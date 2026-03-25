from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

import requests as _requests

from nba_api.live.nba.endpoints.scoreboard import ScoreBoard
from nba_api.live.nba.endpoints.boxscore import BoxScore
from nba_api.stats.endpoints.boxscoretraditionalv3 import BoxScoreTraditionalV3
from nba_api.stats.endpoints.boxscoretraditionalv2 import BoxScoreTraditionalV2
from nba_api.stats.endpoints.commonteamroster import CommonTeamRoster
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

    def fetch_player_stats(
        self,
        game_id: Optional[str],
        team_tricode: str,
        is_live: bool,
        team_id: int = 0,
    ) -> list[dict]:
        if not game_id or not team_tricode:
            return []
        try:
            team_tricode = team_tricode.upper()
            if is_live:
                results = self._fetch_live_player_stats(game_id, team_tricode)
                if results:
                    return results
            else:
                for fn in (
                    lambda: self._fetch_traditional_stats_v3(game_id, team_tricode),
                    lambda: self._fetch_traditional_stats_v2(game_id, team_tricode),
                    lambda: self._fetch_live_player_stats(game_id, team_tricode),
                ):
                    results = fn()
                    if results:
                        return results
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch player stats failed: %s", exc)

        return self._fetch_roster_fallback(game_id or "", team_id, team_tricode)

    def _fetch_live_player_stats(self, game_id: str, team_tricode: str) -> list[dict]:
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
        team_id = team.get("teamId", 0)
        players = team.get("players", []) or []
        results: list[dict] = []
        for player in players:
            stats = player.get("statistics") or {}
            name = player.get("name") or f"{player.get('firstName','')} {player.get('familyName','')}".strip()
            results.append({
                "name": name or player.get("nameI", ""),
                "personId": player.get("personId", 0),
                "teamId": team_id,
                "jerseyNum": str(player.get("jerseyNum", "")),
                "position": player.get("position", ""),
                "points": stats.get("points", 0) or 0,
                "assists": stats.get("assists", 0) or 0,
                "rebounds": stats.get("reboundsTotal", 0) or 0,
            })
        results.sort(key=lambda item: (item["points"], item["assists"], item["rebounds"]), reverse=True)
        return results

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
                results.append({
                    "name": name,
                    "personId": row[idx["personId"]] if "personId" in idx else 0,
                    "teamId": row[idx["teamId"]] if "teamId" in idx else 0,
                    "jerseyNum": str(row[idx["jerseyNum"]]) if "jerseyNum" in idx else "",
                    "position": row[idx["position"]] if "position" in idx else "",
                    "points": row[idx["points"]] if "points" in idx else 0,
                    "assists": row[idx["assists"]] if "assists" in idx else 0,
                    "rebounds": row[idx["reboundsTotal"]] if "reboundsTotal" in idx else 0,
                })
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
                results.append({
                    "name": row[name_idx],
                    "personId": row[idx["PLAYER_ID"]] if "PLAYER_ID" in idx else 0,
                    "teamId": row[idx["TEAM_ID"]] if "TEAM_ID" in idx else 0,
                    "jerseyNum": "",
                    "position": row[idx.get("START_POSITION", "")] if "START_POSITION" in idx else "",
                    "points": row[idx["PTS"]] if "PTS" in idx else 0,
                    "assists": row[idx["AST"]] if "AST" in idx else 0,
                    "rebounds": row[idx["REB"]] if "REB" in idx else 0,
                })
            results.sort(key=lambda item: (item["points"], item["assists"], item["rebounds"]), reverse=True)
            return results
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch player stats v2 failed: %s", exc)
            return []

    def _fetch_roster_fallback(self, game_id: str, team_id: int, team_tricode: str) -> list[dict]:
        """Multi-level fallback to get team roster with zeroed stats."""
        result = self._fetch_roster_via_cdn(game_id, team_tricode)
        if result:
            return result
        result = self._fetch_roster_via_stats(team_id, team_tricode)
        if result:
            return result
        return []

    def _fetch_roster_via_cdn(self, game_id: str, team_tricode: str) -> list[dict]:
        """Direct HTTP request to NBA CDN boxscore to extract roster."""
        try:
            url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
            resp = _requests.get(url, headers=self.headers, timeout=self.timeout)
            if not resp.ok:
                return []
            data = resp.json()
            game = data.get("game", {})
            for key in ("homeTeam", "awayTeam"):
                team = game.get(key, {})
                if team.get("teamTricode", "").upper() != team_tricode.upper():
                    continue
                tid = team.get("teamId", 0)
                players = team.get("players", []) or []
                if not players:
                    continue
                results: list[dict] = []
                for p in players:
                    stats = p.get("statistics") or {}
                    name = (
                        p.get("name")
                        or f"{p.get('firstName', '')} {p.get('familyName', '')}".strip()
                        or p.get("nameI", "")
                    )
                    results.append({
                        "name": name,
                        "personId": p.get("personId", 0),
                        "teamId": tid,
                        "jerseyNum": str(p.get("jerseyNum", "")),
                        "position": p.get("position", ""),
                        "points": stats.get("points", 0) or 0,
                        "assists": stats.get("assists", 0) or 0,
                        "rebounds": stats.get("reboundsTotal", 0) or 0,
                    })
                results.sort(
                    key=lambda item: (item["points"], item["assists"], item["rebounds"]),
                    reverse=True,
                )
                return results
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch roster via CDN failed: %s", exc)
        return []

    def _fetch_roster_via_stats(self, team_id: int, team_tricode: str) -> list[dict]:
        """Try CommonTeamRoster from stats.nba.com (may be rate-limited)."""
        try:
            season = self._current_season()
            roster = CommonTeamRoster(
                team_id=team_id,
                season=season,
                proxy=self.proxy,
                headers=self.headers,
                timeout=self.timeout,
            )
            rows = roster.common_team_roster.get_dict()
            hdrs = rows.get("headers", [])
            data = rows.get("data", [])
            if not hdrs or not data:
                return []
            idx = {name: i for i, name in enumerate(hdrs)}
            name_i = idx.get("PLAYER")
            if name_i is None:
                return []
            pid_i = idx.get("PLAYER_ID")
            num_i = idx.get("NUM")
            pos_i = idx.get("POSITION")
            results: list[dict] = []
            for row in data:
                results.append({
                    "name": row[name_i] or "",
                    "personId": row[pid_i] if pid_i is not None else 0,
                    "teamId": team_id,
                    "jerseyNum": str(row[num_i]) if num_i is not None else "",
                    "position": str(row[pos_i]) if pos_i is not None else "",
                    "points": 0,
                    "assists": 0,
                    "rebounds": 0,
                })
            return results
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch roster via stats.nba.com failed: %s", exc)
            return []

    @staticmethod
    def _current_season() -> str:
        now = datetime.now()
        year = now.year if now.month >= 10 else now.year - 1
        return f"{year}-{(year + 1) % 100:02d}"

    def fetch_player_advanced_stats(self, game_id: str, player_id: int) -> dict:
        """Compute advanced stats from the live BoxScore endpoint."""
        if not game_id or not player_id:
            return {}
        try:
            bs = BoxScore(game_id=game_id, proxy=self.proxy, headers=self.headers, timeout=self.timeout)
            data = bs.nba_response.get_dict()
            game = data.get("game", {}) if isinstance(data, dict) else {}
            for key in ("homeTeam", "awayTeam"):
                team = game.get(key, {})
                for player in team.get("players", []):
                    if player.get("personId") != player_id:
                        continue
                    s = player.get("statistics") or {}
                    pts = s.get("points", 0) or 0
                    fga = s.get("fieldGoalsAttempted", 0) or 0
                    fgm = s.get("fieldGoalsMade", 0) or 0
                    fta = s.get("freeThrowsAttempted", 0) or 0
                    ftm = s.get("freeThrowsMade", 0) or 0
                    tpm = s.get("threePointersMade", 0) or 0
                    tpa = s.get("threePointersAttempted", 0) or 0
                    denom = 2 * (fga + 0.44 * fta)
                    ts_pct = pts / denom if denom > 0 else 0.0
                    efg_pct = (fgm + 0.5 * tpm) / fga if fga > 0 else 0.0
                    raw_min = s.get("minutes") or s.get("minutesCalculated") or ""
                    return {
                        "ts_pct": ts_pct,
                        "efg_pct": efg_pct,
                        "fg_pct": s.get("fieldGoalsPercentage", 0) or 0,
                        "tp_pct": s.get("threePointersPercentage", 0) or 0,
                        "ft_pct": s.get("freeThrowsPercentage", 0) or 0,
                        "plus_minus": s.get("plusMinusPoints", 0) or 0,
                        "minutes": raw_min,
                        "turnovers": s.get("turnovers", 0) or 0,
                        "fgm": fgm, "fga": fga,
                        "tpm": tpm, "tpa": tpa,
                        "ftm": ftm, "fta": fta,
                    }
            return {}
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch advanced stats failed: %s", exc)
            return {}

    def fetch_shot_chart(self, game_id: str, player_id: int, team_id: int) -> list[dict]:
        """Extract shot locations from live PlayByPlay, filtered by player.

        Free throws are excluded since they have no location data.
        """
        if not game_id or not player_id:
            return []
        try:
            pb = PlayByPlay(game_id=game_id, proxy=self.proxy, headers=self.headers, timeout=self.timeout)
            actions = pb.actions.get_dict() if pb.actions else []
            results = []
            for a in actions:
                if not a.get("shotResult") or a.get("personId") != player_id:
                    continue
                action_type = (a.get("actionType") or "").lower()
                if "freethrow" in action_type or "free throw" in action_type:
                    continue
                x = a.get("xLegacy")
                y = a.get("yLegacy")
                if x is None or y is None:
                    continue
                results.append({
                    "x": int(x),
                    "y": int(y),
                    "made": a.get("shotResult") == "Made",
                    "type": a.get("actionType", ""),
                    "zone": a.get("area", ""),
                    "distance": a.get("shotDistance", 0),
                    "action": a.get("subType", ""),
                })
            return results
        except Exception as exc:  # noqa: BLE001
            log.debug("Fetch shot chart failed: %s", exc)
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


