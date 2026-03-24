from __future__ import annotations

import logging
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSequentialAnimationGroup,
    Property,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.resources import team_color, team_full_display_name
from app.services import ScoreboardService

log = logging.getLogger(__name__)

_NBA_FONT = "'Bahnschrift Condensed', 'Franklin Gothic Demi Cond', 'Impact', sans-serif"
_NBA_FONT_ZH = (
    "'Bahnschrift Condensed', 'Franklin Gothic Demi Cond', 'Impact', "
    "'PingFang SC', 'Microsoft YaHei', Inter, 'Segoe UI', "
    "'Helvetica Neue', sans-serif"
)

_HEADSHOT_URL = "https://cdn.nba.com/headshots/nba/latest/260x190/{person_id}.png"

_ADV_STAT_KEYS = [
    ("TS%", "ts_pct", "pct"),
    ("eFG%", "efg_pct", "pct"),
    ("FG%", "fg_pct", "pct"),
    ("3P%", "tp_pct", "pct"),
    ("FT%", "ft_pct", "pct"),
    ("+/-", "plus_minus", "pm"),
    ("MIN", "minutes", "min"),
    ("TOV", "turnovers", "int"),
]

_ADV_STAT_KEYS_ZH = [
    ("真实%", "ts_pct", "pct"),
    ("有效%", "efg_pct", "pct"),
    ("投篮%", "fg_pct", "pct"),
    ("三分%", "tp_pct", "pct"),
    ("罚球%", "ft_pct", "pct"),
    ("+/-", "plus_minus", "pm"),
    ("时间", "minutes", "min"),
    ("失误", "turnovers", "int"),
]

_POS_ZH = {
    "G": "后卫",
    "F": "前锋",
    "C": "中锋",
    "PG": "控球后卫",
    "SG": "得分后卫",
    "SF": "小前锋",
    "PF": "大前锋",
    "G-F": "后卫-前锋",
    "F-G": "前锋-后卫",
    "F-C": "前锋-中锋",
    "C-F": "中锋-前锋",
}


def _contrast_text(bg: QColor) -> str:
    lum = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
    return "#ffffff" if lum < 160 else "#111111"


def _team_palette_detail(tc: QColor) -> dict:
    txt = _contrast_text(tc)
    is_light = txt == "#111111"
    if is_light:
        return {
            "txt": txt,
            "txt_sub": "rgba(0,0,0,140)",
            "txt_dim": "rgba(0,0,0,90)",
            "card_bg": "rgba(0,0,0,8)",
            "stat_val": "#000000",
        }
    return {
        "txt": txt,
        "txt_sub": "rgba(255,255,255,160)",
        "txt_dim": "rgba(255,255,255,100)",
        "card_bg": "rgba(255,255,255,10)",
        "stat_val": "#ffffff",
    }


class ShotChartWidget(QWidget):
    """NBA half-court shot chart rendered with QPainter."""

    COURT_W = 220
    COURT_H = 200

    _NBA_X_MIN, _NBA_X_MAX = -250, 250
    _NBA_Y_MIN, _NBA_Y_MAX = -52, 420

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(self.COURT_W, self.COURT_H)
        self._shots: list[dict] = []
        self._line_color = QColor(255, 255, 255, 50)
        self._court_bg = QColor(20, 20, 24)
        self._made_color = QColor("#22c55e")
        self._miss_color = QColor("#ef4444")

        nba_w = self._NBA_X_MAX - self._NBA_X_MIN
        nba_h = self._NBA_Y_MAX - self._NBA_Y_MIN
        pad = 5
        draw_w = self.COURT_W - 2 * pad
        draw_h = self.COURT_H - 2 * pad
        self._scale = min(draw_w / nba_w, draw_h / nba_h)
        actual_w = nba_w * self._scale
        self._offset_x = pad + (draw_w - actual_w) / 2
        self._offset_y = pad

    def set_shots(self, shots: list[dict]) -> None:
        self._shots = shots
        self.update()

    def _to_screen(self, nba_x: float, nba_y: float) -> tuple[float, float]:
        sx = (nba_x - self._NBA_X_MIN) * self._scale + self._offset_x
        sy = (nba_y - self._NBA_Y_MIN) * self._scale + self._offset_y
        return sx, sy

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self._court_bg)
        self._draw_court(p)
        self._draw_shots(p)
        p.end()

    def _draw_court(self, p: QPainter) -> None:
        pen = QPen(self._line_color, 1.2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        x1, y1 = self._to_screen(-250, -52)
        x2, y2 = self._to_screen(250, 420)
        p.drawRect(QRectF(x1, y1, x2 - x1, y2 - y1))

        px1, py1 = self._to_screen(-80, -52)
        px2, py2 = self._to_screen(80, 190)
        p.drawRect(QRectF(px1, py1, px2 - px1, py2 - py1))

        cx, cy = self._to_screen(0, 190)
        r_ft = 60 * self._scale
        p.drawEllipse(QPointF(cx, cy), r_ft, r_ft)

        bx, by = self._to_screen(0, 0)
        r_basket = 7.5 * self._scale
        basket_pen = QPen(QColor(255, 120, 50, 180), 1.5)
        p.setPen(basket_pen)
        p.drawEllipse(QPointF(bx, by), r_basket, r_basket)

        p.setPen(pen)
        bb_x1, bb_y = self._to_screen(-30, -7.5)
        bb_x2, _ = self._to_screen(30, -7.5)
        p.drawLine(QPointF(bb_x1, bb_y), QPointF(bb_x2, bb_y))

        ra_cx, ra_cy = self._to_screen(0, 0)
        r_ra = 40 * self._scale
        path_ra = QPainterPath()
        path_ra.moveTo(ra_cx - r_ra, ra_cy)
        for deg in range(0, 181, 3):
            rad = math.radians(deg)
            x = -r_ra * math.cos(rad) + ra_cx
            y = r_ra * math.sin(rad) + ra_cy
            path_ra.lineTo(x, y)
        p.drawPath(path_ra)

        path_3pt = QPainterPath()
        rx1, ry1 = self._to_screen(220, -52)
        path_3pt.moveTo(rx1, ry1)
        corner_y = math.sqrt(237.5**2 - 220**2)
        rx2, ry2 = self._to_screen(220, corner_y)
        path_3pt.lineTo(rx2, ry2)
        theta_start = math.atan2(corner_y, 220)
        theta_end = math.pi - theta_start
        for i in range(61):
            theta = theta_start + (theta_end - theta_start) * i / 60
            nx = 237.5 * math.cos(theta)
            ny = 237.5 * math.sin(theta)
            sx, sy = self._to_screen(nx, ny)
            path_3pt.lineTo(sx, sy)
        lx1, ly1 = self._to_screen(-220, corner_y)
        path_3pt.lineTo(lx1, ly1)
        lx2, ly2 = self._to_screen(-220, -52)
        path_3pt.lineTo(lx2, ly2)
        p.drawPath(path_3pt)

    def _draw_shots(self, p: QPainter) -> None:
        if not self._shots:
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.NoBrush)
            no_data_pen = QPen(QColor(255, 255, 255, 60))
            p.setPen(no_data_pen)
            p.drawText(self.rect(), Qt.AlignCenter, "No shot data")
            return

        shot_r = 3.0
        drawn = 0
        made = 0
        for shot in self._shots:
            x_val = shot.get("x")
            y_val = shot.get("y")
            if x_val is None or y_val is None:
                continue
            try:
                sx, sy = self._to_screen(float(x_val), float(y_val))
            except (TypeError, ValueError):
                continue
            if sx < 0 or sx > self.COURT_W or sy < 0 or sy > self.COURT_H:
                continue
            drawn += 1
            if shot.get("made"):
                made += 1
                p.setPen(QPen(self._made_color, 1.2))
                p.setBrush(QBrush(QColor(34, 197, 94, 100)))
            else:
                p.setPen(QPen(self._miss_color, 1.0))
                p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(sx, sy), shot_r, shot_r)

        if drawn == 0:
            no_data_pen = QPen(QColor(255, 255, 255, 60))
            p.setPen(no_data_pen)
            p.drawText(self.rect(), Qt.AlignCenter, "No shot data")
            return

        missed = drawn - made
        pct = (made / drawn * 100) if drawn > 0 else 0
        legend_y = self.COURT_H - 14
        legend_font = p.font()
        legend_font.setPixelSize(9)
        p.setFont(legend_font)

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self._made_color))
        p.drawEllipse(QPointF(8, legend_y), 3, 3)
        p.setPen(QPen(QColor(255, 255, 255, 140)))
        p.drawText(QRectF(14, legend_y - 6, 50, 12), Qt.AlignLeft, f"Made ({made})")

        p.setPen(QPen(self._miss_color, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(80, legend_y), 3, 3)
        p.setPen(QPen(QColor(255, 255, 255, 140)))
        p.drawText(QRectF(86, legend_y - 6, 60, 12), Qt.AlignLeft, f"Miss ({missed})")

        p.drawText(
            QRectF(150, legend_y - 6, 65, 12),
            Qt.AlignRight,
            f"FG: {pct:.1f}%",
        )


class _FetchResultSignal(QWidget):
    """Helper to marshal background thread results to the UI thread."""
    result_ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()


class _DetailCard(QFrame):
    """Animated detail card with height slide."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("playerDetailCard")

    def _get_anim_height(self) -> int:
        return self.maximumHeight()

    def _set_anim_height(self, h: int) -> None:
        self.setMaximumHeight(max(0, int(h)))

    animHeight = Property(int, _get_anim_height, _set_anim_height)  # type: ignore[assignment]


class PlayerDetailWindow(QWidget):
    """Floating player detail panel showing headshot, advanced stats, and shot chart."""

    PANEL_W = 260
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(
            parent,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(self.PANEL_W)

        self._executor = ThreadPoolExecutor(max_workers=2)
        self._current_person_id: int = 0
        self._team_color = QColor("#333")
        self._show_anim: Optional[QSequentialAnimationGroup] = None
        self._hide_anim: Optional[QPropertyAnimation] = None
        self._result_signal = _FetchResultSignal(self)
        self._result_signal.result_ready.connect(self._apply_fetched_data)
        self._ref_window: Optional[QWidget] = None
        self._language: str = "en"
        self._player_info: dict = {}
        self._team_tricode: str = ""

        self._build_ui()

    @property
    def _font(self) -> str:
        return _NBA_FONT_ZH if self._language == "zh" else _NBA_FONT

    @property
    def _stat_keys(self) -> list:
        return _ADV_STAT_KEYS_ZH if self._language == "zh" else _ADV_STAT_KEYS

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._card = _DetailCard(self)
        card_lay = QVBoxLayout(self._card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        self._header = QFrame()
        self._header.setFixedHeight(80)
        h_lay = QHBoxLayout(self._header)
        h_lay.setContentsMargins(12, 8, 12, 8)
        h_lay.setSpacing(12)

        self._headshot_label = QLabel()
        self._headshot_label.setFixedSize(60, 60)
        self._headshot_label.setAlignment(Qt.AlignCenter)
        self._headshot_label.setStyleSheet(
            "background: rgba(255,255,255,15); border-radius: 30px;"
        )
        h_lay.addWidget(self._headshot_label)

        info_w = QWidget()
        info_w.setStyleSheet("background:transparent;")
        info_lay = QVBoxLayout(info_w)
        info_lay.setContentsMargins(0, 4, 0, 4)
        info_lay.setSpacing(2)

        self._name_label = QLabel("—")
        self._name_label.setStyleSheet(
            f"color:#fff; font-family:{_NBA_FONT}; font-weight:900; "
            "font-size:18px; background:transparent;"
        )
        info_lay.addWidget(self._name_label)

        self._meta_label = QLabel("")
        self._meta_label.setStyleSheet(
            "color:rgba(255,255,255,180); font-size:12px; background:transparent;"
        )
        info_lay.addWidget(self._meta_label)

        self._game_stats_label = QLabel("")
        self._game_stats_label.setStyleSheet(
            f"color:rgba(255,255,255,220); font-family:{_NBA_FONT}; "
            "font-size:14px; font-weight:700; background:transparent;"
        )
        info_lay.addWidget(self._game_stats_label)
        info_lay.addStretch()

        h_lay.addWidget(info_w, 1)
        card_lay.addWidget(self._header)

        self._stats_container = QFrame()
        self._stats_container.setObjectName("advStatsContainer")
        self._stats_container.setStyleSheet(
            "#advStatsContainer { background: rgba(0,0,0,40); border: none; }"
        )
        stats_lay = QVBoxLayout(self._stats_container)
        stats_lay.setContentsMargins(12, 8, 12, 8)
        stats_lay.setSpacing(4)

        self._stats_title = QLabel("ADVANCED")
        self._stats_title.setStyleSheet(
            "color:rgba(255,255,255,100); font-size:8px; font-weight:700; "
            "background:transparent; letter-spacing:2px;"
        )
        stats_lay.addWidget(self._stats_title)

        self._stats_grid_w = QWidget()
        self._stats_grid_w.setStyleSheet("background:transparent;")
        self._stats_grid = QGridLayout(self._stats_grid_w)
        self._stats_grid.setContentsMargins(0, 0, 0, 0)
        self._stats_grid.setHorizontalSpacing(4)
        self._stats_grid.setVerticalSpacing(4)

        self._stat_value_labels: list[QLabel] = []
        self._stat_name_labels: list[QLabel] = []
        for i, (label, _, _fmt) in enumerate(_ADV_STAT_KEYS):
            row = i // 4
            col = i % 4
            cell = QWidget()
            cell.setStyleSheet("background:transparent;")
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(1)

            val_lbl = QLabel("—")
            val_lbl.setAlignment(Qt.AlignCenter)
            val_lbl.setStyleSheet(
                f"color:#fff; font-family:{_NBA_FONT}; font-size:14px; "
                "font-weight:700; background:transparent;"
            )
            cl.addWidget(val_lbl)
            self._stat_value_labels.append(val_lbl)

            name_lbl = QLabel(label)
            name_lbl.setAlignment(Qt.AlignCenter)
            name_lbl.setStyleSheet(
                "color:rgba(255,255,255,100); font-size:8px; font-weight:600; "
                "background:transparent;"
            )
            cl.addWidget(name_lbl)
            self._stat_name_labels.append(name_lbl)

            self._stats_grid.addWidget(cell, row, col)
        stats_lay.addWidget(self._stats_grid_w)
        card_lay.addWidget(self._stats_container)

        self._chart_container = QFrame()
        self._chart_container.setObjectName("chartContainer")
        self._chart_container.setStyleSheet(
            "#chartContainer { background: rgba(0,0,0,20); border: none; "
            "border-bottom-left-radius: 10px; border-bottom-right-radius: 10px; }"
        )
        chart_lay = QVBoxLayout(self._chart_container)
        chart_lay.setContentsMargins(10, 6, 10, 8)
        chart_lay.setSpacing(4)

        self._chart_title = QLabel("SHOT CHART")
        self._chart_title.setStyleSheet(
            "color:rgba(255,255,255,100); font-size:8px; font-weight:700; "
            "background:transparent; letter-spacing:2px;"
        )
        chart_lay.addWidget(self._chart_title)

        self._shot_chart = ShotChartWidget(self)
        chart_lay.addWidget(self._shot_chart, 0, Qt.AlignHCenter)

        card_lay.addWidget(self._chart_container)
        root.addWidget(self._card)

    def show_player(
        self,
        player_info: dict,
        game_id: str,
        team_tricode: str,
        ref_window: Optional[QWidget] = None,
        language: str = "en",
    ) -> None:
        person_id = player_info.get("personId", 0)
        player_name = player_info.get("name", "")
        identity_key = person_id or hash(player_name)

        if identity_key == self._current_person_id and self.isVisible():
            self.hide_animated()
            return

        self._current_person_id = identity_key
        self._language = language
        self._player_info = player_info
        self._team_tricode = team_tricode
        tc = team_color(team_tricode)
        self._team_color = tc
        pal = _team_palette_detail(tc)
        font = self._font
        is_zh = language == "zh"

        self._name_label.setText(player_info.get("name", "—"))
        jersey = player_info.get("jerseyNum", "")
        pos = player_info.get("position", "")
        meta_parts = []
        if jersey:
            meta_parts.append(f"#{jersey}")
        if pos:
            display_pos = _POS_ZH.get(pos.upper(), pos) if is_zh else pos
            meta_parts.append(display_pos)
        team_name = team_full_display_name(team_tricode, language)
        if team_name:
            meta_parts.append(team_name)
        self._meta_label.setText("  |  ".join(meta_parts))

        pts = player_info.get("points", 0)
        ast = player_info.get("assists", 0)
        reb = player_info.get("rebounds", 0)
        if is_zh:
            self._game_stats_label.setText(f"{pts} 得分   {ast} 助攻   {reb} 篮板")
        else:
            self._game_stats_label.setText(f"{pts} PTS   {ast} AST   {reb} REB")

        txt = _contrast_text(tc)
        self._header.setStyleSheet(
            f"background:{tc.name()}; "
            "border-top-left-radius:10px; border-top-right-radius:10px;"
        )
        self._name_label.setStyleSheet(
            f"color:{txt}; font-family:{font}; font-weight:900; "
            "font-size:18px; background:transparent;"
        )
        self._meta_label.setStyleSheet(
            f"color:{pal['txt_sub']}; font-family:{font}; "
            "font-size:12px; background:transparent;"
        )
        self._game_stats_label.setStyleSheet(
            f"color:{pal['txt']}; font-family:{font}; "
            "font-size:14px; font-weight:700; background:transparent;"
        )

        darker = QColor(tc)
        darker.setRed(max(0, int(darker.red() * 0.6)))
        darker.setGreen(max(0, int(darker.green() * 0.6)))
        darker.setBlue(max(0, int(darker.blue() * 0.6)))
        self._stats_container.setStyleSheet(
            f"#advStatsContainer {{ background: {darker.name()}; border: none; }}"
        )

        darkest = QColor(darker)
        darkest.setRed(max(0, int(darkest.red() * 0.7)))
        darkest.setGreen(max(0, int(darkest.green() * 0.7)))
        darkest.setBlue(max(0, int(darkest.blue() * 0.7)))
        self._chart_container.setStyleSheet(
            f"#chartContainer {{ background: {darkest.name()}; border: none; "
            f"border-bottom-left-radius: 10px; border-bottom-right-radius: 10px; }}"
        )

        stat_keys = self._stat_keys
        for i, (label, _, _fmt) in enumerate(stat_keys):
            self._stat_value_labels[i].setText("—")
            self._stat_value_labels[i].setStyleSheet(
                f"color:{_contrast_text(darker)}; font-family:{font}; "
                "font-size:14px; font-weight:700; background:transparent;"
            )
            self._stat_name_labels[i].setText(label)
            self._stat_name_labels[i].setStyleSheet(
                f"color:{_contrast_text(darker)}80; font-family:{font}; "
                "font-size:8px; font-weight:600; background:transparent;"
            )
        self._stats_title.setText("高阶数据" if is_zh else "ADVANCED")
        self._stats_title.setStyleSheet(
            f"color:{_contrast_text(darker)}60; font-family:{font}; "
            "font-size:8px; font-weight:700; "
            "background:transparent; letter-spacing:2px;"
        )
        self._chart_title.setText("投篮图" if is_zh else "SHOT CHART")
        self._chart_title.setStyleSheet(
            f"color:{_contrast_text(darkest)}60; font-family:{font}; "
            "font-size:8px; font-weight:700; "
            "background:transparent; letter-spacing:2px;"
        )
        self._shot_chart.set_shots([])

        self._headshot_label.setPixmap(QPixmap())
        self._headshot_label.setStyleSheet(
            f"background: {pal['card_bg']}; border-radius: 30px;"
        )

        self._ref_window = ref_window
        self._reposition()

        self.show()
        self.raise_()
        self._animate_show()

        team_id = player_info.get("teamId", 0)
        if person_id:
            self._executor.submit(self._fetch_all, game_id, person_id, team_id, identity_key)

    def set_language(self, language: str) -> None:
        """Update all language-dependent text and fonts without closing the panel."""
        if language == self._language:
            return
        self._language = language
        self._update_labels()

    def _update_labels(self) -> None:
        """Refresh text and font for all language-sensitive labels."""
        info = self._player_info
        if not info:
            return
        font = self._font
        is_zh = self._language == "zh"
        tc = self._team_color
        pal = _team_palette_detail(tc)

        self._name_label.setStyleSheet(
            f"color:{_contrast_text(tc)}; font-family:{font}; font-weight:900; "
            "font-size:18px; background:transparent;"
        )

        jersey = info.get("jerseyNum", "")
        pos = info.get("position", "")
        meta_parts = []
        if jersey:
            meta_parts.append(f"#{jersey}")
        if pos:
            display_pos = _POS_ZH.get(pos.upper(), pos) if is_zh else pos
            meta_parts.append(display_pos)
        team_name = team_full_display_name(self._team_tricode, self._language)
        if team_name:
            meta_parts.append(team_name)
        self._meta_label.setText("  |  ".join(meta_parts))
        self._meta_label.setStyleSheet(
            f"color:{pal['txt_sub']}; font-family:{font}; "
            "font-size:12px; background:transparent;"
        )

        pts = info.get("points", 0)
        ast = info.get("assists", 0)
        reb = info.get("rebounds", 0)
        if is_zh:
            self._game_stats_label.setText(f"{pts} 得分   {ast} 助攻   {reb} 篮板")
        else:
            self._game_stats_label.setText(f"{pts} PTS   {ast} AST   {reb} REB")
        self._game_stats_label.setStyleSheet(
            f"color:{pal['txt']}; font-family:{font}; "
            "font-size:14px; font-weight:700; background:transparent;"
        )

        darker = QColor(tc)
        darker.setRed(max(0, int(darker.red() * 0.6)))
        darker.setGreen(max(0, int(darker.green() * 0.6)))
        darker.setBlue(max(0, int(darker.blue() * 0.6)))

        stat_keys = self._stat_keys
        for i, (label, _, _fmt) in enumerate(stat_keys):
            self._stat_name_labels[i].setText(label)
            self._stat_name_labels[i].setStyleSheet(
                f"color:{_contrast_text(darker)}80; font-family:{font}; "
                "font-size:8px; font-weight:600; background:transparent;"
            )
            self._stat_value_labels[i].setStyleSheet(
                f"color:{_contrast_text(darker)}; font-family:{font}; "
                "font-size:14px; font-weight:700; background:transparent;"
            )

        self._stats_title.setText("高阶数据" if is_zh else "ADVANCED")
        self._stats_title.setStyleSheet(
            f"color:{_contrast_text(darker)}60; font-family:{font}; "
            "font-size:8px; font-weight:700; "
            "background:transparent; letter-spacing:2px;"
        )

        darkest = QColor(darker)
        darkest.setRed(max(0, int(darkest.red() * 0.7)))
        darkest.setGreen(max(0, int(darkest.green() * 0.7)))
        darkest.setBlue(max(0, int(darkest.blue() * 0.7)))
        self._chart_title.setText("投篮图" if is_zh else "SHOT CHART")
        self._chart_title.setStyleSheet(
            f"color:{_contrast_text(darkest)}60; font-family:{font}; "
            "font-size:8px; font-weight:700; "
            "background:transparent; letter-spacing:2px;"
        )

    def _reposition(self) -> None:
        """Align this panel to the right edge of the reference window."""
        if self._ref_window and self._ref_window.isVisible():
            geo = self._ref_window.geometry()
            self.move(geo.right() + 8, geo.top())

    def follow_ref_window(self) -> None:
        """Called by the host window on moveEvent to stay attached."""
        if self.isVisible():
            self._reposition()

    def hide_animated(self) -> None:
        self._current_person_id = 0
        self.hide()
        self.closed.emit()

    def _animate_show(self) -> None:
        if self._show_anim:
            self._show_anim.stop()
        self._card.setMaximumHeight(0)
        target_h = self._card.sizeHint().height()
        if target_h <= 0:
            target_h = 500

        anim = QPropertyAnimation(self._card, b"animHeight", self)
        anim.setDuration(250)
        anim.setStartValue(0)
        anim.setEndValue(target_h)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _unlock():
            self._card.setMaximumHeight(16777215)

        anim.finished.connect(_unlock)
        self._show_anim = QSequentialAnimationGroup(self)
        self._show_anim.addAnimation(anim)
        self._show_anim.start()

    def _fetch_all(self, game_id: str, person_id: int, team_id: int, identity_key: int) -> None:
        service = ScoreboardService(timeout=15)
        try:
            headshot_data = self._download_headshot(person_id)
        except Exception:
            headshot_data = None
        try:
            adv_stats = service.fetch_player_advanced_stats(game_id, person_id)
        except Exception:
            adv_stats = {}
        try:
            shots = service.fetch_shot_chart(game_id, person_id, team_id)
        except Exception:
            shots = []

        self._result_signal.result_ready.emit({
            "identity_key": identity_key,
            "headshot": headshot_data,
            "adv_stats": adv_stats,
            "shots": shots,
        })

    @staticmethod
    def _download_headshot(person_id: int) -> Optional[bytes]:
        url = _HEADSHOT_URL.format(person_id=person_id)
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.read()
        except Exception as exc:
            log.debug("Headshot download failed for %d: %s", person_id, exc)
            return None

    def _apply_fetched_data(self, data: dict) -> None:
        if data.get("identity_key") != self._current_person_id:
            return

        headshot_bytes = data.get("headshot")
        if headshot_bytes:
            px = QPixmap()
            px.loadFromData(headshot_bytes)
            if not px.isNull():
                scaled = px.scaled(
                    60, 60, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                )
                x_off = (scaled.width() - 60) // 2
                y_off = (scaled.height() - 60) // 2
                cropped = scaled.copy(x_off, y_off, 60, 60)
                self._headshot_label.setPixmap(cropped)
                self._headshot_label.setMask(
                    QRegion(0, 0, 60, 60, QRegion.Ellipse)
                )

        adv = data.get("adv_stats", {})
        if adv:
            for i, (_, key, fmt) in enumerate(_ADV_STAT_KEYS):
                val = adv.get(key)
                if val is None:
                    continue
                try:
                    if fmt == "pct":
                        self._stat_value_labels[i].setText(f"{float(val) * 100:.1f}")
                    elif fmt == "pm":
                        v = float(val)
                        self._stat_value_labels[i].setText(
                            f"+{v:.0f}" if v > 0 else f"{v:.0f}"
                        )
                    elif fmt == "min":
                        self._stat_value_labels[i].setText(self._parse_minutes(str(val)))
                    else:
                        self._stat_value_labels[i].setText(str(int(val)))
                except (TypeError, ValueError):
                    self._stat_value_labels[i].setText(str(val))

        shots = data.get("shots", [])
        self._shot_chart.set_shots(shots)

    @staticmethod
    def _parse_minutes(raw: str) -> str:
        if not raw:
            return "0"
        raw = raw.strip()
        if raw.startswith("PT") and "M" in raw:
            raw = raw[2:]
            parts = raw.split("M", 1)
            return parts[0]
        return raw

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.hide_animated()
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            self.hide_animated()
        super().mousePressEvent(event)
