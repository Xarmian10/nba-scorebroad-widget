from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

import keyboard
from PySide6.QtCore import QEvent, QPoint, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QIcon, QPixmap, QColor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.models import GameDiff, GameState, GameStatus
from app.resources import team_display_name
from app.ui.player_detail_widget import PlayerDetailWindow
from app.ui.poll_worker import PollWorker
from app.ui.scoreboard_widget import ScoreboardWidget

log = logging.getLogger(__name__)


class ScoreboardWindow(QMainWindow):
    """
    ESPN/TNT 风格 NBA 记分牌桌面组件。

    交互模型：
    - 左键单击：展开/收缩详细面板（球员数据 + 节次得分）
    - 右键单击：弹出设置菜单（选场次/主题/语言/置顶/透明度/退出）
    - 滚轮：调节窗口透明度
    - 拖拽：任意位置拖动窗口
    - Alt+X / 托盘：显示/隐藏
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
        self._language = "en"
        self._mouse_press_pos: Optional[QPoint] = None
        self._click_origin: Optional[QPoint] = None
        self._last_diffs: list[GameDiff] = []
        self.theme = "broadcast"
        self.opacity_level = 0.95
        self.topmost = True

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

        self.score_widget = ScoreboardWidget(self)
        self.score_widget.expand_toggled.connect(self._on_expand_toggled)
        self.score_widget.collapse_done.connect(self._adjust_size)
        self.score_widget.layout_changed.connect(self._adjust_size)
        self.score_widget.player_clicked.connect(self._on_player_clicked)
        layout.addWidget(self.score_widget)

        self._detail_window: Optional[PlayerDetailWindow] = None

        self.setCentralWidget(container)
        self.setFixedWidth(ScoreboardWidget.WIDGET_WIDTH)
        self._apply_theme()

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

        self.timer = QTimer(self)
        self.timer.setInterval(self.refresh_ms)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.worker.poll_once, Qt.QueuedConnection)
        self.timer.start()

        self._init_tray()
        self._register_hotkey()
        self._toggle_shortcut = QShortcut(QKeySequence("Alt+X"), self)
        self._toggle_shortcut.setContext(Qt.ApplicationShortcut)
        self._toggle_shortcut.activated.connect(self._toggle_visibility)
        self.toggle_visibility_signal.connect(self._toggle_visibility)

        QTimer.singleShot(0, self.poll_once_requested.emit)

    # ── Drag support ──────────────────────────────────────────

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._mouse_press_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            self._click_origin = event.globalPosition().toPoint()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._mouse_press_pos and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._mouse_press_pos)
            if self._detail_window and self._detail_window.isVisible():
                self._detail_window.follow_ref_window()
            event.accept()
        super().mouseMoveEvent(event)

    def moveEvent(self, event):  # noqa: N802
        super().moveEvent(event)
        if self._detail_window and self._detail_window.isVisible():
            self._detail_window.follow_ref_window()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._click_origin:
            delta = event.globalPosition().toPoint() - self._click_origin
            if delta.manhattanLength() < 5:
                click_local = self.score_widget.mapFromGlobal(
                    event.globalPosition().toPoint()
                )
                if self.score_widget._scorebug.geometry().contains(click_local):
                    self.score_widget.toggle_expanded()
        self._mouse_press_pos = None
        self._click_origin = None
        super().mouseReleaseEvent(event)

    # ── Right-click context menu ──────────────────────────────

    def contextMenuEvent(self, event):  # noqa: N802
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#1e1e22; color:#e4e4e7; border:1px solid #333; "
            "border-radius:6px; padding:4px 0; font-size:11px; }"
            "QMenu::item { padding:6px 20px; }"
            "QMenu::item:selected { background:#2d2d33; }"
            "QMenu::item:disabled { color:#666; }"
            "QMenu::separator { height:1px; background:#333; margin:4px 10px; }"
        )

        games_menu = menu.addMenu("Select Game")
        games_menu.setStyleSheet(menu.styleSheet())
        if self._last_diffs:
            for d in self._last_diffs:
                away = team_display_name(d.game.away.tricode, self._language)
                home = team_display_name(d.game.home.tricode, self._language)
                if d.game.is_live:
                    suffix = "  LIVE"
                elif d.game.is_final:
                    suffix = "  FINAL"
                else:
                    suffix = f"  {self._format_game_time(d.game.game_time_utc)}"
                act = games_menu.addAction(f"{away} @ {home}{suffix}")
                act.setData(d.game.game_id)
                if d.game.game_id == self.selected_game_id:
                    act.setCheckable(True)
                    act.setChecked(True)
            games_menu.triggered.connect(self._on_game_menu_action)
        else:
            games_menu.addAction("No games today").setEnabled(False)

        theme_menu = menu.addMenu("Theme")
        theme_menu.setStyleSheet(menu.styleSheet())
        for t_name, t_label in [
            ("dark", "Dark"),
            ("light", "Light"),
            ("broadcast", "Broadcast"),
        ]:
            act = theme_menu.addAction(t_label)
            act.setData(t_name)
            act.setCheckable(True)
            act.setChecked(t_name == self.theme)
        theme_menu.triggered.connect(self._on_theme_menu_action)

        lang_label = (
            "Language: English" if self._language == "zh" else "Language: Chinese"
        )
        lang_action = menu.addAction(lang_label)
        lang_action.triggered.connect(self._on_language_toggle)

        top_action = menu.addAction("Always on Top")
        top_action.setCheckable(True)
        top_action.setChecked(self.topmost)
        top_action.triggered.connect(self._on_top_toggle)

        menu.addSeparator()
        opacity_pct = int(self.opacity_level * 100)
        menu.addAction(f"Opacity: {opacity_pct}%  (scroll to adjust)").setEnabled(
            False
        )
        menu.addSeparator()
        menu.addAction("Quit", self._quit_fast)

        menu.exec(event.globalPos())

    # ── Scroll wheel opacity ──────────────────────────────────

    def wheelEvent(self, event):  # noqa: N802
        delta = event.angleDelta().y()
        current = int(self.opacity_level * 100)
        step = 5
        if delta > 0:
            current = min(100, current + step)
        else:
            current = max(30, current - step)
        self._set_opacity(current)
        event.accept()

    # ── Data handling ─────────────────────────────────────────

    def _on_worker_error(self, msg: str) -> None:
        log.warning("Poll failed: %s", msg)
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
        if not diffs:
            self.score_widget.render_game(None)
            return

        self._last_diffs = diffs
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
        self._sync_polling_state(chosen.game)

        if player_stats and self.score_widget.is_expanded:
            self.score_widget.set_player_stats(player_stats)

        if self.selected_game_id:
            self.selected_game_changed.emit(self.selected_game_id)

        log.info(
            "[%s] %s %s-%s | P%s | %s",
            datetime.now().isoformat(timespec="milliseconds"),
            chosen.game.away.tricode,
            chosen.game.away.score,
            chosen.game.home.score,
            chosen.game.period,
            chosen.game.game_clock or "--",
        )

    # ── Expand toggle ─────────────────────────────────────────

    def _on_expand_toggled(self, expanded: bool) -> None:
        if expanded:
            if self._last_diffs and self.selected_game_id:
                for d in self._last_diffs:
                    if d.game.game_id == self.selected_game_id:
                        both = f"{d.game.away.tricode},{d.game.home.tricode}"
                        self.worker.set_player_stats_team(both)
                        self.poll_once_requested.emit()
                        break
            QTimer.singleShot(10, self._adjust_size)
        else:
            self.worker.set_player_stats_team("")
            if self._detail_window and self._detail_window.isVisible():
                self._detail_window.hide_animated()

    def _adjust_size(self) -> None:
        w = ScoreboardWidget.WIDGET_WIDTH
        self.setFixedWidth(w)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.centralWidget().updateGeometry()
        self.adjustSize()

    # ── Player detail ─────────────────────────────────────────

    def _on_player_clicked(self, player_info: dict) -> None:
        if not self.selected_game_id:
            return
        if self._detail_window is None:
            self._detail_window = PlayerDetailWindow()
            self._detail_window.closed.connect(self._on_detail_closed)
        tricode = player_info.get("teamTricode", player_info.get("team", ""))
        self._detail_window.show_player(
            player_info,
            self.selected_game_id,
            tricode,
            ref_window=self,
            language=self._language,
        )

    def _on_detail_closed(self) -> None:
        pass

    # ── Menu actions ──────────────────────────────────────────

    def _on_game_menu_action(self, action) -> None:
        game_id = action.data()
        if not game_id:
            return
        if self._detail_window and self._detail_window.isVisible():
            self._detail_window.hide_animated()
        self.selected_game_id = game_id
        self.selected_game_changed.emit(game_id)
        for d in self._last_diffs:
            if d.game.game_id == game_id:
                self.score_widget.render_diff(d)
                break
        if self.score_widget.is_expanded:
            for d in self._last_diffs:
                if d.game.game_id == game_id:
                    both = f"{d.game.away.tricode},{d.game.home.tricode}"
                    self.worker.set_player_stats_team(both)
                    self.poll_once_requested.emit()
                    break

    def _on_theme_menu_action(self, action) -> None:
        theme = action.data()
        if theme:
            self.theme = theme
            self._apply_theme()

    def _on_language_toggle(self) -> None:
        self._language = "zh" if self._language == "en" else "en"
        self.score_widget.setUpdatesEnabled(False)
        self.score_widget.set_language(self._language)
        if self.selected_game_id:
            for d in self._last_diffs:
                if d.game.game_id == self.selected_game_id:
                    self.score_widget.render_game(d.game)
                    break
        self.score_widget.setUpdatesEnabled(True)
        self.score_widget.update()
        if self._detail_window and self._detail_window.isVisible():
            self._detail_window.set_language(self._language)

    def _on_top_toggle(self) -> None:
        self.topmost = not self.topmost
        self._apply_topmost()

    # ── Theme ─────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        self.score_widget.apply_theme(self.theme)
        self.setStyleSheet("background: transparent;")
        self.setFixedWidth(ScoreboardWidget.WIDGET_WIDTH)

    # ── Opacity ───────────────────────────────────────────────

    def _set_opacity(self, value: int) -> None:
        self.opacity_level = max(0.3, min(1.0, value / 100.0))
        self.setWindowOpacity(self.opacity_level)

    # ── Topmost ───────────────────────────────────────────────

    def _apply_topmost(self) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.topmost)
        if self.isVisible():
            self.show()

    # ── Polling state ─────────────────────────────────────────

    def _sync_polling_state(self, game: GameState) -> None:
        if game.is_final:
            if self.timer.isActive():
                self.timer.stop()
        else:
            if not self.timer.isActive():
                self.timer.start()

    # ── Tray & hotkey ─────────────────────────────────────────

    def _init_tray(self) -> None:
        icon = self._resolve_tray_icon()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("System tray not available.")
            self.tray_icon = None
            return
        self.tray_icon = QSystemTrayIcon()
        self.tray_icon.setIcon(icon)
        menu = QMenu()
        menu.addAction("Show/Hide", self._toggle_visibility)
        menu.addAction("Quit", QApplication.instance().quit)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.setToolTip("NBA Scoreboard")
        self.tray_icon.setVisible(True)
        self.tray_icon.show()

    @staticmethod
    def _resolve_tray_icon() -> QIcon:
        repo_root = Path(__file__).resolve().parents[3]
        icon_path = repo_root / "src" / "simple_circle_lakers_000.png"
        if icon_path.exists():
            return QIcon(str(icon_path))
        icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)
        if not icon.isNull():
            return icon
        px = QPixmap(64, 64)
        px.fill(QColor("#1e88e5"))
        return QIcon(px)

    def _register_hotkey(self) -> None:
        try:
            keyboard.add_hotkey(
                self.hotkey, lambda: self.toggle_visibility_signal.emit()
            )
            log.info("Registered hotkey: %s", self.hotkey)
        except Exception:  # noqa: BLE001
            log.warning("Failed to register hotkey %s", self.hotkey)

    def _unregister_hotkey(self) -> None:
        try:
            keyboard.remove_hotkey(self.hotkey)
        except Exception:
            pass

    def _toggle_visibility(self) -> None:
        if self.isVisible() and not self.isMinimized():
            if self._detail_window and self._detail_window.isVisible():
                self._detail_window.hide()
            self.hide()
            if self.tray_icon:
                self.tray_icon.setIcon(self._resolve_tray_icon())
                self.tray_icon.setVisible(True)
                self.tray_icon.show()
        else:
            self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()
            if self._detail_window and self._detail_window._current_person_id:
                self._detail_window.follow_ref_window()
                self._detail_window.show()
                self._detail_window.raise_()
        self._apply_topmost()

    def changeEvent(self, event):  # noqa: N802
        if event.type() == QEvent.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                event.ignore()
                if self._detail_window and self._detail_window.isVisible():
                    self._detail_window.hide()
                self.hide()
                if self.tray_icon:
                    self.tray_icon.setVisible(True)
                    self.tray_icon.show()
                return
        super().changeEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self._unregister_hotkey()
        if self._detail_window:
            self._detail_window.close()
            self._detail_window = None
        if self.tray_icon:
            self.tray_icon.hide()
        self.timer.stop()
        self.worker_thread.quit()
        self.worker_thread.wait(300)
        super().closeEvent(event)

    def _quit_fast(self) -> None:
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

    # ── Utility ───────────────────────────────────────────────

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
            beijing = utc_time.astimezone(timezone(timedelta(hours=8)))
            return beijing.strftime("%H:%M")
        except ValueError:
            return "--:--"


def run_app() -> None:
    logging.basicConfig(level=logging.INFO)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(ScoreboardWindow._resolve_tray_icon())
    win = ScoreboardWindow()
    win.show()
    app.exec()


__all__ = ["ScoreboardWindow", "run_app"]
