from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

import keyboard
from PySide6.QtCore import QPoint, QThread, QTimer, Qt, Signal, QEvent
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QIcon, QPixmap, QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

from app.models import GameDiff, GameState
from app.resources import team_display_name
from app.ui.broadcast_widget import BroadcastScoreboardWidget
from app.ui.poll_worker import PollWorker
from app.ui.scoreboard_widget import ScoreboardWidget

log = logging.getLogger(__name__)


class ScoreboardWindow(QMainWindow):
    """
    主窗体：无边框、置顶、小尺寸，用于承载比分控件并定时刷新。
    """

    toggle_visibility_signal = Signal()
    selected_game_changed = Signal(str)
    poll_once_requested = Signal()

    def __init__(
        self,
        refresh_ms: int = 400,
        hotkey: str = "alt+x",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.refresh_ms = refresh_ms
        self.hotkey = hotkey
        # 直接连接 NBA API，不使用代理
        self.proxy = None
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.8",
            "Origin": "https://www.nba.com",
            "Referer": "https://www.nba.com/",
        }
        self.selected_game_id: Optional[str] = None
        self._game_date: str = ""
        self._shot_clock_display: str = "--"
        self._shot_clock_game_id: str = ""
        self._language = "en"
        self._mouse_press_pos: Optional[QPoint] = None
        self._last_diffs: list[GameDiff] = []
        self._player_panel_team = ""
        self._player_panel_window = self._build_player_panel_window()
        self.theme = "broadcast"
        self.opacity_level = 1.0
        self.topmost = True
        self._control_default_sizes = {
            "theme_box": 80,
            "game_picker": 270,
            "opacity_slider": 120,
            "lang_button": 50,
            "top_button": 50,
            "close_button": 40,
        }

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._main_layout = layout

        self._control_bar = self._build_control_bar()
        self._control_bar_window = self._build_control_bar_window()
        self._control_bar_window.installEventFilter(self)
        self._control_bar.installEventFilter(self)
        self._control_bar_left_offset = 0

        self.standard_widget = ScoreboardWidget(self)
        self.broadcast_widget = BroadcastScoreboardWidget(self)
        self.score_widget = self.standard_widget
        self.score_widget.set_language(self._language)
        self.broadcast_widget.period_clicked.connect(self._toggle_broadcast_control_bar)
        self.broadcast_widget.team_bar_right_clicked.connect(self._toggle_player_panel)
        self._apply_theme()
        self.score_widget.set_opacity(self.opacity_level)
        layout.addWidget(self.score_widget)

        self.setCentralWidget(container)
        self.setFixedWidth(320)

        # 后台轮询线程
        self.worker_thread = QThread(self)
        self.worker = PollWorker(
            refresh_ms=refresh_ms,
            timeout=20,
            retries=3,
            proxy=self.proxy,
            headers=self.headers,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker.data_ready.connect(self._apply_diffs)
        self.worker.error.connect(self._on_worker_error)
        self.selected_game_changed.connect(self.worker.set_selected_game_id)
        self.poll_once_requested.connect(self.worker.poll_once, Qt.QueuedConnection)
        self.worker_thread.start()

        # 定时刷新（排队到 worker 线程）
        self.timer = QTimer(self)
        self.timer.setInterval(self.refresh_ms)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.worker.poll_once, Qt.QueuedConnection)
        self.timer.start()

        # 托盘与热键
        self._init_tray()
        self._register_hotkey()
        self._toggle_shortcut = QShortcut(QKeySequence("Alt+X"), self)
        self._toggle_shortcut.setContext(Qt.ApplicationShortcut)
        self._toggle_shortcut.activated.connect(self._toggle_visibility)
        self.toggle_visibility_signal.connect(self._toggle_visibility)

        # 初次刷新（排队到 worker 线程，避免阻塞 UI 启动）
        QTimer.singleShot(0, self.poll_once_requested.emit)

    # 拖动支持
    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        if event.button() == Qt.LeftButton:
            self._mouse_press_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._mouse_press_pos and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._mouse_press_pos)
            event.accept()
            self._sync_player_panel_position()
            self._sync_control_bar_position()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._mouse_press_pos = None
        super().mouseReleaseEvent(event)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        if obj in (self._control_bar_window, self._control_bar):
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._mouse_press_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return True
            if event.type() == QEvent.MouseMove and event.buttons() & Qt.LeftButton:
                if self._mouse_press_pos:
                    self.move(event.globalPosition().toPoint() - self._mouse_press_pos)
                    self._sync_player_panel_position()
                    self._sync_control_bar_position()
                    event.accept()
                    return True
            if event.type() == QEvent.MouseButtonRelease:
                self._mouse_press_pos = None
        return super().eventFilter(obj, event)

    def closeEvent(self, event):  # noqa: N802
        self._unregister_hotkey()
        if self.tray_icon:
            self.tray_icon.hide()
        self._player_panel_window.hide()
        self._control_bar_window.hide()
        super().closeEvent(event)

    def _on_worker_error(self, msg: str) -> None:
        log.warning("Scoreboard poll failed: %s", msg)
        self._set_no_games_placeholder("Network error")
        self.score_widget.render_game(None)

    def _apply_diffs(
        self,
        diffs: list[GameDiff],
        game_date: str,
        shot_clock: str,
        shot_clock_game_id: str,
        timeout_team: str,
        player_stats: list[dict],
        player_team: str,
    ) -> None:
        self._game_date = self._format_game_date(game_date)
        self._shot_clock_display = shot_clock or "--"
        self._shot_clock_game_id = shot_clock_game_id or ""
        if not diffs:
            self._set_no_games_placeholder("No games today")
            self.score_widget.render_game(None)
            self.score_widget.set_shot_clock_display("--")
            self.score_widget.set_timeout_team("")
            self._player_panel_window.hide()
            return

        self._last_diffs = diffs
        self._refresh_game_picker()

        # 选中逻辑：若有指定 game_id，优先，否则取第一场
        chosen: Optional[GameDiff] = None
        if self.selected_game_id:
            for d in diffs:
                if d.game.game_id == self.selected_game_id:
                    chosen = d
                    break
        if not chosen:
            chosen = diffs[0]
            self.selected_game_id = chosen.game.game_id

        self.score_widget.set_timeout_team(timeout_team)
        self.score_widget.render_diff(chosen)
        self._update_player_panel(player_team, player_stats)
        self._sync_polling_state(chosen.game)
        log.info(
            "[%s] SCORE %s %s-%s | PERIOD %s | CLOCK %s | SHOT %s",
            datetime.now().isoformat(timespec="milliseconds"),
            chosen.game.away.tricode,
            chosen.game.away.score,
            chosen.game.home.score,
            chosen.game.period,
            chosen.game.game_clock or "--:--",
            self._shot_clock_display or "--",
        )
        if self.selected_game_id:
            self.selected_game_changed.emit(self.selected_game_id)
        if self._shot_clock_game_id == self.selected_game_id:
            self.score_widget.set_shot_clock_display(self._shot_clock_display)
        else:
            self.score_widget.set_shot_clock_display("--")

    def _refresh_game_picker(self) -> None:
        current_id = self.selected_game_id
        self.game_picker.blockSignals(True)
        self.game_picker.clear()
        if not self._last_diffs:
            self.game_picker.addItem("NONE @ NONE  No games today", None)
        else:
            for d in self._last_diffs:
                status = d.game.status_text or ""
                clock = d.game.clock_display or ""
                status_label = self._format_status_label(status, clock)
                date_suffix = f"  {self._game_date}" if self._game_date else ""
                time_label = self._format_game_time(d.game.game_time_utc)
                away_name = team_display_name(d.game.away.tricode, self._language)
                home_name = team_display_name(d.game.home.tricode, self._language)
                label = f"{away_name} @ {home_name}  {time_label}  {status_label}{date_suffix}"
                self.game_picker.addItem(label.strip(), d.game.game_id)
        if current_id:
            idx = self.game_picker.findData(current_id)
            if idx >= 0:
                self.game_picker.setCurrentIndex(idx)
        self.game_picker.blockSignals(False)

    def _on_game_selected(self, index: int) -> None:
        game_id = self.game_picker.itemData(index)
        if game_id:
            self.selected_game_id = game_id
            self.selected_game_changed.emit(game_id)
            for d in self._last_diffs:
                if d.game.game_id == game_id:
                    self.score_widget.render_diff(d)
                    break
            if self._shot_clock_game_id == game_id:
                self.score_widget.set_shot_clock_display(self._shot_clock_display)
            else:
                self.score_widget.set_shot_clock_display("--")
        else:
            self.score_widget.render_game(None)
            self.score_widget.set_shot_clock_display("--")

    def _on_language_toggle(self) -> None:
        self._language = "zh" if self.lang_button.isChecked() else "en"
        self.lang_button.setText("中" if self._language == "zh" else "EN")
        self.score_widget.set_language(self._language)
        self._refresh_game_picker()
        if self.selected_game_id:
            for d in self._last_diffs:
                if d.game.game_id == self.selected_game_id:
                    self.score_widget.render_diff(d)
                    break

    def _set_no_games_placeholder(self, text: str = "No games") -> None:
        self.game_picker.blockSignals(True)
        self.game_picker.clear()
        date_suffix = f"  {self._game_date}" if self._game_date else ""
        self.game_picker.addItem(f"NONE @ NONE  {text}{date_suffix}", None)
        self.game_picker.blockSignals(False)

    @staticmethod
    def _format_game_date(game_date: str) -> str:
        if not game_date:
            return ""
        try:
            return datetime.strptime(game_date, "%Y-%m-%d").strftime("%m.%d")
        except ValueError:
            return game_date

    @staticmethod
    def _format_game_time(game_time_utc: Optional[str]) -> str:
        if not game_time_utc:
            return "--:--"
        try:
            normalized = game_time_utc.replace("Z", "+00:00")
            utc_time = datetime.fromisoformat(normalized)
            if utc_time.tzinfo is None:
                utc_time = utc_time.replace(tzinfo=timezone.utc)
            beijing_time = utc_time.astimezone(timezone(timedelta(hours=8)))
            return beijing_time.strftime("%H:%M")
        except ValueError:
            return "--:--"

    @staticmethod
    def _format_status_label(status: str, clock: str) -> str:
        status_upper = status.strip().upper()
        clock_upper = clock.strip().upper()
        if status_upper == "FINAL" and clock_upper == "FINAL":
            return "已结束"
        if status_upper == "PPD" and clock_upper == "PPD":
            return "延期"
        return "比赛进行中"

    # 控制条与托盘
    def _build_control_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(82)
        bar.setStyleSheet("background: rgba(24,24,24,0.92); border-radius: 10px;")

        outer = QVBoxLayout(bar)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(6)
        self._control_row2 = row2

        self.theme_box = QComboBox()
        self.theme_box.addItems(["dark", "light", "broadcast"])
        self.theme_box.setCurrentText(self.theme)
        self.theme_box.currentTextChanged.connect(self._on_theme_changed)
        self.theme_box.setFixedWidth(self._control_default_sizes["theme_box"])
        self.theme_box.setStyleSheet(
            "background: rgba(50,50,50,0.85); color: white; padding: 4px 6px; selection-background-color: #1e88e5;"
        )

        self.game_picker = QComboBox()
        self.game_picker.setEditable(False)
        self.game_picker.currentIndexChanged.connect(self._on_game_selected)
        self.game_picker.setFixedWidth(self._control_default_sizes["game_picker"])
        self.game_picker.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.game_picker.setMinimumContentsLength(10)
        self.game_picker.view().setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.game_picker.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.game_picker.view().setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.game_picker.view().setMinimumWidth(260)
        self.game_picker.setStyleSheet(
            "QComboBox {"
            "background: rgba(50,50,50,0.9); color: white; padding: 4px 6px; selection-background-color: #1e88e5;"
            "border: 1px solid #555; border-radius: 6px;"
            "}"
            "QComboBox QAbstractItemView {"
            "background: rgba(35,35,35,0.95); color: white; selection-background-color: #1e88e5;"
            "}"
        )
        self.game_picker.setMaxVisibleItems(15)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(int(self.opacity_level * 100))
        self.opacity_slider.setFixedWidth(self._control_default_sizes["opacity_slider"])
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)

        self.lang_button = QPushButton("EN")
        self.lang_button.setCheckable(True)
        self.lang_button.setChecked(False)
        self.lang_button.clicked.connect(self._on_language_toggle)
        self.lang_button.setToolTip("球队名称中英文切换")
        self.lang_button.setStyleSheet(
            "QPushButton { color: #ddd; background: rgba(80,80,80,0.8); border: 1px solid #666; border-radius: 4px; padding: 4px 8px; }"
            "QPushButton:hover { background: rgba(95,95,95,0.9); }"
            "QPushButton:pressed { background: rgba(60,60,60,0.9); }"
            "QPushButton:checked { background: #1e88e5; color: white; }"
        )
        self.lang_button.setMinimumWidth(self._control_default_sizes["lang_button"])

        self.top_button = QPushButton("Top")
        self.top_button.setCheckable(True)
        self.top_button.setChecked(self.topmost)
        self.top_button.clicked.connect(self._on_top_toggle)
        self.top_button.setToolTip("窗口置顶开关")
        self.top_button.setStyleSheet(
            "QPushButton { color: #ddd; background: rgba(80,80,80,0.8); border: 1px solid #666; border-radius: 4px; padding: 4px 8px; }"
            "QPushButton:hover { background: rgba(95,95,95,0.9); }"
            "QPushButton:pressed { background: rgba(60,60,60,0.9); }"
            "QPushButton:checked { background: #1e88e5; color: white; }"
            "QPushButton:checked:hover { background: #1976d2; }"
            "QPushButton:checked:pressed { background: #1565c0; }"
        )
        self.top_button.setMinimumWidth(self._control_default_sizes["top_button"])

        btn_close = QPushButton("Quit")
        btn_close.setMinimumWidth(self._control_default_sizes["close_button"])
        btn_close.setStyleSheet(
            "QPushButton { color: white; background: rgba(160,60,60,0.9); border: 1px solid #933; border-radius: 4px; padding: 4px 8px; }"
            "QPushButton:hover { background: rgba(180,70,70,0.95); }"
            "QPushButton:pressed { background: rgba(130,50,50,0.95); }"
        )
        btn_close.clicked.connect(self._quit_fast)
        self._close_button = btn_close

        row1.addWidget(self.theme_box)
        row1.addWidget(self.game_picker)
        row1.addStretch()

        row2.addWidget(self.opacity_slider)
        row2.addStretch()
        row2.addWidget(self.lang_button)
        row2.addWidget(self.top_button)
        row2.addWidget(btn_close)

        outer.addLayout(row1)
        outer.addLayout(row2)

        return bar

    def _init_tray(self) -> None:
        icon = self._resolve_tray_icon()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("System tray is not available.")
            self.tray_icon = None
            return
        self.tray_icon = QSystemTrayIcon()
        self.tray_icon.setIcon(icon)
        menu = QMenu()
        act_show = QAction("Show/Hide", self)
        act_show.triggered.connect(self._toggle_visibility)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(QApplication.instance().quit)
        menu.addAction(act_show)
        menu.addAction(act_quit)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.setToolTip("NBA Scoreboard Widget")
        self.tray_icon.setVisible(True)
        self.tray_icon.show()
        self.tray_icon.showMessage(
            "NBA Scoreboard Widget",
            "托盘图标已创建，可在右下角隐藏图标中查看。",
            QSystemTrayIcon.Information,
            3000,
        )

    @staticmethod
    def _resolve_tray_icon() -> QIcon:
        repo_root = Path(__file__).resolve().parents[3]
        icon_path = repo_root / "src" / "simple_circle_lakers_000.png"
        if icon_path.exists():
            return QIcon(str(icon_path))
        icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)
        if not icon.isNull():
            return icon
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("#1e88e5"))
        return QIcon(pixmap)

    def _register_hotkey(self) -> None:
        try:
            keyboard.add_hotkey(self.hotkey, lambda: self.toggle_visibility_signal.emit())
            log.info("Registered hotkey: %s", self.hotkey)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to register hotkey %s: %s", self.hotkey, exc)

    def _unregister_hotkey(self) -> None:
        try:
            keyboard.remove_hotkey(self.hotkey)
        except Exception:
            pass

    def _toggle_visibility(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
            self._player_panel_window.hide()
            self._control_bar_window.hide()
            if self.tray_icon:
                self.tray_icon.setIcon(self._resolve_tray_icon())
                self.tray_icon.setVisible(True)
                self.tray_icon.show()
            else:
                self._init_tray()
        else:
            self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()
            self._control_bar_window.show()
            self._sync_control_bar_position()
            if self.theme == "broadcast" and self._player_panel_team:
                self._player_panel_window.show()
                self._sync_player_panel_position()
        self._apply_topmost()

    def closeEvent(self, event):  # noqa: N802
        self._unregister_hotkey()
        if self.tray_icon:
            self.tray_icon.hide()
        self.timer.stop()
        self.worker_thread.quit()
        self.worker_thread.wait(300)
        super().closeEvent(event)

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._sync_control_bar_width()

    # 主题/透明度/置顶
    def _on_theme_changed(self, theme: str) -> None:
        self.theme = theme
        self._apply_theme()

    def _apply_theme(self) -> None:
        if self.theme == "light":
            self.setStyleSheet("background: rgba(245,245,245,0.03);")
            self._control_bar.setStyleSheet("background: rgba(245,245,245,0.95); border-radius: 10px;")
            self._set_score_widget(self.standard_widget)
            self.score_widget.apply_theme(
                text_color="#ffffff",
                sub_text="#333333",
                delta_color="#d9534f",
                container_bg="#f5f5f5",
                border_color="#cfcfcf",
                timeouts_active_color="#ffa200",
                timeouts_inactive_color="#d0d0d0",
            )
            self.standard_widget.set_layout_mode("side_by_side")
            self.setFixedWidth(320)
            self._apply_control_sizes(compact=False)
        elif self.theme == "broadcast":
            self.setStyleSheet("background: rgba(0,0,0,0.01);")
            self._control_bar.setStyleSheet("background: rgba(24,24,24,0.92); border-radius: 12px;")
            self._set_score_widget(self.broadcast_widget)
            self.score_widget.apply_theme(
                text_color="#ffffff",
                sub_text="#cccccc",
                delta_color="#ffd166",
                container_bg="rgba(0,0,0,0)",
                border_color="transparent",
                timeouts_active_color="#f1c40f",
                timeouts_inactive_color="#6e6e6e",
                footer_bg="#000000",
                footer_border="#111111",
            )
            self._control_bar.setFixedHeight(82)
            self.setFixedWidth(252)
            self._apply_control_sizes(compact=True)
            self._control_bar_left_offset = 10
            self._main_layout.setAlignment(self.score_widget, Qt.AlignLeft)
            self._control_bar_window.show()
        else:
            self.setStyleSheet("background: rgba(0,0,0,0.01);")
            self._control_bar.setStyleSheet("background: rgba(24,24,24,0.92); border-radius: 12px;")
            self._set_score_widget(self.standard_widget)
            self.score_widget.apply_theme(
                text_color="#ffffff",
                sub_text="#dddddd",
                delta_color="#ffd166",
                container_bg="#111111",
                border_color="#444444",
                timeouts_active_color="#ffffff",
                timeouts_inactive_color="#333333",
            )
            self.standard_widget.set_layout_mode("side_by_side")
            self.setFixedWidth(320)
            self._control_bar.setFixedHeight(82)
            self._apply_control_sizes(compact=False)
            self._control_bar_left_offset = 0
            self._main_layout.setAlignment(self.score_widget, Qt.AlignCenter)
            self._control_bar_window.show()
            self._player_panel_window.hide()
            self._player_panel_team = ""
            if hasattr(self, "worker"):
                self.worker.set_player_stats_team("")
        self._sync_control_bar_width()
        self._sync_control_bar_position()

    def _set_score_widget(self, widget: ScoreboardWidget) -> None:
        if self.score_widget is widget:
            return
        self._main_layout.removeWidget(self.score_widget)
        self.score_widget.setParent(None)
        self.score_widget = widget
        self.score_widget.set_language(self._language)
        self.score_widget.set_opacity(self.opacity_level)
        self._main_layout.insertWidget(1, self.score_widget)
        self._render_current_game()
        self._sync_control_bar_width()
        if self.theme == "broadcast":
            self._main_layout.setAlignment(self.score_widget, Qt.AlignLeft)
        else:
            self._main_layout.setAlignment(self.score_widget, Qt.AlignCenter)

    def _sync_control_bar_width(self) -> None:
        if self.theme == "broadcast":
            width = self.score_widget.get_broadcast_bar_width()
            if width > 0:
                control_width = max(width, 300)
                self._control_bar.setFixedWidth(control_width)
                self._control_bar_window.setFixedWidth(control_width)
        else:
            self._control_bar.setFixedWidth(self.width())
            self._control_bar_window.setFixedWidth(self.width())

    def _apply_control_sizes(self, compact: bool) -> None:
        if compact:
            self.theme_box.setFixedWidth(60)
            self.game_picker.setFixedWidth(220)
            self.game_picker.view().setMinimumWidth(220)
            self.opacity_slider.setFixedWidth(120)
            max_button_width = max(
                self.lang_button.sizeHint().width(),
                self.top_button.sizeHint().width(),
                self._close_button.sizeHint().width(),
            )
            max_button_height = max(
                self.lang_button.sizeHint().height(),
                self.top_button.sizeHint().height(),
                self._close_button.sizeHint().height(),
            )
            self.lang_button.setFixedWidth(max_button_width)
            self.lang_button.setFixedHeight(max_button_height)
            self.top_button.setFixedWidth(max_button_width)
            self.top_button.setFixedHeight(max_button_height)
            self._close_button.setFixedWidth(max_button_width)
            self._close_button.setFixedHeight(max_button_height)
            if hasattr(self, "_control_row2"):
                self._control_row2.setContentsMargins(0, 0, 5, 0)
        else:
            self.theme_box.setFixedWidth(self._control_default_sizes["theme_box"])
            self.game_picker.setFixedWidth(self._control_default_sizes["game_picker"])
            self.game_picker.view().setMinimumWidth(self._control_default_sizes["game_picker"])
            self.opacity_slider.setFixedWidth(self._control_default_sizes["opacity_slider"])
            max_button_width = max(
                self.lang_button.sizeHint().width(),
                self.top_button.sizeHint().width(),
                self._close_button.sizeHint().width(),
            )
            max_button_height = max(
                self.lang_button.sizeHint().height(),
                self.top_button.sizeHint().height(),
                self._close_button.sizeHint().height(),
            )
            self.lang_button.setFixedWidth(max_button_width)
            self.lang_button.setFixedHeight(max_button_height)
            self.top_button.setFixedWidth(max_button_width)
            self.top_button.setFixedHeight(max_button_height)
            self._close_button.setFixedWidth(max_button_width)
            self._close_button.setFixedHeight(max_button_height)
            if hasattr(self, "_control_row2"):
                self._control_row2.setContentsMargins(0, 0, 0, 0)

    def _toggle_broadcast_control_bar(self) -> None:
        if self.theme != "broadcast":
            return
        self._control_bar_window.setVisible(not self._control_bar_window.isVisible())
        self._sync_control_bar_position()

    def _toggle_player_panel(self, tricode: str) -> None:
        if self.theme != "broadcast":
            return
        tricode = (tricode or "").upper()
        if self._player_panel_team == tricode:
            self._player_panel_team = ""
            self._player_panel_window.hide()
            self.worker.set_player_stats_team("")
            return
        self._player_panel_team = tricode
        self.worker.set_player_stats_team(tricode)
        # 结束比赛可能已停止轮询，右击时触发一次拉取
        self.poll_once_requested.emit()
        self._player_panel_window.show()
        self._sync_player_panel_position()
        self._update_player_panel(tricode, [])

    def _build_player_panel_window(self) -> QWidget:
        panel = QFrame(self)
        panel.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        panel.setAttribute(Qt.WA_TranslucentBackground, True)
        panel.setStyleSheet("background: transparent;")
        panel.setStyleSheet("QFrame { background: #000000; border-radius: 8px; }")
        panel.setVisible(False)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        container = QFrame()
        container.setStyleSheet("QFrame { background: #000000; border-radius: 12px; }")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(8, 6, 8, 6)
        container_layout.setSpacing(4)

        self._player_header = QLabel("")
        self._player_header.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 12px;")
        container_layout.addWidget(self._player_header)

        self._player_table = QWidget()
        self._player_table_layout = QGridLayout(self._player_table)
        self._player_table_layout.setContentsMargins(0, 0, 0, 0)
        self._player_table_layout.setHorizontalSpacing(6)
        self._player_table_layout.setVerticalSpacing(2)
        container_layout.addWidget(self._player_table)
        layout.addWidget(container)
        return panel

    def _build_control_bar_window(self) -> QWidget:
        panel = QFrame(self)
        panel.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        panel.setAttribute(Qt.WA_TranslucentBackground, True)
        panel.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._control_bar)
        panel.setVisible(True)
        return panel

    def _update_player_panel(self, team_tricode: str, players: list[dict]) -> None:
        if self.theme != "broadcast" or not self._player_panel_window.isVisible():
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
        if not players:
            empty = QLabel("Loading...")
            empty.setStyleSheet("color: #aaaaaa; font-size: 11px;")
            self._player_table_layout.addWidget(empty, 1, 0, 1, 4)
        else:
            for row, player in enumerate(players, start=1):
                name = player.get("name", "")
                pts = str(player.get("points", 0))
                ast = str(player.get("assists", 0))
                reb = str(player.get("rebounds", 0))
                for col, value in enumerate([name, pts, ast, reb]):
                    lbl = QLabel(value)
                    lbl.setStyleSheet("color: #ffffff; font-size: 11px;")
                    self._player_table_layout.addWidget(lbl, row, col)
        width = max(220, self.score_widget.get_broadcast_bar_width())
        self._player_panel_window.setFixedWidth(width)

    def _sync_player_panel_position(self) -> None:
        if not self._player_panel_window.isVisible():
            return
        offset_x = self.width() - 100
        offset_y = self.y()
        self._player_panel_window.move(self.x() + offset_x, offset_y)

    def _sync_control_bar_position(self) -> None:
        if not self._control_bar_window.isVisible():
            return
        y = self.y() - self._control_bar_window.height() - 4
        self._control_bar_window.move(self.x() + self._control_bar_left_offset, y)

    def _sync_polling_state(self, game: GameState) -> None:
        if game.is_final:
            if self.timer.isActive():
                self.timer.stop()
        else:
            if not self.timer.isActive():
                self.timer.start()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _render_current_game(self) -> None:
        if not self._last_diffs:
            self.score_widget.render_game(None)
            self.score_widget.set_shot_clock_display("--")
            return
        if self.selected_game_id:
            for d in self._last_diffs:
                if d.game.game_id == self.selected_game_id:
                    self.score_widget.render_diff(d)
                    break
        else:
            self.score_widget.render_diff(self._last_diffs[0])
        if self._shot_clock_game_id == self.selected_game_id:
            self.score_widget.set_shot_clock_display(self._shot_clock_display)
        else:
            self.score_widget.set_shot_clock_display("--")
        game = None
        if self.selected_game_id:
            for d in self._last_diffs:
                if d.game.game_id == self.selected_game_id:
                    game = d.game
                    break
        if not game and self._last_diffs:
            game = self._last_diffs[0].game
        if game:
            self._sync_polling_state(game)



    def _on_opacity_changed(self, value: int) -> None:
        self.opacity_level = max(0.3, min(1.0, value / 100.0))
        self.setWindowOpacity(self.opacity_level)
        self.score_widget.set_opacity(self.opacity_level)
        self._control_bar_window.setWindowOpacity(self.opacity_level)
        self._player_panel_window.setWindowOpacity(self.opacity_level)
        if hasattr(self, "opacity_value"):
            self.opacity_value.setText(f"{value}%")

    def _on_topmost_toggle(self, state: int) -> None:
        self.topmost = state == Qt.Checked
        self._apply_topmost()

    def _on_top_toggle(self) -> None:
        self.topmost = self.top_button.isChecked()
        self._apply_topmost()

    def _apply_topmost(self) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.topmost)
        self._control_bar_window.setWindowFlag(Qt.WindowStaysOnTopHint, self.topmost)
        self._player_panel_window.setWindowFlag(Qt.WindowStaysOnTopHint, self.topmost)
        if self.isVisible():
            self.show()
        if self._control_bar_window.isVisible():
            self._control_bar_window.show()
        if self._player_panel_window.isVisible():
            self._player_panel_window.show()

    def _quit_fast(self) -> None:
        # 尝试先停止计时器和线程，再快速退出
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            self.worker_thread.quit()
            self.worker_thread.wait(200)
        except Exception:
            pass
        QApplication.instance().quit()


def run_app() -> None:
    logging.basicConfig(level=logging.INFO)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(ScoreboardWindow._resolve_tray_icon())
    win = ScoreboardWindow()
    win.show()
    app.exec()


__all__ = ["ScoreboardWindow", "run_app"]

