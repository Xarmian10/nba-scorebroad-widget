from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from nba_api.live.nba.endpoints.scoreboard import ScoreBoard
from nba_api.live.nba.endpoints.boxscore import BoxScore
from nba_api.stats.endpoints.boxscoretraditionalv3 import BoxScoreTraditionalV3
from nba_api.stats.endpoints.boxscoretraditionalv2 import BoxScoreTraditionalV2
from nba_api.live.nba.endpoints.playbyplay import PlayByPlay

from app.models import (
    GameDiff,
    GameState,
    GameStatus,
    ScoreDelta,
    ScoreboardSnapshot,
    TeamState,
)

log = logging.getLogger(__name__)


class ScoreboardService:
    """
    负责从 nba_api 拉取当天比分，并给出与上一帧的得分差，用于触发动画。
    """

    def __init__(self, proxy: Optional[str] = None, headers: Optional[dict] = None, timeout: int = 15):
        self.proxy = proxy
        # 默认浏览器 UA，降低被限流概率
        self.headers = headers or {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.8",
            "Origin": "https://www.nba.com",
            "Referer": "https://www.nba.com/",
        }
        self.timeout = timeout
        self._last_games: Dict[str, GameState] = {}
        self._last_shot_clock_error_at: Optional[datetime] = None

    def fetch_today(self) -> ScoreboardSnapshot:
        """
        拉取当天 scoreboard 数据并解析。
        """
        sb = ScoreBoard(proxy=self.proxy, headers=self.headers, timeout=self.timeout)
        data_sets = sb.nba_response.get_dict()
        game_date = data_sets.get("scoreboard", {}).get("gameDate") or ""
        games_raw = data_sets.get("scoreboard", {}).get("games", []) or []
        games = [self._parse_game(g) for g in games_raw]
        snapshot = ScoreboardSnapshot(game_date=game_date, games=games)
        self._update_cache(games)
        return snapshot

    def fetch_shot_clock(self, game_id: Optional[str]) -> str:
        if not game_id:
            return "--"
        try:
            pb = PlayByPlay(game_id=game_id, proxy=self.proxy, headers=self.headers, timeout=self.timeout)
            actions = pb.actions.get_dict() if pb.actions else []
            if not actions:
                return "--"

            current_possession = None
            possession_start = None
            for action in reversed(actions):
                possession = action.get("possession")
                if possession is None:
                    continue
                if current_possession is None:
                    current_possession = possession
                    possession_start = action
                    continue
                if possession != current_possession:
                    break
                possession_start = action

            if not possession_start:
                return "--"

            time_actual = possession_start.get("timeActual")
            if not time_actual:
                return "--"

            if time_actual.endswith("Z"):
                time_actual = time_actual.replace("Z", "+00:00")
            start_time = datetime.fromisoformat(time_actual)
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            remaining = max(0, 24 - int(elapsed))
            return f":{remaining:02d}"
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            now = datetime.utcnow()
            if isinstance(exc, ValueError) and "Expecting value" in msg:
                log.debug("Fetch shot clock failed: %s", exc)
            else:
                if not self._last_shot_clock_error_at or (now - self._last_shot_clock_error_at).total_seconds() > 60:
                    log.warning("Fetch shot clock failed: %s", exc)
                    self._last_shot_clock_error_at = now
            return "--"

    def fetch_game_clock(self, game_id: Optional[str]) -> str:
        if not game_id:
            return ""
        try:
            bs = BoxScore(game_id=game_id, proxy=self.proxy, headers=self.headers, timeout=self.timeout)
            data = bs.nba_response.get_dict()
            game = data.get("game", {}) if isinstance(data, dict) else {}
            return str(game.get("gameClock") or "")
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch game clock failed: %s", exc)
            return ""

    def fetch_player_stats(self, game_id: Optional[str], team_tricode: str, is_live: bool) -> list[dict]:
        if not game_id or not team_tricode:
            return []
        try:
            team_tricode = team_tricode.upper()
            if is_live:
                bs = BoxScore(game_id=game_id, proxy=self.proxy, headers=self.headers, timeout=self.timeout)
                data = bs.nba_response.get_dict()
                game = data.get("game", {}) if isinstance(data, dict) else {}
                team = None
                for key in ("homeTeam", "awayTeam"):
                    candidate = game.get(key, {})
                    if candidate.get("teamTricode", "").upper() == team_tricode:
                        team = candidate
                        break
                if not team:
                    return []
                players = team.get("players", []) or []
                results: list[dict] = []
                for player in players:
                    stats = player.get("statistics") or {}
                    name = player.get("name") or f"{player.get('firstName','')} {player.get('familyName','')}".strip()
                    results.append(
                        {
                            "name": name or player.get("nameI", ""),
                            "points": stats.get("points", 0) or 0,
                            "assists": stats.get("assists", 0) or 0,
                            "rebounds": stats.get("reboundsTotal", 0) or 0,
                        }
                    )
                results.sort(key=lambda item: (item["points"], item["assists"], item["rebounds"]), reverse=True)
                return results

            results = self._fetch_traditional_stats_v3(game_id, team_tricode)
            if results:
                return results
            results = self._fetch_traditional_stats_v2(game_id, team_tricode)
            if results:
                return results
            # Fallback to live boxscore for ended games if stats endpoints are empty
            bs = BoxScore(game_id=game_id, proxy=self.proxy, headers=self.headers, timeout=self.timeout)
            data = bs.nba_response.get_dict()
            game = data.get("game", {}) if isinstance(data, dict) else {}
            team = None
            for key in ("homeTeam", "awayTeam"):
                candidate = game.get(key, {})
                if candidate.get("teamTricode", "").upper() == team_tricode:
                    team = candidate
                    break
            if not team:
                return []
            players = team.get("players", []) or []
            results = []
            for player in players:
                stats = player.get("statistics") or {}
                name = player.get("name") or f"{player.get('firstName','')} {player.get('familyName','')}".strip()
                results.append(
                    {
                        "name": name or player.get("nameI", ""),
                        "points": stats.get("points", 0) or 0,
                        "assists": stats.get("assists", 0) or 0,
                        "rebounds": stats.get("reboundsTotal", 0) or 0,
                    }
                )
            results.sort(key=lambda item: (item["points"], item["assists"], item["rebounds"]), reverse=True)
            return results
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch player stats failed: %s", exc)
            return []

    def _fetch_traditional_stats_v3(self, game_id: str, team_tricode: str) -> list[dict]:
        try:
            stats = BoxScoreTraditionalV3(game_id=game_id, proxy=self.proxy, headers=self.headers, timeout=self.timeout)
            player_stats = stats.player_stats.get_dict()
            headers = player_stats.get("headers", [])
            data_rows = player_stats.get("data", [])
            if not headers or not data_rows:
                return []
            idx = {name: i for i, name in enumerate(headers)}
            team_idx = idx.get("teamTricode")
            name_idx = idx.get("nameI")
            first_idx = idx.get("firstName")
            last_idx = idx.get("familyName")
            if team_idx is None or name_idx is None:
                return []
            results: list[dict] = []
            for row in data_rows:
                if row[team_idx] != team_tricode:
                    continue
                name = row[name_idx] or f"{row[first_idx]} {row[last_idx]}".strip()
                results.append(
                    {
                        "name": name,
                        "points": row[idx.get("points")] if idx.get("points") is not None else 0,
                        "assists": row[idx.get("assists")] if idx.get("assists") is not None else 0,
                        "rebounds": row[idx.get("reboundsTotal")] if idx.get("reboundsTotal") is not None else 0,
                    }
                )
            results.sort(key=lambda item: (item["points"], item["assists"], item["rebounds"]), reverse=True)
            return results
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch player stats v3 failed: %s", exc)
            return []

    def _fetch_traditional_stats_v2(self, game_id: str, team_tricode: str) -> list[dict]:
        try:
            stats = BoxScoreTraditionalV2(game_id=game_id, proxy=self.proxy, headers=self.headers, timeout=self.timeout)
            player_stats = stats.player_stats.get_dict()
            headers = player_stats.get("headers", [])
            data_rows = player_stats.get("data", [])
            if not headers or not data_rows:
                return []
            idx = {name: i for i, name in enumerate(headers)}
            team_idx = idx.get("TEAM_ABBREVIATION")
            name_idx = idx.get("PLAYER_NAME")
            if team_idx is None or name_idx is None:
                return []
            results: list[dict] = []
            for row in data_rows:
                if row[team_idx] != team_tricode:
                    continue
                results.append(
                    {
                        "name": row[name_idx],
                        "points": row[idx.get("PTS")] if idx.get("PTS") is not None else 0,
                        "assists": row[idx.get("AST")] if idx.get("AST") is not None else 0,
                        "rebounds": row[idx.get("REB")] if idx.get("REB") is not None else 0,
                    }
                )
            results.sort(key=lambda item: (item["points"], item["assists"], item["rebounds"]), reverse=True)
            return results
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch player stats v2 failed: %s", exc)
            return []

    def fetch_last_timeout_team(self, game_id: Optional[str], game_clock: str) -> str:
        if not game_id:
            return ""
        if not game_clock:
            return ""
        try:
            pb = PlayByPlay(game_id=game_id, proxy=self.proxy, headers=self.headers, timeout=self.timeout)
            actions = pb.actions.get_dict() if pb.actions else []
            if not actions:
                return ""
            for action in reversed(actions):
                description = (action.get("description") or "").upper()
                action_type = (action.get("actionType") or "").upper()
                if "TIMEOUT" in description or action_type == "TIMEOUT":
                    action_clock = (action.get("clock") or "").strip()
                    if action_clock != game_clock:
                        return ""
                    tricode = action.get("teamTricode") or ""
                    return str(tricode).upper()
            return ""
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch timeout team failed: %s", exc)
            return ""

    def diff_since_last(self, current: Iterable[GameState]) -> List[GameDiff]:
        """
        基于缓存的上一帧，给出本帧的比分差。
        """
        diffs: List[GameDiff] = []
        for game in current:
            prev = self._last_games.get(game.game_id)
            delta = self._score_delta(prev, game)
            diffs.append(GameDiff(game=game, delta=delta))
        self._update_cache(current)
        return diffs

    def _update_cache(self, games: Iterable[GameState]) -> None:
        self._last_games = {g.game_id: g for g in games}

    @staticmethod
    def _parse_team(data: dict) -> TeamState:
        return TeamState(
            team_id=data.get("teamId", 0),
            tricode=data.get("teamTricode", ""),
            name=data.get("teamName", ""),
            city=data.get("teamCity", ""),
            score=int(data.get("score", 0) or 0),
            wins=int(data.get("wins", 0) or 0),
            losses=int(data.get("losses", 0) or 0),
            in_bonus=data.get("inBonus"),
            timeouts_remaining=int(data.get("timeoutsRemaining", 0) or 0),
            periods=data.get("periods", []) or [],
        )

    def _parse_game(self, data: dict) -> GameState:
        return GameState(
            game_id=data.get("gameId", ""),
            game_code=data.get("gameCode", ""),
            status=GameStatus.from_int(int(data.get("gameStatus", 0) or 0)),
            status_text=data.get("gameStatusText", ""),
            period=int(data.get("period", 0) or 0),
            game_clock=data.get("gameClock", ""),
            regulation_periods=int(data.get("regulationPeriods", 0) or 0),
            game_time_utc=data.get("gameTimeUTC"),
            game_et=data.get("gameEt"),
            series_game_number=data.get("seriesGameNumber"),
            series_text=data.get("seriesText"),
            home=self._parse_team(data.get("homeTeam", {})),
            away=self._parse_team(data.get("awayTeam", {})),
            pb_odds=data.get("pbOdds"),
            last_update_utc=datetime.utcnow(),
        )

    @staticmethod
    def _score_delta(prev: Optional[GameState], curr: GameState) -> ScoreDelta:
        if not prev:
            return ScoreDelta()
        return ScoreDelta(
            home_delta=curr.home.score - prev.home.score,
            away_delta=curr.away.score - prev.away.score,
        )


