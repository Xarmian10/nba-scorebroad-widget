from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class GameStatus(Enum):
    """NBA live scoreboard game status codes."""

    NOT_STARTED = 1
    IN_PROGRESS = 2
    FINAL = 3
    UNKNOWN = 0

    @classmethod
    def from_int(cls, value: int) -> "GameStatus":
        return {
            1: cls.NOT_STARTED,
            2: cls.IN_PROGRESS,
            3: cls.FINAL,
        }.get(value, cls.UNKNOWN)


@dataclass(slots=True)
class TeamState:
    team_id: int
    tricode: str
    name: str
    city: str
    score: int
    wins: int
    losses: int
    in_bonus: Optional[bool]
    timeouts_remaining: int
    periods: List[Dict[str, int]] = field(default_factory=list)


@dataclass(slots=True)
class GameState:
    game_id: str
    game_code: str
    status: GameStatus
    status_text: str
    period: int
    game_clock: str
    regulation_periods: int
    game_time_utc: Optional[str]
    game_et: Optional[str]
    series_game_number: Optional[str]
    series_text: Optional[str]
    home: TeamState
    away: TeamState
    pb_odds: Optional[Dict] = None
    last_update_utc: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_live(self) -> bool:
        return self.status == GameStatus.IN_PROGRESS

    @property
    def is_final(self) -> bool:
        return self.status == GameStatus.FINAL

    @property
    def clock_display(self) -> str:
        if self.is_final:
            return "Final"
        if self.status == GameStatus.NOT_STARTED:
            return self.status_text or "Scheduled"
        return self.game_clock or self.status_text or "--:--"


@dataclass(slots=True)
class ScoreDelta:
    home_delta: int = 0
    away_delta: int = 0

    def has_change(self) -> bool:
        return bool(self.home_delta or self.away_delta)


@dataclass(slots=True)
class GameDiff:
    game: GameState
    delta: ScoreDelta


@dataclass(slots=True)
class ScoreboardSnapshot:
    game_date: str
    games: List[GameState] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.utcnow)











