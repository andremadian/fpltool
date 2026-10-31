"""Shared immutable record types for the weekly brief."""
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Player:
    """A current-season player with availability."""
    id: int
    name: str
    team_id: int
    team_short: str
    pos: str  # GKP | DEF | MID | FWD
    price: float
    status: str
    chance: int | None
    news: str


@dataclass(frozen=True)
class Fixture:
    """One side of a fixture: `team_id` plays `opp_id` in `gw`."""
    gw: int
    team_id: int
    opp_id: int
    home: bool


@dataclass(frozen=True)
class Gameweek:
    """A gameweek and its transfer deadline."""
    gw: int
    deadline: datetime


@dataclass(frozen=True)
class HistoryRow:
    """One player's totals for one gameweek."""
    player_id: int
    gw: int
    minutes: int
    total_points: int
    xg: float
    xa: float
    xgc: float
    bps: int
    cbit: int
    goals: int
    assists: int
    clean_sheets: int
    price: float


@dataclass(frozen=True)
class FlagRow:
    """A daily availability snapshot for one player."""
    player_id: int
    as_of_date: date
    status: str
    chance: int | None
