from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot

from app.models import GameDiff, GameState, ScoreDelta
from app.services import ScoreboardService

log = logging.getLogger(__name__)


class PollWorker(QObject):
    """
    后台轮询 worker，避免在 UI 线程阻塞。
    """

    data_ready = Signal(list, str, str, str, str, list, str)
    error = Signal(str)

    def __init__(
        self,
        refresh_ms: int = 8000,
        timeout: int = 10,
        retries: int = 2,
        proxy: str | None = None,
        headers: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = ScoreboardService(timeout=timeout, proxy=proxy, headers=headers)
        self.refresh_ms = refresh_ms
        self.retries = max(0, retries)
        self._selected_game_id: str = ""
        self._last_shot_clock_fetch = 0.0
        self._last_timeout_fetch = 0.0
        self._last_shot_clock_value = "--"
        self._last_timeout_team = ""
        self._last_game_clock_fetch = 0.0
        self._last_game_clock_value = ""
        self._last_poll_at = 0.0
        self._seq = 0
        self._last_applied_seq = 0
        self._last_games: Dict[str, GameState] = {}
        self._player_stats_team = ""
        self._last_player_stats_fetch = 0.0
        self._last_player_stats: list[dict] = []
        self._player_stats_cache: Dict[str, list[dict]] = {}
        self._player_stats_game_id = ""
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=2)

    @Slot(str)
    def set_selected_game_id(self, game_id: str) -> None:
        self._selected_game_id = game_id or ""
        self._player_stats_game_id = self._selected_game_id or self._player_stats_game_id

    @Slot(str)
    def set_player_stats_team(self, tricode: str) -> None:
        self._player_stats_team = (tricode or "").upper()
        self._last_player_stats_fetch = 0.0
        cache_key = f"{self._selected_game_id}:{self._player_stats_team}"
        self._last_player_stats = self._player_stats_cache.get(cache_key, [])

    @Slot()
    def poll_once(self) -> None:
        now = time.monotonic()
        if now - self._last_poll_at < 0.5:
            return
        self._last_poll_at = now
        self._seq += 1
        seq = self._seq
        future = self._executor.submit(self._poll_task, seq, self._selected_game_id)
        future.add_done_callback(self._on_poll_done)

    def _poll_task(
        self, seq: int, game_id: str
    ) -> Tuple[int, Optional[ScoreboardService], Optional[str], Optional[str], Optional[str], list, str]:
        try:
            service = ScoreboardService(timeout=self.service.timeout, proxy=self.service.proxy, headers=self.service.headers)
            snapshot = service.fetch_today()
            shot_clock = "--"
            timeout_team = self._last_timeout_team
            game_clock = None
            player_team = self._player_stats_team
            cache_key = f"{game_id}:{player_team}"
            player_stats = self._player_stats_cache.get(cache_key, self._last_player_stats)
            if game_id:
                game = next((g for g in snapshot.games if g.game_id == game_id), None)
                if game:
                    now = time.monotonic()
                    if game.is_live:
                        if now - self._last_game_clock_fetch >= 0.5:
                            game_clock = service.fetch_game_clock(game_id)
                            self._last_game_clock_fetch = now
                            self._last_game_clock_value = game_clock or ""
                        game_clock = self._last_game_clock_value or game_clock or game.game_clock
                        # 禁用非直接来源的 SHOT 数据
                        if now - self._last_timeout_fetch >= 0.5:
                            timeout_team = service.fetch_last_timeout_team(game_id, game_clock or "")
                            self._last_timeout_fetch = now
                            self._last_timeout_team = timeout_team
                        if game_clock:
                            game.game_clock = game_clock
                    if player_team:
                        tricodes = [t.strip().upper() for t in player_team.split(",") if t.strip()]
                        should_fetch = now - self._last_player_stats_fetch >= 10.0
                        all_stats: list[dict] = []
                        fetched_any = False
                        tc_to_tid = {
                            game.home.tricode.upper(): game.home.team_id,
                            game.away.tricode.upper(): game.away.team_id,
                        }
                        for tc in tricodes:
                            tc_cache_key = f"{game_id}:{tc}"
                            if not game.is_live and tc_cache_key in self._player_stats_cache:
                                tc_stats = self._player_stats_cache[tc_cache_key]
                            elif should_fetch:
                                tid = tc_to_tid.get(tc, 0)
                                tc_stats = service.fetch_player_stats(
                                    game_id, tc, is_live=game.is_live, team_id=tid,
                                )
                                fetched_any = True
                                if tc_stats:
                                    self._player_stats_cache[tc_cache_key] = tc_stats
                            else:
                                tc_stats = self._player_stats_cache.get(tc_cache_key, [])
                            for s in tc_stats:
                                s["team"] = tc
                            all_stats.extend(tc_stats)
                        if fetched_any:
                            self._last_player_stats_fetch = now
                        player_stats = all_stats
            return seq, snapshot, shot_clock, game_id, timeout_team, player_stats, player_team
        except Exception as exc:  # noqa: BLE001
            log.warning("Poll worker failed attempt: %s", exc)
            return seq, None, None, None, None, [], ""

    def _on_poll_done(self, future) -> None:
        try:
            seq, snapshot, shot_clock, game_id, timeout_team, player_stats, player_team = future.result()
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        if not snapshot:
            return
        if seq < self._last_applied_seq:
            return
        self._last_applied_seq = seq
        with self._lock:
            diffs = self._diff_since_last(snapshot.games)
        self.data_ready.emit(
            diffs,
            snapshot.game_date,
            shot_clock or "--",
            game_id or "",
            timeout_team or "",
            player_stats or [],
            player_team or "",
        )

    def _diff_since_last(self, current: List[GameState]) -> List[GameDiff]:
        diffs: List[GameDiff] = []
        for game in current:
            prev = self._last_games.get(game.game_id)
            delta = self._score_delta(prev, game)
            diffs.append(GameDiff(game=game, delta=delta))
        self._last_games = {g.game_id: g for g in current}
        return diffs

    @staticmethod
    def _score_delta(prev: Optional[GameState], curr: GameState) -> ScoreDelta:
        if not prev:
            return ScoreDelta()
        return ScoreDelta(
            home_delta=curr.home.score - prev.home.score,
            away_delta=curr.away.score - prev.away.score,
        )

