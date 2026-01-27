from __future__ import annotations

from typing import List, Optional

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

from app.models import GameDiff, GameState
from app.resources import team_color, team_logo_path, team_display_name


class FadableLabel(QLabel):
    """支持透明度动画的标签，用于 +X 动画。"""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity = 1.0

    def getOpacity(self) -> float:  # noqa: N802 (Qt property signature)
        return self._opacity

    def setOpacity(self, value: float) -> None:  # noqa: N802
        self._opacity = value
        self._opacity_effect.setOpacity(value)

    opacity = Property(float, getOpacity, setOpacity)  # type: ignore


class ScoreboardWidget(QWidget):
    """主比分控件，显示单场比赛信息并支持得分增量动画。"""

    period_clicked = Signal()
    team_bar_right_clicked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._timeouts_active_color = "#ffffff"
        self._timeouts_inactive_color = "#333333"
        self._away_timeouts_remaining = 0
        self._home_timeouts_remaining = 0
        self._language = "en"
        self._layout_mode = "side_by_side"
        self._broadcast_width_scale = 0.375
        self._broadcast_fixed_width = 200
        self._logo_color_cache: dict[str, str] = {}
        self._timeout_team_tricode = ""
        self._player_panel_team = ""
        self._build_ui()
        self.apply_theme()
        self.set_opacity(0.9)

    def _build_ui(self) -> None:
        self.setAutoFillBackground(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.container = QFrame()
        self.container.setStyleSheet("QFrame { background: #0b0b0b; border: 1px solid #ffffff; border-radius: 0px; }")
        self._cont_layout = QVBoxLayout(self.container)
        self._cont_layout.setContentsMargins(4, 4, 4, 4)
        self._cont_layout.setSpacing(4)

        # Top row: two team bars
        self._grid_widget = QWidget()
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(2)
        self.away_bar = self._make_team_bar()
        self.home_bar = self._make_team_bar()
        self.away_bar.installEventFilter(self)
        self.home_bar.installEventFilter(self)

        # Middle row: timeouts (7 blocks per team)
        self.away_timeouts = self._make_timeouts_row()
        self.home_timeouts = self._make_timeouts_row()
        self._timeouts_row = QWidget()
        self._timeouts_layout = QGridLayout(self._timeouts_row)
        self._timeouts_layout.setContentsMargins(0, 0, 0, 0)
        self._timeouts_layout.setHorizontalSpacing(2)

        # Broadcast sections: bar + timeouts stacked
        self._home_section = QWidget()
        self._home_section_layout = QVBoxLayout(self._home_section)
        self._home_section_layout.setContentsMargins(0, 0, 0, 0)
        self._home_section_layout.setSpacing(2)
        self._home_section_layout.addWidget(self.home_bar)

        self._away_section = QWidget()
        self._away_section_layout = QVBoxLayout(self._away_section)
        self._away_section_layout.setContentsMargins(0, 0, 0, 0)
        self._away_section_layout.setSpacing(2)
        self._away_section_layout.addWidget(self.away_bar)

        # Bottom row: three boxed labels (left/center/right)
        self._footer = QFrame()
        self._footer_layout = QGridLayout(self._footer)
        self._footer_layout.setContentsMargins(0, 0, 0, 0)
        self._footer_layout.setHorizontalSpacing(2)

        self.period_label = QLabel("—")
        self.period_label.setAlignment(Qt.AlignCenter)
        self.period_label.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 700;")

        self.clock_label = QLabel("--:--")
        self.clock_label.setAlignment(Qt.AlignCenter)
        self.clock_label.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 700;")

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 700;")

        period_box = self._wrap_footer_box(self.period_label)
        clock_box = self._wrap_footer_box(self.clock_label)
        status_box = self._wrap_footer_box(self.status_label)

        self._footer_boxes = [period_box, clock_box, status_box]
        self._footer_layout.addWidget(period_box, 0, 0)
        self._footer_layout.addWidget(clock_box, 0, 1)
        self._footer_layout.addWidget(status_box, 0, 2)
        self._footer_layout.setColumnStretch(0, 1)
        self._footer_layout.setColumnStretch(1, 1)
        self._footer_layout.setColumnStretch(2, 1)

        # Broadcast bottom row: period / clock / shot clock
        self._broadcast_footer = QFrame()
        self._broadcast_footer.setVisible(False)
        self._broadcast_footer_layout = QHBoxLayout(self._broadcast_footer)
        self._broadcast_footer_layout.setContentsMargins(0, 0, 0, 0)
        self._broadcast_footer_layout.setSpacing(4)
        self._broadcast_footer_layout.setAlignment(Qt.AlignLeft)

        self._broadcast_period_label = QLabel("—")
        self._broadcast_clock_label = QLabel("--:--")
        self._broadcast_shot_label = QLabel("--")
        self._broadcast_period_label.installEventFilter(self)

        self._broadcast_period_box = self._wrap_broadcast_box(self._broadcast_period_label, 50, 30)
        self._broadcast_clock_box = self._wrap_broadcast_box(self._broadcast_clock_label, 90, 30)
        self._broadcast_shot_box = self._wrap_broadcast_box(self._broadcast_shot_label, 50, 30)

        self._broadcast_footer_layout.addWidget(self._broadcast_period_box)
        self._broadcast_footer_layout.addWidget(self._broadcast_clock_box)
        self._broadcast_footer_layout.addWidget(self._broadcast_shot_box)

        self._player_panel = QFrame()
        self._player_panel.setVisible(False)
        self._player_panel.setStyleSheet("QFrame { background: #000000; border-radius: 8px; }")
        self._player_panel_layout = QVBoxLayout(self._player_panel)
        self._player_panel_layout.setContentsMargins(8, 6, 8, 6)
        self._player_panel_layout.setSpacing(4)
        self._player_header = QLabel("")
        self._player_header.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 12px;")
        self._player_panel_layout.addWidget(self._player_header)
        self._player_table = QWidget()
        self._player_table_layout = QGridLayout(self._player_table)
        self._player_table_layout.setContentsMargins(0, 0, 0, 0)
        self._player_table_layout.setHorizontalSpacing(6)
        self._player_table_layout.setVerticalSpacing(2)
        self._player_panel_layout.addWidget(self._player_table)

        self._player_panel_container = QWidget()
        self._player_panel_container_layout = QHBoxLayout(self._player_panel_container)
        self._player_panel_container_layout.setContentsMargins(0, 0, 0, 0)
        self._player_panel_container_layout.setSpacing(8)
        self._player_panel_container_layout.addStretch()
        self._player_panel_container_layout.addWidget(self._player_panel)
        self._player_panel_container.setVisible(False)

        self._grid_row = QWidget()
        self._grid_row_layout = QHBoxLayout(self._grid_row)
        self._grid_row_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_row_layout.setSpacing(8)
        self._grid_row_layout.addWidget(self._grid_widget)
        self._grid_row_layout.setAlignment(Qt.AlignLeft)

        self._cont_layout.addWidget(self._grid_row)
        self._cont_layout.addWidget(self._timeouts_row)
        self._cont_layout.addWidget(self._footer)

        layout.addWidget(self.container)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Delta labels for animations
        self.away_delta = self._make_delta_label()
        self.home_delta = self._make_delta_label()
        self._apply_layout_mode()

        self._reset_display()

    def _make_team_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(28)
        bar.setFrameShape(QFrame.NoFrame)
        bar.setStyleSheet("background: #444; border-radius: 0px; border: none;")
        layout = QGridLayout(bar)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setHorizontalSpacing(6)

        logo = QLabel()
        logo.setFixedSize(0, 0)
        logo.setScaledContents(True)
        logo.hide()

        name = QLabel("N/A")
        name.setStyleSheet("color: white; font-weight: 900; font-size: 13px;")
        score = QLabel("--")
        score.setStyleSheet("color: white; font-weight: 900; font-size: 16px;")
        score.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(logo, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(name, 0, 1, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(score, 0, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)

        bar._layout = layout  # type: ignore[attr-defined]
        bar._logo_label = logo  # type: ignore[attr-defined]
        bar._name_label = name  # type: ignore[attr-defined]
        bar._score_label = score  # type: ignore[attr-defined]
        return bar

    def _make_timeouts_row(self, max_timeouts: int = 7) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)
        row._timeout_blocks = []  # type: ignore[attr-defined]
        for _ in range(max_timeouts):
            block = QFrame()
            block.setFixedSize(12, 6)
            block.setStyleSheet("background: #333;")
            layout.addWidget(block)
            row._timeout_blocks.append(block)  # type: ignore[attr-defined]
        layout.addStretch()
        return row

    def _make_delta_label(self) -> FadableLabel:
        lbl = FadableLabel("")
        lbl.setStyleSheet("color: #ffd166; font-weight: 700; font-size: 12px;")
        lbl.hide()
        return lbl

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        if (
            hasattr(self, "_broadcast_period_label")
            and obj == self._broadcast_period_label
            and event.type() == QEvent.MouseButtonPress
        ):
            self.period_clicked.emit()
            return True
        if event.type() == QEvent.MouseButtonPress and self._layout_mode == "broadcast":
            if obj in (self.home_bar, self.away_bar) and event.button() == Qt.RightButton:
                tricode = getattr(obj, "_team_tricode", "")
                self.team_bar_right_clicked.emit(tricode)
                return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _apply_team_bar_mode(self) -> None:
        if self._layout_mode == "broadcast":
            self._configure_broadcast_team_bar(self.away_bar)
            self._configure_broadcast_team_bar(self.home_bar)
        else:
            self._configure_standard_team_bar(self.away_bar)
            self._configure_standard_team_bar(self.home_bar)

    @staticmethod
    def _configure_standard_team_bar(bar: QFrame) -> None:
        layout: QGridLayout = bar._layout  # type: ignore[attr-defined]
        logo: QLabel = bar._logo_label  # type: ignore[attr-defined]
        name: QLabel = bar._name_label  # type: ignore[attr-defined]
        score: QLabel = bar._score_label  # type: ignore[attr-defined]

        layout.removeWidget(logo)
        layout.removeWidget(name)
        layout.removeWidget(score)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setHorizontalSpacing(6)
        layout.addWidget(logo, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(name, 0, 1, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(score, 0, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 0)

        bar.setFixedHeight(28)
        logo.setFixedSize(0, 0)
        logo.setStyleSheet("")
        name.setStyleSheet("color: white; font-weight: 900; font-size: 13px;")
        score.setStyleSheet("color: white; font-weight: 900; font-size: 16px;")

    @staticmethod
    def _configure_broadcast_team_bar(bar: QFrame) -> None:
        layout: QGridLayout = bar._layout  # type: ignore[attr-defined]
        logo: QLabel = bar._logo_label  # type: ignore[attr-defined]
        name: QLabel = bar._name_label  # type: ignore[attr-defined]
        score: QLabel = bar._score_label  # type: ignore[attr-defined]

        layout.removeWidget(logo)
        layout.removeWidget(name)
        layout.removeWidget(score)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setHorizontalSpacing(6)
        layout.addWidget(name, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(score, 0, 1, alignment=Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(logo, 0, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 0)

        bar.setFixedHeight(50)
        logo.setFixedSize(50, 50)
        radius = logo.width() // 2
        logo.setStyleSheet(f"background: #ffffff; border-radius: {radius}px;")
        name.setStyleSheet("color: #ffffff; font-weight: 900; font-size: 22px;")
        score.setStyleSheet("color: #ffffff; font-weight: 900; font-size: 30px;")

    def _reset_display(self) -> None:
        self._set_team(self.away_bar, None, is_home=False)
        self._set_team(self.home_bar, None, is_home=True)
        self.clock_label.setText("--:--")
        self.period_label.setText("")
        self.status_label.setText("--")
        self._away_timeouts_remaining = 0
        self._home_timeouts_remaining = 0
        self._set_timeouts(self.away_timeouts, self._away_timeouts_remaining)
        self._set_timeouts(self.home_timeouts, self._home_timeouts_remaining)

    def render_game(self, game: Optional[GameState]) -> None:
        """
        渲染比赛的基础信息（不含动画）。
        """
        if not game:
            self._reset_display()
            return

        self._set_team(self.away_bar, game.away, is_home=False)
        self._set_team(self.home_bar, game.home, is_home=True)
        self._away_timeouts_remaining = game.away.timeouts_remaining
        self._home_timeouts_remaining = game.home.timeouts_remaining
        self._set_timeouts(self.away_timeouts, self._away_timeouts_remaining)
        self._set_timeouts(self.home_timeouts, self._home_timeouts_remaining)

        if game.is_final:
            period_text = "Timeout"
        elif game.period > 4:
            period_text = self._format_overtime_period(game.period)
        else:
            period_text = self._format_period(game)
        if period_text == "Timeout":
            self.period_label.setStyleSheet("color: #ffffff; font-size: 10px; font-weight: 700;")
            self._broadcast_period_label.setStyleSheet("color: #ffffff; font-size: 11px; font-weight: 700;")
        else:
            self.period_label.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 700;")
            self._broadcast_period_label.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700;")
        if self._is_period_break(game):
            clock_text = "Timeout"
        else:
            clock_text = self._format_game_clock(game)
        self.clock_label.setText(clock_text)
        self.period_label.setText(period_text or "—")
        self._broadcast_period_label.setText(period_text or "—")
        self._broadcast_clock_label.setText(clock_text)
        self._apply_clock_font_size(clock_text == "Timeout")

    def render_diff(self, diff: GameDiff) -> None:
        """
        渲染比分并根据增量触发动画。
        """
        old_away = self._safe_int(self.away_bar._score_label.text())  # type: ignore[attr-defined]
        old_home = self._safe_int(self.home_bar._score_label.text())  # type: ignore[attr-defined]
        self.render_game(diff.game)

        home_delta = diff.delta.home_delta
        away_delta = diff.delta.away_delta
        if home_delta <= 0 and diff.game.home.score > old_home:
            home_delta = diff.game.home.score - old_home
        if away_delta <= 0 and diff.game.away.score > old_away:
            away_delta = diff.game.away.score - old_away

        if home_delta > 0:
            self._animate_score_roll(self.home_bar, old_home, home_delta, diff.game.home.score)
        if away_delta > 0:
            self._animate_score_roll(self.away_bar, old_away, away_delta, diff.game.away.score)

    def _set_team(self, bar: QFrame, team, is_home: bool) -> None:
        name_label: QLabel = bar._name_label  # type: ignore[attr-defined]
        score_label: QLabel = bar._score_label  # type: ignore[attr-defined]
        if not team:
            name_label.setText("N/A")
            score_label.setText("--")
            border_radius = 8 if self._layout_mode == "broadcast" else 0
            bar.setStyleSheet(f"background: #444; border-radius: {border_radius}px;")
            bar._logo_label.clear()  # type: ignore[attr-defined]
            bar._logo_label.hide()  # type: ignore[attr-defined]
            return

        display_name = team_display_name(team.tricode, self._language)
        name_text = display_name or ("HOME" if is_home else "AWAY")
        if self._timeout_team_tricode and team.tricode.upper() == self._timeout_team_tricode:
            dot_color = self._timeout_dot_color(team.tricode)
            name_text = f"{name_text} <span style='color:{dot_color};'>●</span>"
            name_label.setTextFormat(Qt.RichText)
        else:
            name_label.setTextFormat(Qt.PlainText)
        name_label.setText(name_text)
        bar._team_tricode = team.tricode.upper()  # type: ignore[attr-defined]
        score_label.setText(str(team.score))

        logo_label: QLabel = bar._logo_label  # type: ignore[attr-defined]
        path = team_logo_path(team.tricode)
        if path:
            logo_label.setPixmap(QPixmap(str(path)))
            logo_label.show()
            self._apply_logo_mask(logo_label)
        else:
            logo_label.clear()
            logo_label.hide()

        if self._layout_mode == "broadcast" and path:
            color = self._logo_bg_color(path, team.tricode)
        else:
            color = team_color(team.tricode)
        if self._layout_mode == "broadcast":
            text_color = "#000000" if color.lightness() > 220 else "#ffffff"
            name_label.setStyleSheet(f"color: {text_color}; font-weight: 900; font-size: 22px;")
            score_label.setStyleSheet(f"color: {text_color}; font-weight: 900; font-size: 30px;")
            bar.setStyleSheet(
                f"background: {color.name()};"
                "border-radius: 8px; border: none;"
            )
        else:
            name_label.setStyleSheet("color: white; font-weight: 900; font-size: 13px;")
            score_label.setStyleSheet("color: white; font-weight: 900; font-size: 16px;")
            bar.setStyleSheet(
                f"background: {color.name()};"
                "border-radius: 0px; border: none;"
            )

    def _show_delta(self, label: FadableLabel, text: str, to_right: bool) -> None:
        label.setText(text)
        label.show()
        label.move(label.pos() + QPoint(0, 0))
        label.setOpacity(1.0)

        # 位置轻微偏移动画
        start_pos = label.pos()
        end_pos = start_pos + QPoint(12 if to_right else -12, -6)

        pos_anim = QPropertyAnimation(label, b"pos", self)
        pos_anim.setDuration(600)
        pos_anim.setStartValue(start_pos)
        pos_anim.setEndValue(end_pos)
        pos_anim.setEasingCurve(QEasingCurve.OutQuad)

        opacity_anim = QPropertyAnimation(label, b"opacity", self)
        opacity_anim.setDuration(600)
        opacity_anim.setStartValue(1.0)
        opacity_anim.setEndValue(0.0)
        opacity_anim.setEasingCurve(QEasingCurve.InQuad)

        def on_finished() -> None:
            label.hide()
            label.move(start_pos)
            label.setOpacity(1.0)

        opacity_anim.finished.connect(on_finished)
        pos_anim.start()
        opacity_anim.start()

    @staticmethod
    def _safe_int(value: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _animate_score_roll(self, bar: QFrame, old_score: int, delta: int, new_score: int) -> None:
        if delta <= 0 or old_score == new_score:
            return

        score_label: QLabel = bar._score_label  # type: ignore[attr-defined]
        if hasattr(bar, "_score_anim") and bar._score_anim is not None:  # type: ignore[attr-defined]
            bar._score_anim.stop()  # type: ignore[attr-defined]

        layout = bar.layout()
        if layout is not None:
            layout.activate()
        bar.updateGeometry()

        rect = score_label.geometry()
        if rect.height() <= 0 or rect.width() <= 0:
            size = score_label.sizeHint()
            rect = QRect(score_label.pos(), QSize(max(1, size.width()), max(1, size.height())))

        style = score_label.styleSheet()
        align = score_label.alignment()

        def make_label(text: str) -> QLabel:
            lbl = QLabel(text, bar)
            lbl.setStyleSheet(style)
            lbl.setAlignment(align)
            lbl.setFixedSize(rect.size())
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lbl.show()
            lbl.raise_()
            return lbl

        old_lbl = make_label(str(old_score))
        delta_lbl = make_label(f"+{delta}")
        new_lbl = make_label(str(new_score))

        start_pos = rect.topLeft()
        up_pos = start_pos - QPoint(0, rect.height())
        down_pos = start_pos + QPoint(0, rect.height())

        old_lbl.move(start_pos)
        delta_lbl.move(up_pos)
        new_lbl.move(up_pos)

        score_label.hide()

        old_anim = QPropertyAnimation(old_lbl, b"pos", self)
        old_anim.setDuration(300)
        old_anim.setStartValue(start_pos)
        old_anim.setEndValue(down_pos)
        old_anim.setEasingCurve(QEasingCurve.InQuad)

        delta_in = QPropertyAnimation(delta_lbl, b"pos", self)
        delta_in.setDuration(300)
        delta_in.setStartValue(up_pos)
        delta_in.setEndValue(start_pos)
        delta_in.setEasingCurve(QEasingCurve.OutBack)

        hold = QPauseAnimation(1000, self)

        delta_out = QPropertyAnimation(delta_lbl, b"pos", self)
        delta_out.setDuration(300)
        delta_out.setStartValue(start_pos)
        delta_out.setEndValue(down_pos)
        delta_out.setEasingCurve(QEasingCurve.InQuad)

        new_in = QPropertyAnimation(new_lbl, b"pos", self)
        new_in.setDuration(300)
        new_in.setStartValue(up_pos)
        new_in.setEndValue(start_pos)
        new_in.setEasingCurve(QEasingCurve.OutBack)

        phase_in = QParallelAnimationGroup(self)
        phase_in.addAnimation(old_anim)
        phase_in.addAnimation(delta_in)

        phase_out = QParallelAnimationGroup(self)
        phase_out.addAnimation(delta_out)
        phase_out.addAnimation(new_in)

        group = QSequentialAnimationGroup(self)
        group.addAnimation(phase_in)
        group.addAnimation(hold)
        group.addAnimation(phase_out)

        def cleanup() -> None:
            old_lbl.deleteLater()
            delta_lbl.deleteLater()
            new_lbl.deleteLater()
            score_label.setText(str(new_score))
            score_label.show()

        group.finished.connect(cleanup)
        bar._score_anim = group  # type: ignore[attr-defined]
        group.start()

    # 主题与透明度
    def apply_theme(
        self,
        text_color: str = "#ffffff",
        sub_text: str = "#dddddd",
        delta_color: str = "#ffd166",
        container_bg: str = "#111111",
        border_color: str = "#444444",
        timeouts_active_color: str = "#ffffff",
        timeouts_inactive_color: str = "#333333",
        footer_bg: str = "#111111",
        footer_border: str = "#000000",
    ) -> None:
        self.container.setStyleSheet(
            f"QFrame {{ background: {container_bg}; border: 1px solid {border_color}; border-radius: 0px; }}"
        )
        self.clock_label.setStyleSheet(f"color: {text_color}; font-size: 12px; font-weight: 700;")
        self.period_label.setStyleSheet(f"color: {text_color}; font-size: 12px; font-weight: 700;")
        self.status_label.setStyleSheet(f"color: {text_color}; font-size: 12px; font-weight: 700;")
        self.away_delta.setStyleSheet(f"color: {delta_color}; font-weight: 700; font-size: 12px;")
        self.home_delta.setStyleSheet(f"color: {delta_color}; font-weight: 700; font-size: 12px;")
        for box in self._footer_boxes:
            box.setStyleSheet(f"background: {footer_bg}; border: 1px solid {footer_border};")
        self._timeouts_active_color = timeouts_active_color
        self._timeouts_inactive_color = timeouts_inactive_color
        self._set_timeouts(self.away_timeouts, self._away_timeouts_remaining)
        self._set_timeouts(self.home_timeouts, self._home_timeouts_remaining)

    @staticmethod
    def _wrap_footer_box(label: QLabel) -> QFrame:
        box = QFrame()
        box.setStyleSheet("background: #111111; border: 0px;")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)
        layout.addWidget(label, alignment=Qt.AlignCenter)
        return box

    @staticmethod
    def _wrap_broadcast_box(label: QLabel, width: int, height: int) -> QFrame:
        box = QFrame()
        box.setFixedSize(width, height)
        box.setStyleSheet("background: #000000; border-radius: 4px;")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700;")
        layout.addWidget(label, alignment=Qt.AlignCenter)
        return box

    def set_opacity(self, opacity: float) -> None:
        self.setWindowOpacity(opacity)

    def set_shot_clock_display(self, value: str) -> None:
        self.status_label.setText(value or "--")
        self._broadcast_shot_label.setText(value or "--")

    def set_game_clock_display(self, value: str) -> None:
        self.clock_label.setText(value or "--:--")
        self._broadcast_clock_label.setText(value or "--:--")

    def _apply_clock_font_size(self, is_timeout: bool) -> None:
        if is_timeout:
            self.clock_label.setStyleSheet("color: #ffffff; font-size: 8px; font-weight: 700;")
            self._broadcast_clock_label.setStyleSheet("color: #ffffff; font-size: 9px; font-weight: 700;")
        else:
            self.clock_label.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 700;")
            self._broadcast_clock_label.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700;")

    def set_timeout_team(self, tricode: str) -> None:
        self._timeout_team_tricode = (tricode or "").upper()

    def set_player_panel_visible(self, team_tricode: str) -> None:
        self._player_panel_team = (team_tricode or "").upper()
        show = bool(self._player_panel_team) and self._layout_mode == "broadcast"
        self._player_panel.setVisible(show)
        self._player_panel_container.setVisible(show)

    def set_player_stats(self, team_tricode: str, players: list[dict]) -> None:
        if self._layout_mode != "broadcast":
            return
        if not self._player_panel.isVisible():
            return
        if self._player_panel_team != (team_tricode or "").upper():
            return

        self._player_header.setText(f"{self._player_panel_team} Players")
        self._clear_layout(self._player_table_layout)

        headers = ["PLAYER", "PTS", "AST", "REB"]
        for col, text in enumerate(headers):
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #bbbbbb; font-weight: 700; font-size: 10px;")
            self._player_table_layout.addWidget(lbl, 0, col)

        for row, player in enumerate(players, start=1):
            name = player.get("name", "")
            pts = str(player.get("points", 0))
            ast = str(player.get("assists", 0))
            reb = str(player.get("rebounds", 0))
            for col, value in enumerate([name, pts, ast, reb]):
                lbl = QLabel(value)
                lbl.setStyleSheet("color: #ffffff; font-size: 11px;")
                self._player_table_layout.addWidget(lbl, row, col)

        width = self.get_broadcast_bar_width()
        if width > 0:
            self._player_panel.setFixedWidth(width)

    def set_language(self, language: str) -> None:
        self._language = language or "en"

    def set_layout_mode(self, mode: str) -> None:
        self._layout_mode = mode or "side_by_side"
        self._apply_layout_mode()

    def _set_timeouts(self, row: QWidget, remaining: int, max_timeouts: int = 7) -> None:
        blocks = getattr(row, "_timeout_blocks", [])
        remaining = max(0, min(max_timeouts, int(remaining)))
        for idx, block in enumerate(blocks):
            color = self._timeouts_active_color if idx < remaining else self._timeouts_inactive_color
            block.setStyleSheet(f"background: {color};")

    def _apply_layout_mode(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)

        if self._layout_mode == "broadcast":
            self._grid.setHorizontalSpacing(0)
            self._grid.setVerticalSpacing(10)
            self._move_to_layout(self.away_bar, self._away_section_layout)
            self._move_to_layout(self.home_bar, self._home_section_layout)
            self._cont_layout.setAlignment(Qt.AlignLeft)
            self._home_section_layout.setAlignment(Qt.AlignLeft)
            self._away_section_layout.setAlignment(Qt.AlignLeft)
            if self._broadcast_footer.parent() is None:
                self._home_section_layout.addWidget(self._broadcast_footer)
            self.home_timeouts.hide()
            self.away_timeouts.hide()
            self._grid.addWidget(self._away_section, 0, 0)
            self._grid.addWidget(self._home_section, 1, 0)
            self._grid.addWidget(self.away_delta, 0, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
            self._grid.addWidget(self.home_delta, 1, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
            self._grid.setColumnStretch(0, 1)
            self._grid.setRowStretch(0, 1)
            self._grid.setRowStretch(1, 1)
            self._remove_from_layout(self._timeouts_row)
            self._footer.setVisible(False)
            self._broadcast_footer.setVisible(True)
            self._set_footer_box_size(20)
            self._set_footer_font_size(12)
            self._sync_footer_width()
            self._apply_broadcast_sizes()
            self._player_panel.setVisible(bool(self._player_panel_team))
        else:
            self._grid.setHorizontalSpacing(2)
            self._grid.setVerticalSpacing(2)
            self._cont_layout.setAlignment(Qt.AlignCenter)
            self._home_section_layout.setAlignment(Qt.AlignCenter)
            self._away_section_layout.setAlignment(Qt.AlignCenter)
            self._move_to_layout(self.away_bar, self._grid, 0, 0)
            self._move_to_layout(self.home_bar, self._grid, 0, 1)
            self._grid.addWidget(self.away_delta, 0, 0, alignment=Qt.AlignLeft | Qt.AlignVCenter)
            self._grid.addWidget(self.home_delta, 0, 1, alignment=Qt.AlignRight | Qt.AlignVCenter)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 1)
            self._timeouts_layout.addWidget(self.away_timeouts, 0, 0)
            self._timeouts_layout.addWidget(self.home_timeouts, 0, 1)
            self.home_timeouts.show()
            self.away_timeouts.show()
            if self._timeouts_row.parent() is None:
                self._cont_layout.insertWidget(1, self._timeouts_row)
            self._timeouts_row.setVisible(True)
            self._footer.setVisible(True)
            self._broadcast_footer.setVisible(False)
            self._player_panel.setVisible(False)
            self._set_footer_box_size(20)
            self._set_footer_font_size(12)
            self._sync_footer_width()

        self._apply_team_bar_mode()

    def _apply_broadcast_sizes(self) -> None:
        target_width = self._broadcast_target_width()
        if target_width > 0:
            self._home_section.setFixedWidth(target_width)
            self._away_section.setFixedWidth(target_width)
            self.home_bar.setFixedWidth(target_width)
            self.away_bar.setFixedWidth(target_width)
            self._home_section_layout.setAlignment(Qt.AlignLeft)
            self._away_section_layout.setAlignment(Qt.AlignLeft)

    def _broadcast_target_width(self) -> int:
        if self._broadcast_fixed_width:
            return int(self._broadcast_fixed_width)
        base_width = max(
            self._home_section.sizeHint().width(),
            self._away_section.sizeHint().width(),
            self.home_bar.sizeHint().width(),
            self.away_bar.sizeHint().width(),
            self.container.width(),
            self.width(),
        )
        layout = self.layout()
        if layout is not None:
            margins = layout.contentsMargins()
            base_width = max(base_width, self.width() - margins.left() - margins.right())
        if base_width <= 0:
            return 0
        return int(base_width * self._broadcast_width_scale)

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
                color = sample.pixelColor(x, y)
                if color.alpha() < 10:
                    continue
                edge_total += 1
                if color.value() > 230 and color.saturation() < 30:
                    edge_whites += 1
        for y in range(sample.height()):
            for x in (0, sample.width() - 1):
                color = sample.pixelColor(x, y)
                if color.alpha() < 10:
                    continue
                edge_total += 1
                if color.value() > 230 and color.saturation() < 30:
                    edge_whites += 1
        if edge_total > 0 and (edge_whites / edge_total) >= 0.6:
            return QColor("#ffffff")

        bins: dict[tuple[int, int, int], list[int]] = {}
        for x in range(sample.width()):
            for y in range(sample.height()):
                color = sample.pixelColor(x, y)
                if color.alpha() < 10:
                    continue
                if color.value() > 240 and color.saturation() < 30:
                    continue
                r = color.red()
                g = color.green()
                b = color.blue()
                bin_key = (r // 16, g // 16, b // 16)
                if bin_key not in bins:
                    bins[bin_key] = [0, 0, 0, 0]
                bins[bin_key][0] += 1
                bins[bin_key][1] += r
                bins[bin_key][2] += g
                bins[bin_key][3] += b
        if not bins:
            return team_color(tricode)
        dominant = max(bins.values(), key=lambda v: v[0])
        count = dominant[0]
        avg = QColor(dominant[1] // count, dominant[2] // count, dominant[3] // count)
        self._logo_color_cache[key] = avg.name()
        return avg

    def _timeout_dot_color(self, tricode: str) -> str:
        if not tricode:
            return "#ffffff"
        team_color_value = team_color(tricode)
        dot_color = QColor("#ff3b30")
        dr = abs(team_color_value.red() - dot_color.red())
        dg = abs(team_color_value.green() - dot_color.green())
        db = abs(team_color_value.blue() - dot_color.blue())
        if (dr + dg + db) < 120:
            return "#ffffff"
        return "#ff3b30"

    @staticmethod
    def _apply_logo_mask(label: QLabel) -> None:
        size = label.size()
        if size.width() <= 0 or size.height() <= 0:
            return
        rect = QRect(0, 0, size.width(), size.height())
        label.setMask(QRegion(rect, QRegion.Ellipse))

    def get_broadcast_bar_width(self) -> int:
        if self._layout_mode != "broadcast":
            return self.width()
        target = self._broadcast_target_width()
        if target > 0:
            return target
        return max(self._home_section.sizeHint().width(), self._away_section.sizeHint().width())

    @staticmethod
    def _move_to_layout(widget: QWidget, layout, row: int | None = None, col: int | None = None) -> None:
        widget.setParent(None)
        if isinstance(layout, QGridLayout):
            layout.addWidget(widget, row or 0, col or 0)
        else:
            layout.addWidget(widget)

    def _set_footer_box_size(self, height: int) -> None:
        for box in self._footer_boxes:
            box.setMinimumHeight(height)

    def _set_footer_font_size(self, size: int) -> None:
        self.period_label.setStyleSheet(f"color: #ffffff; font-size: {size}px; font-weight: 700;")
        self.clock_label.setStyleSheet(f"color: #ffffff; font-size: {size}px; font-weight: 700;")
        self.status_label.setStyleSheet(f"color: #ffffff; font-size: {size}px; font-weight: 700;")

    def _sync_footer_width(self) -> None:
        if self._layout_mode == "broadcast":
            score_width = max(self._home_section.sizeHint().width(), self._away_section.sizeHint().width())
        else:
            score_width = self._grid.sizeHint().width()
        if score_width > 0:
            self._footer.setFixedWidth(score_width)

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if self._layout_mode == "broadcast":
            self._apply_broadcast_sizes()
            self._sync_footer_width()

    @staticmethod
    def _remove_from_layout(widget: QWidget) -> None:
        parent = widget.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().removeWidget(widget)
        widget.setParent(None)

    @staticmethod
    def _format_period(game: GameState) -> str:
        """格式化节次为 1st/2nd/3rd/4th 或 OT."""
        p = game.period
        if p <= 0:
            return game.status_text or ""
        suffix = {1: "1st", 2: "2nd", 3: "3rd"}.get(p, f"{p}th")
        return suffix

    @staticmethod
    def _format_overtime_period(period: int) -> str:
        if period <= 4:
            return {1: "1st", 2: "2nd", 3: "3rd"}.get(period, f"{period}th")
        ot_num = period - 4
        ot_prefix = {1: "1st", 2: "2nd", 3: "3rd"}.get(ot_num, f"{ot_num}th")
        return f"{ot_prefix} OT"

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
            if any(token in status for token in ("HALF", "HALFTIME", "END", "BREAK")):
                return True
        return False

