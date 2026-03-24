from __future__ import annotations

import random
from typing import Dict, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    Property,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QPauseAnimation,
    QSequentialAnimationGroup,
    Qt,
    QRect,
    QSize,
    QEvent,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QImage, QPixmap, QRegion
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.models import GameDiff, GameState, GameStatus
from app.resources import team_color, team_logo_path, team_display_name, team_full_display_name

THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "container_bg": "#18181b",
        "container_border": "#27272a",
        "info_bar_bg": "#09090b",
        "separator": "rgba(255,255,255,15)",
        "text_primary": "#fafafa",
        "text_secondary": "#a1a1aa",
        "delta_color": "#fbbf24",
        "live_color": "#22c55e",
        "final_color": "#a1a1aa",
        "expanded_bg": "#131316",
        "expanded_header": "#71717a",
        "expanded_text": "#d4d4d8",
        "expanded_border": "#27272a",
        "expanded_row_alt": "#1c1c21",
        "expanded_stat_accent": "#fafafa",
    },
    "light": {
        "container_bg": "#f4f4f5",
        "container_border": "#d4d4d8",
        "info_bar_bg": "#e4e4e7",
        "separator": "rgba(0,0,0,20)",
        "text_primary": "#18181b",
        "text_secondary": "#52525b",
        "delta_color": "#dc2626",
        "live_color": "#16a34a",
        "final_color": "#71717a",
        "expanded_bg": "#ebebef",
        "expanded_header": "#71717a",
        "expanded_text": "#3f3f46",
        "expanded_border": "#d4d4d8",
        "expanded_row_alt": "#e1e1e6",
        "expanded_stat_accent": "#18181b",
    },
    "broadcast": {
        "container_bg": "rgba(0,0,0,204)",
        "container_border": "rgba(255,255,255,10)",
        "info_bar_bg": "rgba(0,0,0,235)",
        "separator": "rgba(255,255,255,10)",
        "text_primary": "#fafafa",
        "text_secondary": "#a1a1aa",
        "delta_color": "#fbbf24",
        "live_color": "#22c55e",
        "final_color": "#a1a1aa",
        "expanded_bg": "rgba(0,0,0,230)",
        "expanded_header": "#71717a",
        "expanded_text": "#d4d4d8",
        "expanded_border": "rgba(255,255,255,10)",
        "expanded_row_alt": "rgba(255,255,255,8)",
        "expanded_stat_accent": "#fafafa",
    },
}

_NBA_FONT = "'Bahnschrift Condensed', 'Franklin Gothic Demi Cond', 'Impact', sans-serif"
_NBA_FONT_ZH = (
    "'Bahnschrift Condensed', 'Franklin Gothic Demi Cond', 'Impact', "
    "'PingFang SC', 'Microsoft YaHei', Inter, 'Segoe UI', "
    "'Helvetica Neue', sans-serif"
)


def _contrast_text(bg: QColor) -> str:
    lum = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
    return "#ffffff" if lum < 160 else "#111111"


def _team_palette(tc: QColor) -> dict:
    """Derive a full text palette from a team background color (integer alpha)."""
    txt = _contrast_text(tc)
    is_light_bg = txt == "#111111"
    if is_light_bg:
        return {
            "txt": txt,
            "txt_sub": "rgba(0,0,0,128)",
            "txt_dim": "rgba(0,0,0,184)",
            "alt_row": "rgba(0,0,0,13)",
            "border": "rgba(0,0,0,31)",
        }
    return {
        "txt": txt,
        "txt_sub": "rgba(255,255,255,128)",
        "txt_dim": "rgba(255,255,255,184)",
        "alt_row": "rgba(255,255,255,18)",
        "border": "rgba(255,255,255,36)",
    }


class FadableLabel(QLabel):
    """支持透明度动画的标签。"""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity = 1.0

    def getOpacity(self) -> float:  # noqa: N802
        return self._opacity

    def setOpacity(self, value: float) -> None:  # noqa: N802
        self._opacity = value
        self._opacity_effect.setOpacity(value)

    opacity = Property(float, getOpacity, setOpacity)  # type: ignore[assignment]


class _BubbleFrame(QFrame):
    """带高度滑动动画的气泡容器（不使用 QGraphicsOpacityEffect）。"""

    def __init__(self, object_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName(object_name)

    def _get_anim_height(self) -> int:
        return self.maximumHeight()

    def _set_anim_height(self, h: int) -> None:
        self.setMaximumHeight(max(0, int(h)))

    animHeight = Property(int, _get_anim_height, _set_anim_height)  # type: ignore[assignment]


class ScoreboardWidget(QWidget):
    """ESPN/TNT 风格体育转播记分牌控件。

    紧凑模式：双行团队栏 + 信息栏（NBA 风格缩窄字体）
    展开模式：三个圆角气泡面板（节次得分 / 客队球员 / 主队球员），带高度滑动动画
    球员气泡背景色 = 对应球队得分栏颜色。
    """

    period_clicked = Signal()
    team_bar_right_clicked = Signal(str)
    expand_toggled = Signal(bool)
    collapse_done = Signal()
    layout_changed = Signal()
    player_clicked = Signal(object)

    WIDGET_WIDTH = 240
    _TEAM_BAR_H = 50
    _INFO_BAR_H = 26
    _MAX_TIMEOUTS = 7

    _BUBBLE_IN_DURATION = 220
    _BUBBLE_IN_STAGGER = 60
    _BUBBLE_OUT_DURATION = 160
    _BUBBLE_OUT_STAGGER = 35

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._expanded = False
        self._language = "en"
        self._theme_name = "dark"
        self._theme = THEMES["dark"]
        self._timeout_team_tricode = ""
        self._away_tricode = ""
        self._home_tricode = ""
        self._away_timeouts_remaining = 0
        self._home_timeouts_remaining = 0
        self._current_game: Optional[GameState] = None
        self._logo_color_cache: dict[str, str] = {}
        self._bubble_expand_anim: Optional[QParallelAnimationGroup] = None
        self._bubble_collapse_anim: Optional[QParallelAnimationGroup] = None
        self._player_label_map: dict[int, dict] = {}
        self._build_ui()
        self._apply_theme_styles()

    @property
    def _font(self) -> str:
        return _NBA_FONT_ZH if self._language == "zh" else _NBA_FONT

    # ── Build UI ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setFixedWidth(self.WIDGET_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._scorebug = QFrame()
        self._scorebug.setObjectName("scorebug")
        bug = QVBoxLayout(self._scorebug)
        bug.setContentsMargins(0, 0, 0, 0)
        bug.setSpacing(0)

        self.away_bar = self._make_team_bar()
        self._sep_line = QFrame()
        self._sep_line.setFixedHeight(1)
        self.home_bar = self._make_team_bar()
        self._info_bar = self._build_info_bar()

        bug.addWidget(self.away_bar)
        bug.addWidget(self._sep_line)
        bug.addWidget(self.home_bar)
        bug.addWidget(self._info_bar)
        root.addWidget(self._scorebug)

        self._bubble_period = self._build_period_bubble()
        self._bubble_away = self._build_stats_bubble("bubbleAway")
        self._bubble_home = self._build_stats_bubble("bubbleHome")
        self._bubbles: list[_BubbleFrame] = [
            self._bubble_period,
            self._bubble_away,
            self._bubble_home,
        ]
        for b in self._bubbles:
            b.setVisible(False)
            root.addWidget(b)

        self.away_delta = FadableLabel("", self)
        self.home_delta = FadableLabel("", self)
        self.away_delta.hide()
        self.home_delta.hide()

        self._reset_display()

    def _make_team_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(self._TEAM_BAR_H)
        bar.setCursor(Qt.PointingHandCursor)
        bar.installEventFilter(self)

        lay = QGridLayout(bar)
        lay.setContentsMargins(6, 4, 10, 4)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(3)

        logo = QLabel()
        logo.setFixedSize(38, 38)
        logo.setScaledContents(True)
        logo.setStyleSheet("background:transparent;")

        name = QLabel("---")
        name.setMinimumWidth(36)

        timeout_w = QWidget()
        timeout_w.setStyleSheet("background:transparent;")
        t_lay = QHBoxLayout(timeout_w)
        t_lay.setContentsMargins(0, 0, 0, 0)
        t_lay.setSpacing(3)
        blocks: List[QFrame] = []
        for _ in range(self._MAX_TIMEOUTS):
            dot = QFrame()
            dot.setFixedSize(7, 7)
            t_lay.addWidget(dot)
            blocks.append(dot)
        t_lay.addStretch()

        score = QLabel("-")
        score.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        score.setMinimumWidth(48)

        lay.addWidget(logo, 0, 0, 2, 1, Qt.AlignVCenter)
        lay.addWidget(name, 0, 1, Qt.AlignLeft | Qt.AlignBottom)
        lay.addWidget(timeout_w, 1, 1, Qt.AlignLeft | Qt.AlignTop)
        lay.addWidget(score, 0, 2, 2, 1, Qt.AlignRight | Qt.AlignVCenter)
        lay.setColumnStretch(1, 1)
        lay.setRowStretch(0, 3)
        lay.setRowStretch(1, 2)

        bar._logo_label = logo  # type: ignore[attr-defined]
        bar._name_label = name  # type: ignore[attr-defined]
        bar._score_label = score  # type: ignore[attr-defined]
        bar._timeout_blocks = blocks  # type: ignore[attr-defined]
        bar._timeout_widget = timeout_w  # type: ignore[attr-defined]
        bar._team_tricode = ""  # type: ignore[attr-defined]
        bar._score_anim = None  # type: ignore[attr-defined]
        bar._anim_labels: list[QLabel] = []  # type: ignore[attr-defined]
        bar._cycle_timer = None  # type: ignore[attr-defined]
        bar._layout = lay  # type: ignore[attr-defined]
        return bar

    def _build_info_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(self._INFO_BAR_H)
        bar.installEventFilter(self)
        bar.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(0)

        self.period_label = QLabel("\u2014")
        self.period_label.setFixedWidth(50)
        self.clock_label = QLabel("--:--")
        self.clock_label.setAlignment(Qt.AlignCenter)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_label.setFixedWidth(65)

        lay.addWidget(self.period_label)
        lay.addStretch()
        lay.addWidget(self.clock_label)
        lay.addStretch()
        lay.addWidget(self.status_label)
        return bar

    # ── Bubble builders ───────────────────────────────────────

    def _build_period_bubble(self) -> _BubbleFrame:
        bubble = _BubbleFrame("bubblePeriod", self)
        lay = QVBoxLayout(bubble)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        self._period_grid_widget = QWidget()
        self._period_grid = QGridLayout(self._period_grid_widget)
        self._period_grid.setContentsMargins(0, 0, 0, 0)
        self._period_grid.setHorizontalSpacing(0)
        self._period_grid.setVerticalSpacing(2)
        lay.addWidget(self._period_grid_widget)
        return bubble

    def _build_stats_bubble(self, name: str) -> _BubbleFrame:
        bubble = _BubbleFrame(name, self)
        lay = QVBoxLayout(bubble)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(2)
        return bubble

    # ── Events ────────────────────────────────────────────────

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.MouseButtonPress:
            if obj in (self.home_bar, self.away_bar) and event.button() == Qt.RightButton:
                tricode = getattr(obj, "_team_tricode", "")
                self.team_bar_right_clicked.emit(tricode)
                return True
            if obj == self._info_bar and event.button() == Qt.LeftButton:
                self.period_clicked.emit()
                return True
            if event.button() == Qt.LeftButton:
                widget_id = id(obj)
                if widget_id in self._player_label_map:
                    self.player_clicked.emit(self._player_label_map[widget_id])
                    return True
        return super().eventFilter(obj, event)

    # ── Theme ─────────────────────────────────────────────────

    def apply_theme(self, theme_name: str = None, **_kw) -> None:
        if theme_name and theme_name in THEMES:
            self._theme_name = theme_name
            self._theme = THEMES[theme_name]
        self._apply_theme_styles()
        if self._current_game:
            self._set_team(self.away_bar, self._current_game.away, False)
            self._set_team(self.home_bar, self._current_game.home, True)
            self._set_timeouts(self.away_bar, self._away_timeouts_remaining)
            self._set_timeouts(self.home_bar, self._home_timeouts_remaining)

    def _apply_theme_styles(self) -> None:
        t = self._theme
        self._scorebug.setStyleSheet(
            f"QFrame#scorebug {{ background: {t['container_bg']}; "
            f"border: 1px solid {t['container_border']}; }}"
        )
        self._sep_line.setStyleSheet(f"background: {t['separator']};")
        self._info_bar.setStyleSheet(f"background: {t['info_bar_bg']};")
        self.period_label.setStyleSheet(
            f"color: {t['text_primary']}; font-family: {self._font}; "
            "font-weight:700; font-size:12px; background:transparent;"
        )
        self.clock_label.setStyleSheet(
            f"color: {t['text_primary']}; font-family: {self._font}; "
            "font-weight:700; font-size:14px; background:transparent;"
        )
        self.status_label.setStyleSheet(
            f"color: {t['text_secondary']}; font-family: {self._font}; "
            "font-weight:700; font-size:10px; background:transparent;"
        )
        self.away_delta.setStyleSheet(
            f"color: {t['delta_color']}; font-family: {self._font}; "
            "font-weight:700; font-size:14px; background:transparent;"
        )
        self.home_delta.setStyleSheet(
            f"color: {t['delta_color']}; font-family: {self._font}; "
            "font-weight:700; font-size:14px; background:transparent;"
        )

        bubble_base = (
            f"background: {t['expanded_bg']}; "
            "border: none; border-radius: 8px;"
        )
        self._bubble_period.setStyleSheet(
            f"#{self._bubble_period.objectName()} {{ {bubble_base} }}"
        )

    # ── Rendering ─────────────────────────────────────────────

    def render_game(self, game: Optional[GameState]) -> None:
        if not game:
            self._current_game = None
            self._reset_display()
            return

        self._current_game = game
        self._set_team(self.away_bar, game.away, False)
        self._set_team(self.home_bar, game.home, True)
        self._away_timeouts_remaining = game.away.timeouts_remaining
        self._home_timeouts_remaining = game.home.timeouts_remaining
        self._set_timeouts(self.away_bar, self._away_timeouts_remaining)
        self._set_timeouts(self.home_bar, self._home_timeouts_remaining)

        if game.is_final:
            period_text = "FIN."
        elif game.period <= 0:
            period_text = game.status_text or ""
        elif game.period > 4:
            period_text = self._format_overtime_period(game.period)
        else:
            period_text = self._format_ordinal_period(game.period)
        self.period_label.setText(period_text or "\u2014")

        if self._is_period_break(game):
            if "HALF" in (game.status_text or "").upper():
                clock_text = "中场休息" if self._language == "zh" else "HALFTIME"
            else:
                clock_text = "休息" if self._language == "zh" else "BREAK"
        elif game.is_final:
            clock_text = ""
        else:
            clock_text = self._format_game_clock(game)
        self.clock_label.setText(clock_text)

        t = self._theme
        tied_text = "平分" if self._language == "zh" else "TIED"
        if game.is_final:
            diff = game.home.score - game.away.score
            if diff > 0:
                lead = f"{team_display_name(game.home.tricode, self._language)} +{diff}"
            elif diff < 0:
                lead = f"{team_display_name(game.away.tricode, self._language)} +{abs(diff)}"
            else:
                lead = tied_text
            self.status_label.setText(lead)
            self.status_label.setStyleSheet(
                f"color: {t['final_color']}; font-family: {self._font}; "
                "font-weight:700; font-size:10px; background:transparent;"
            )
        elif game.is_live:
            diff = game.home.score - game.away.score
            if diff > 0:
                lead = f"{team_display_name(game.home.tricode, self._language)} +{diff}"
            elif diff < 0:
                lead = f"{team_display_name(game.away.tricode, self._language)} +{abs(diff)}"
            else:
                lead = tied_text
            self.status_label.setText(lead)
            self.status_label.setStyleSheet(
                f"color: {t['live_color']}; font-family: {self._font}; "
                "font-weight:700; font-size:10px; background:transparent;"
            )
        elif game.status == GameStatus.NOT_STARTED:
            self.status_label.setText("")
        else:
            self.status_label.setText("")

        if self._expanded:
            self._update_period_scores(game)

    def render_diff(self, diff: GameDiff) -> None:
        away_text = self.away_bar._score_label.text()  # type: ignore[attr-defined]
        home_text = self.home_bar._score_label.text()  # type: ignore[attr-defined]
        old_away = self._safe_int(away_text)
        old_home = self._safe_int(home_text)
        initial_away = away_text == "-"
        initial_home = home_text == "-"

        self.render_game(diff.game)

        if initial_away and diff.game.away.score > 0:
            self._animate_score_initial(self.away_bar, diff.game.away.score)
        elif not initial_away:
            away_delta = diff.delta.away_delta
            if away_delta <= 0 and diff.game.away.score > old_away:
                away_delta = diff.game.away.score - old_away
            if away_delta > 0:
                self._animate_score_roll(
                    self.away_bar, old_away, away_delta, diff.game.away.score
                )

        if initial_home and diff.game.home.score > 0:
            self._animate_score_initial(self.home_bar, diff.game.home.score, delay_ms=120)
        elif not initial_home:
            home_delta = diff.delta.home_delta
            if home_delta <= 0 and diff.game.home.score > old_home:
                home_delta = diff.game.home.score - old_home
            if home_delta > 0:
                self._animate_score_roll(
                    self.home_bar, old_home, home_delta, diff.game.home.score
                )

    def _reset_display(self) -> None:
        self._set_team(self.away_bar, None, False)
        self._set_team(self.home_bar, None, True)
        self._away_timeouts_remaining = 0
        self._home_timeouts_remaining = 0
        self._set_timeouts(self.away_bar, 0)
        self._set_timeouts(self.home_bar, 0)
        self.period_label.setText("\u2014")
        self.clock_label.setText("--:--")
        self.status_label.setText("")

    # ── Logo-based color extraction ───────────────────────────

    def _logo_bg_color(self, path, tricode: str) -> QColor:
        key = str(path)
        cached = self._logo_color_cache.get(key)
        if cached:
            return QColor(cached)

        image = QImage(key)
        if image.isNull():
            return team_color(tricode)

        sample = image.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        edge_whites = 0
        edge_total = 0
        for x in range(sample.width()):
            for y in (0, sample.height() - 1):
                c = sample.pixelColor(x, y)
                if c.alpha() < 10:
                    continue
                edge_total += 1
                if c.value() > 230 and c.saturation() < 30:
                    edge_whites += 1
        for y in range(sample.height()):
            for x in (0, sample.width() - 1):
                c = sample.pixelColor(x, y)
                if c.alpha() < 10:
                    continue
                edge_total += 1
                if c.value() > 230 and c.saturation() < 30:
                    edge_whites += 1

        if edge_total > 0 and (edge_whites / edge_total) >= 0.6:
            self._logo_color_cache[key] = "#ffffff"
            return QColor("#ffffff")

        bins: dict[tuple[int, int, int], list[int]] = {}
        for x in range(sample.width()):
            for y in range(sample.height()):
                c = sample.pixelColor(x, y)
                if c.alpha() < 10:
                    continue
                if c.value() > 240 and c.saturation() < 30:
                    continue
                r, g, b = c.red(), c.green(), c.blue()
                bk = (r // 16, g // 16, b // 16)
                if bk not in bins:
                    bins[bk] = [0, 0, 0, 0]
                bins[bk][0] += 1
                bins[bk][1] += r
                bins[bk][2] += g
                bins[bk][3] += b

        if not bins:
            return team_color(tricode)

        dominant = max(bins.values(), key=lambda v: v[0])
        cnt = dominant[0]
        avg = QColor(dominant[1] // cnt, dominant[2] // cnt, dominant[3] // cnt)
        self._logo_color_cache[key] = avg.name()
        return avg

    # ── Team rendering ────────────────────────────────────────

    def _set_team(self, bar: QFrame, team, is_home: bool) -> None:
        self._cleanup_score_anim(bar)

        name_lbl: QLabel = bar._name_label  # type: ignore[attr-defined]
        score_lbl: QLabel = bar._score_label  # type: ignore[attr-defined]
        logo_lbl: QLabel = bar._logo_label  # type: ignore[attr-defined]

        if not team:
            name_lbl.setText("---")
            score_lbl.setText("-")
            bar.setStyleSheet("background:#333; border:none;")
            name_lbl.setStyleSheet(
                f"color:#666; font-family:{self._font}; font-weight:800; "
                "font-size:18px; background:transparent;"
            )
            score_lbl.setStyleSheet(
                f"color:#666; font-family:{self._font}; font-weight:900; "
                "font-size:34px; background:transparent;"
            )
            logo_lbl.setStyleSheet("background:transparent;")
            logo_lbl.clear()
            bar._team_tricode = ""  # type: ignore[attr-defined]
            return

        display = team_display_name(team.tricode, self._language)
        name_text = display or ("HOME" if is_home else "AWAY")
        if self._timeout_team_tricode and team.tricode.upper() == self._timeout_team_tricode:
            name_text = f"\u23f1 {name_text}"
        name_lbl.setTextFormat(Qt.PlainText)
        name_lbl.setText(name_text)
        bar._team_tricode = team.tricode.upper()  # type: ignore[attr-defined]
        score_lbl.setText(str(team.score))

        path = team_logo_path(team.tricode)
        if path:
            logo_lbl.setPixmap(QPixmap(str(path)))
            logo_lbl.show()
            self._apply_logo_mask(logo_lbl)
            bg = self._logo_bg_color(path, team.tricode)
        else:
            logo_lbl.clear()
            bg = team_color(team.tricode)

        txt = _contrast_text(bg)
        bar.setStyleSheet(f"background:{bg.name()}; border:none;")
        name_lbl.setStyleSheet(
            f"color:{txt}; font-family:{self._font}; font-weight:800; "
            "font-size:18px; background:transparent;"
        )
        score_lbl.setStyleSheet(
            f"color:{txt}; font-family:{self._font}; font-weight:900; "
            "font-size:34px; background:transparent;"
        )
        logo_lbl.setStyleSheet("background:transparent;")
        bar._timeout_widget.setStyleSheet("background:transparent;")  # type: ignore[attr-defined]

        if is_home:
            self._home_tricode = team.tricode.upper()
        else:
            self._away_tricode = team.tricode.upper()

    # ── Timeouts ──────────────────────────────────────────────

    def _set_timeouts(self, bar: QFrame, remaining: int) -> None:
        blocks: List[QFrame] = bar._timeout_blocks  # type: ignore[attr-defined]
        tricode: str = bar._team_tricode  # type: ignore[attr-defined]
        bg = team_color(tricode) if tricode else QColor("#333")

        if bg.lightness() > 160:
            active_clr = "rgba(0,0,0,220)"
            inactive_clr = "rgba(0,0,0,110)"
        else:
            active_clr = "rgba(255,255,255,245)"
            inactive_clr = "rgba(255,255,255,110)"

        remaining = max(0, min(self._MAX_TIMEOUTS, int(remaining)))
        for i, blk in enumerate(blocks):
            if i < remaining:
                blk.setStyleSheet(
                    f"background:{active_clr}; border:none; border-radius:3px;"
                )
            else:
                blk.setStyleSheet(
                    f"background:transparent; "
                    f"border:1px solid {inactive_clr}; border-radius:3px;"
                )

    # ── Expand / Collapse with height slide animation ─────────

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._stop_bubble_anims()

        if expanded:
            if self._current_game:
                self._update_period_scores(self._current_game)
            self._reset_stats_placeholder(self._bubble_away)
            self._reset_stats_placeholder(self._bubble_home)
            self._animate_bubbles_in()
            self.expand_toggled.emit(True)
        else:
            self._animate_bubbles_out()
            self.expand_toggled.emit(False)

    def toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    def _stop_bubble_anims(self) -> None:
        if self._bubble_expand_anim is not None:
            self._bubble_expand_anim.stop()
            self._bubble_expand_anim = None
        if self._bubble_collapse_anim is not None:
            self._bubble_collapse_anim.stop()
            self._bubble_collapse_anim = None

    def _animate_bubbles_in(self) -> None:
        targets: list[int] = []
        for b in self._bubbles:
            b.setMaximumHeight(16777215)
            b.setVisible(True)
        for b in self._bubbles:
            b.adjustSize()
            targets.append(max(b.sizeHint().height(), 40))
            b.setMaximumHeight(0)

        group = QParallelAnimationGroup(self)
        for i, (bubble, target_h) in enumerate(zip(self._bubbles, targets)):
            seq = QSequentialAnimationGroup(group)
            if i > 0:
                seq.addAnimation(QPauseAnimation(i * self._BUBBLE_IN_STAGGER, seq))
            anim = QPropertyAnimation(bubble, b"animHeight", seq)
            anim.setDuration(self._BUBBLE_IN_DURATION)
            anim.setStartValue(0)
            anim.setEndValue(target_h)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(self._on_bubble_resized)
            seq.addAnimation(anim)
            group.addAnimation(seq)

        def _unlock() -> None:
            for b in self._bubbles:
                b.setMaximumHeight(16777215)
            self.layout_changed.emit()

        group.finished.connect(_unlock)
        self._bubble_expand_anim = group
        group.start()

    def _animate_bubbles_out(self) -> None:
        reversed_bubbles = list(reversed(self._bubbles))
        group = QParallelAnimationGroup(self)
        for i, bubble in enumerate(reversed_bubbles):
            current_h = bubble.height()
            seq = QSequentialAnimationGroup(group)
            if i > 0:
                seq.addAnimation(QPauseAnimation(i * self._BUBBLE_OUT_STAGGER, seq))
            anim = QPropertyAnimation(bubble, b"animHeight", seq)
            anim.setDuration(self._BUBBLE_OUT_DURATION)
            anim.setStartValue(current_h)
            anim.setEndValue(0)
            anim.setEasingCurve(QEasingCurve.InQuad)
            anim.valueChanged.connect(self._on_bubble_resized)
            seq.addAnimation(anim)
            group.addAnimation(seq)

        def _on_collapse_done() -> None:
            for b in self._bubbles:
                b.setVisible(False)
                b.setMaximumHeight(16777215)
            self.collapse_done.emit()

        group.finished.connect(_on_collapse_done)
        self._bubble_collapse_anim = group
        group.start()

    def _on_bubble_resized(self) -> None:
        self.updateGeometry()
        self.layout_changed.emit()

    def _reset_stats_placeholder(self, bubble: _BubbleFrame) -> None:
        lay = bubble.layout()
        if lay is None:
            return
        self._clear_layout(lay)
        t = self._theme
        ph = QLabel("加载中..." if self._language == "zh" else "Loading...")
        ph.setStyleSheet(
            f"color:{t['text_secondary']}; font-size:10px; background:transparent; border:none;"
        )
        lay.addWidget(ph)

    # ── Period scores ─────────────────────────────────────────

    def _update_period_scores(self, game: GameState) -> None:
        self._clear_layout(self._period_grid)
        t = self._theme
        num_periods = max(
            len(game.away.periods), len(game.home.periods), game.regulation_periods or 4
        )
        headers: list[str] = []
        for i in range(1, num_periods + 1):
            if i <= 4:
                headers.append(f"Q{i}")
            else:
                ot = i - 4
                headers.append(f"OT{ot}" if ot > 1 else "OT")
        headers.append("T")

        name_w = 48
        content_w = self.WIDGET_WIDTH - 20 - name_w
        col_w = max(22, content_w // len(headers))

        hdr_style = (
            f"color:{t['expanded_header']}; font-family:{self._font}; "
            "font-size:9px; font-weight:700; "
            "background:transparent; padding:1px 0; border:none;"
        )
        blank = QLabel("")
        blank.setFixedWidth(name_w)
        blank.setStyleSheet(hdr_style)
        self._period_grid.addWidget(blank, 0, 0)
        for ci, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedWidth(col_w)
            lbl.setStyleSheet(hdr_style)
            self._period_grid.addWidget(lbl, 0, ci + 1)

        for ri, team_obj in enumerate([game.away, game.home], start=1):
            tc = team_color(team_obj.tricode)
            row_bg = t["expanded_row_alt"] if ri % 2 == 0 else "transparent"

            nm = QLabel(team_display_name(team_obj.tricode, self._language))
            nm.setFixedWidth(name_w)
            nm.setStyleSheet(
                f"color:{t['expanded_text']}; font-family:{self._font}; "
                f"font-size:11px; font-weight:800; "
                f"background:{row_bg}; padding:2px 0; "
                f"border-left:3px solid {tc.name()}; border-top:none; "
                "border-right:none; border-bottom:none;"
            )
            self._period_grid.addWidget(nm, ri, 0)

            periods = team_obj.periods or []
            for ci in range(num_periods):
                val = str(periods[ci].get("score", "-")) if ci < len(periods) else "-"
                lbl = QLabel(val)
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setFixedWidth(col_w)
                lbl.setStyleSheet(
                    f"color:{t['expanded_text']}; font-family:{self._font}; "
                    f"font-size:11px; "
                    f"background:{row_bg}; padding:2px 0; border:none;"
                )
                self._period_grid.addWidget(lbl, ri, ci + 1)

            total = QLabel(str(team_obj.score))
            total.setAlignment(Qt.AlignCenter)
            total.setFixedWidth(col_w)
            total.setStyleSheet(
                f"color:{t['expanded_stat_accent']}; font-family:{self._font}; "
                f"font-size:11px; font-weight:900; "
                f"background:{row_bg}; padding:2px 0; border:none;"
            )
            self._period_grid.addWidget(total, ri, num_periods + 1)

    # ── Player stats (team-colored bubbles) ───────────────────

    def set_player_stats(self, stats: list[dict]) -> None:
        if not self._expanded:
            return

        self._player_label_map.clear()
        away_stats = [s for s in stats if s.get("team", "").upper() == self._away_tricode]
        home_stats = [s for s in stats if s.get("team", "").upper() == self._home_tricode]

        self._fill_stats_bubble(self._bubble_away, self._away_tricode, away_stats)
        self._fill_stats_bubble(self._bubble_home, self._home_tricode, home_stats)
        self.layout_changed.emit()

    def _fill_stats_bubble(
        self, bubble: _BubbleFrame, tricode: str, players: list[dict]
    ) -> None:
        lay = bubble.layout()
        if lay is None:
            return
        self._clear_layout(lay)

        tc = team_color(tricode)
        pal = _team_palette(tc)
        display = team_full_display_name(tricode, self._language)

        bubble.setStyleSheet(
            f"#{bubble.objectName()} {{ background: {tc.name()}; "
            f"border: none; border-radius: 8px; }}"
        )

        is_zh = self._language == "zh"
        loading_text = "加载中..." if is_zh else "Loading..."

        if not players:
            header = QLabel(display)
            header.setStyleSheet(
                f"color:{pal['txt']}; font-family:{self._font}; font-weight:900; "
                "font-size:13px; background:transparent; border:none;"
            )
            lay.addWidget(header)
            ph = QLabel(loading_text)
            ph.setStyleSheet(
                f"color:{pal['txt_sub']}; font-size:10px; "
                "background:transparent; border:none;"
            )
            lay.addWidget(ph)
            return

        header = QLabel(display)
        header.setStyleSheet(
            f"color:{pal['txt']}; font-family:{self._font}; font-weight:900; "
            "font-size:13px; background:transparent; border:none;"
        )
        lay.addWidget(header)

        col_headers = ["球员", "得分", "助攻", "篮板"] if is_zh else ["PLAYER", "PTS", "AST", "REB"]
        col_hdr = QWidget()
        col_hdr.setStyleSheet("background:transparent; border:none;")
        ch_lay = QGridLayout(col_hdr)
        ch_lay.setContentsMargins(0, 0, 0, 0)
        ch_lay.setHorizontalSpacing(4)
        ch_lay.setVerticalSpacing(0)
        for ci, h in enumerate(col_headers):
            lbl = QLabel(h)
            lbl.setStyleSheet(
                f"color:{pal['txt_sub']}; font-size:8px; font-weight:700; "
                "background:transparent; border:none;"
            )
            if ci == 0:
                lbl.setMinimumWidth(90)
            else:
                lbl.setFixedWidth(28)
                lbl.setAlignment(Qt.AlignCenter)
            ch_lay.addWidget(lbl, 0, ci)
        lay.addWidget(col_hdr)

        for pi, player in enumerate(players):
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent; border:none;")
            r_lay = QGridLayout(row_w)
            r_lay.setContentsMargins(0, 0, 0, 0)
            r_lay.setHorizontalSpacing(4)
            r_lay.setVerticalSpacing(0)
            row_bg = pal["alt_row"] if pi % 2 == 1 else "transparent"

            nm = QLabel(player.get("name", ""))
            nm.setMinimumWidth(90)
            nm.setCursor(Qt.PointingHandCursor)
            nm.setStyleSheet(
                f"color:{pal['txt_dim']}; font-size:10px; "
                f"background:{row_bg}; border:none; padding:1px 0;"
                " text-decoration:underline;"
            )
            nm.installEventFilter(self)
            player_info = dict(player)
            player_info["teamTricode"] = tricode
            self._player_label_map[id(nm)] = player_info
            r_lay.addWidget(nm, 0, 0)

            pts_lbl = QLabel(str(player.get("points", 0)))
            pts_lbl.setFixedWidth(28)
            pts_lbl.setAlignment(Qt.AlignCenter)
            pts_lbl.setStyleSheet(
                f"color:{pal['txt']}; font-family:{self._font}; "
                "font-size:12px; font-weight:700; "
                f"background:{row_bg}; border:none; padding:1px 0;"
            )
            r_lay.addWidget(pts_lbl, 0, 1)

            for ci, key in enumerate(["assists", "rebounds"], start=2):
                val = QLabel(str(player.get(key, 0)))
                val.setFixedWidth(28)
                val.setAlignment(Qt.AlignCenter)
                val.setStyleSheet(
                    f"color:{pal['txt_dim']}; font-family:{self._font}; "
                    f"font-size:10px; "
                    f"background:{row_bg}; border:none; padding:1px 0;"
                )
                r_lay.addWidget(val, 0, ci)

            lay.addWidget(row_w)

    # ── Score roll animation ──────────────────────────────────

    @staticmethod
    def _cleanup_score_anim(bar: QFrame) -> None:
        cycle_timer = getattr(bar, "_cycle_timer", None)
        if cycle_timer is not None:
            cycle_timer.stop()
            bar._cycle_timer = None  # type: ignore[attr-defined]
        anim = getattr(bar, "_score_anim", None)
        if anim is not None:
            anim.stop()
            bar._score_anim = None  # type: ignore[attr-defined]
        for lbl in getattr(bar, "_anim_labels", []):
            lbl.setParent(None)
            lbl.deleteLater()
        bar._anim_labels = []  # type: ignore[attr-defined]
        score_lbl: QLabel = bar._score_label  # type: ignore[attr-defined]
        if not score_lbl.isVisible():
            score_lbl.show()

    def _animate_score_initial(
        self, bar: QFrame, final_score: int, delay_ms: int = 0
    ) -> None:
        """Slot-machine roll-in animation for the first score load."""
        self._cleanup_score_anim(bar)

        score_label: QLabel = bar._score_label  # type: ignore[attr-defined]
        lay = bar.layout()
        if lay:
            lay.activate()
        bar.updateGeometry()

        rect = score_label.geometry()
        if rect.height() <= 0 or rect.width() <= 0:
            sz = score_label.sizeHint()
            rect = QRect(
                score_label.pos(),
                QSize(max(1, sz.width()), max(1, sz.height())),
            )

        style = score_label.styleSheet()
        align = score_label.alignment()

        roll_lbl = QLabel("-", bar)
        roll_lbl.setStyleSheet(style)
        roll_lbl.setAlignment(align)
        roll_lbl.setFixedSize(rect.size())
        roll_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        roll_lbl.move(rect.topLeft())
        roll_lbl.show()
        roll_lbl.raise_()

        bar._anim_labels = [roll_lbl]  # type: ignore[attr-defined]
        score_label.hide()

        spread = max(10, final_score // 3)
        cycle_vals = [
            str(random.randint(max(0, final_score - spread), final_score + spread))
            for _ in range(7)
        ]
        step_idx = [0]

        def _tick() -> None:
            i = step_idx[0]
            if i < len(cycle_vals):
                roll_lbl.setText(cycle_vals[i])
                step_idx[0] += 1
            else:
                timer.stop()
                bar._cycle_timer = None  # type: ignore[attr-defined]
                _slide_final()

        def _slide_final() -> None:
            start_pos = rect.topLeft()
            above = start_pos - QPoint(0, int(rect.height() * 0.5))

            roll_lbl.setText(str(final_score))
            roll_lbl.move(above)

            slide = QPropertyAnimation(roll_lbl, b"pos", self)
            slide.setDuration(300)
            slide.setStartValue(above)
            slide.setEndValue(start_pos)
            slide.setEasingCurve(QEasingCurve.OutCubic)

            def _done() -> None:
                roll_lbl.setParent(None)
                roll_lbl.deleteLater()
                bar._anim_labels = []  # type: ignore[attr-defined]
                score_label.setText(str(final_score))
                score_label.show()

            slide.finished.connect(_done)
            bar._score_anim = slide  # type: ignore[attr-defined]
            slide.start()

        timer = QTimer(self)
        timer.setInterval(45)
        timer.timeout.connect(_tick)
        bar._cycle_timer = timer  # type: ignore[attr-defined]

        if delay_ms > 0:
            QTimer.singleShot(delay_ms, timer.start)
        else:
            timer.start()

    def _animate_score_roll(
        self, bar: QFrame, old_score: int, delta: int, new_score: int
    ) -> None:
        if delta <= 0 or old_score == new_score:
            return

        self._cleanup_score_anim(bar)

        score_label: QLabel = bar._score_label  # type: ignore[attr-defined]
        layout = bar.layout()
        if layout:
            layout.activate()
        bar.updateGeometry()

        rect = score_label.geometry()
        if rect.height() <= 0 or rect.width() <= 0:
            sz = score_label.sizeHint()
            rect = QRect(score_label.pos(), QSize(max(1, sz.width()), max(1, sz.height())))

        style = score_label.styleSheet()
        align = score_label.alignment()

        def _mk(text: str) -> QLabel:
            lbl = QLabel(text, bar)
            lbl.setStyleSheet(style)
            lbl.setAlignment(align)
            lbl.setFixedSize(rect.size())
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lbl.show()
            lbl.raise_()
            return lbl

        old_lbl = _mk(str(old_score))
        delta_lbl = _mk(f"+{delta}")
        delta_lbl.setStyleSheet(
            f"color:{self._theme['delta_color']}; font-family:{self._font}; "
            "font-weight:900; font-size:24px; background:transparent;"
        )
        new_lbl = _mk(str(new_score))
        bar._anim_labels = [old_lbl, delta_lbl, new_lbl]  # type: ignore[attr-defined]

        start = rect.topLeft()
        up = start - QPoint(0, rect.height())
        down = start + QPoint(0, rect.height())

        old_lbl.move(start)
        delta_lbl.move(up)
        new_lbl.move(up)
        score_label.hide()

        a_old = QPropertyAnimation(old_lbl, b"pos", self)
        a_old.setDuration(280)
        a_old.setStartValue(start)
        a_old.setEndValue(down)
        a_old.setEasingCurve(QEasingCurve.InQuad)

        a_din = QPropertyAnimation(delta_lbl, b"pos", self)
        a_din.setDuration(280)
        a_din.setStartValue(up)
        a_din.setEndValue(start)
        a_din.setEasingCurve(QEasingCurve.OutCubic)

        hold = QPauseAnimation(900, self)

        a_dout = QPropertyAnimation(delta_lbl, b"pos", self)
        a_dout.setDuration(280)
        a_dout.setStartValue(start)
        a_dout.setEndValue(down)
        a_dout.setEasingCurve(QEasingCurve.InQuad)

        a_new = QPropertyAnimation(new_lbl, b"pos", self)
        a_new.setDuration(280)
        a_new.setStartValue(up)
        a_new.setEndValue(start)
        a_new.setEasingCurve(QEasingCurve.OutCubic)

        phase_in = QParallelAnimationGroup(self)
        phase_in.addAnimation(a_old)
        phase_in.addAnimation(a_din)

        phase_out = QParallelAnimationGroup(self)
        phase_out.addAnimation(a_dout)
        phase_out.addAnimation(a_new)

        seq = QSequentialAnimationGroup(self)
        seq.addAnimation(phase_in)
        seq.addAnimation(hold)
        seq.addAnimation(phase_out)

        def _cleanup() -> None:
            for lbl in [old_lbl, delta_lbl, new_lbl]:
                lbl.setParent(None)
                lbl.deleteLater()
            bar._anim_labels = []  # type: ignore[attr-defined]
            score_label.setText(str(new_score))
            score_label.show()

        seq.finished.connect(_cleanup)
        bar._score_anim = seq  # type: ignore[attr-defined]
        seq.start()

    # ── Public helpers ────────────────────────────────────────

    def set_language(self, language: str) -> None:
        self._language = language or "en"
        self._apply_theme_styles()

    def set_opacity(self, opacity: float) -> None:
        self.setWindowOpacity(opacity)

    def set_shot_clock_display(self, value: str) -> None:
        pass

    def set_game_clock_display(self, value: str) -> None:
        self.clock_label.setText(value or "--:--")

    def set_timeout_team(self, tricode: str) -> None:
        self._timeout_team_tricode = (tricode or "").upper()

    def set_layout_mode(self, mode: str) -> None:
        pass

    def get_broadcast_bar_width(self) -> int:
        return self.WIDGET_WIDTH

    # ── Static helpers ────────────────────────────────────────

    @staticmethod
    def _apply_logo_mask(label: QLabel) -> None:
        sz = label.size()
        if sz.width() <= 0 or sz.height() <= 0:
            return
        label.setMask(QRegion(QRect(0, 0, sz.width(), sz.height()), QRegion.Ellipse))

    @staticmethod
    def _safe_int(value: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

    @staticmethod
    def _format_ordinal_period(period: int) -> str:
        return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(period, f"{period}th")

    @staticmethod
    def _format_period(game: GameState) -> str:
        p = game.period
        if p <= 0:
            return game.status_text or ""
        return {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}.get(p, f"Q{p}")

    @staticmethod
    def _format_overtime_period(period: int) -> str:
        if period <= 4:
            return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(period, f"{period}th")
        ot = period - 4
        return f"OT{ot}" if ot > 1 else "OT"

    @staticmethod
    def _format_game_clock(game: GameState) -> str:
        clock = game.game_clock or ""
        if not clock:
            return "00:00" if game.is_final else "--:--"
        if clock.startswith("PT") and clock.endswith("S"):
            clock = clock[2:-1]
            if "M" in clock:
                minutes, seconds = clock.split("M", 1)
                seconds = seconds.split(".", 1)[0]
                return f"{int(minutes):02d}:{int(seconds):02d}"
        return clock

    @staticmethod
    def _is_period_break(game: GameState) -> bool:
        clock = (game.game_clock or "").strip().upper()
        status = (game.status_text or "").strip().upper()
        if clock in {"00:00", "0:00", "0.0", "0", ""} and status:
            if any(tok in status for tok in ("HALF", "HALFTIME", "END", "BREAK")):
                return True
        return False
