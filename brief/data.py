"""Supabase loaders for the weekly brief."""
from datetime import date, datetime
from typing import Any

from brief.types import FlagRow, Fixture, Gameweek, HistoryRow

PAGE_SIZE = 1000


def _fetch_all(sb: Any, table: str, columns: str, season: str, order_cols: list[str]) -> list[dict]:
    """Read every row of a season's table in pages of 1000, in a stable order."""
    rows: list[dict] = []
    start = 0
    while True:
        query = sb.table(table).select(columns).eq("season", season)
        for col in order_cols:
            query = query.order(col)
        page = query.range(start, start + PAGE_SIZE - 1).execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def _f(value: Any) -> float:
    """Coerce a numeric (Decimal/str/None) to float, None -> 0.0."""
    return float(value) if value is not None else 0.0


def _i(value: Any) -> int:
    """Coerce a numeric to int, None -> 0."""
    return int(value) if value is not None else 0


def load_history(sb: Any, season: str) -> list[HistoryRow]:
    """Load player_history for a season, ordered by player_id, gw."""
    cols = ("player_id,gw,minutes,total_points,goals,assists,clean_sheets,"
            "xg,xa,xgi,bps,cbit,price,xgc")
    return [
        HistoryRow(
            player_id=r["player_id"], gw=r["gw"], minutes=_i(r.get("minutes")),
            total_points=_i(r.get("total_points")), xg=_f(r.get("xg")),
            xa=_f(r.get("xa")), xgc=_f(r.get("xgc")), bps=_i(r.get("bps")),
            cbit=_i(r.get("cbit")), goals=_i(r.get("goals")),
            assists=_i(r.get("assists")), clean_sheets=_i(r.get("clean_sheets")),
            price=_f(r.get("price")),
        )
        for r in _fetch_all(sb, "player_history", cols, season, ["player_id", "gw"])
    ]


def load_fixtures(sb: Any, season: str) -> list[Fixture]:
    """Load fixtures as one Fixture per side, skipping unscheduled (null GW) ones."""
    out: list[Fixture] = []
    for r in _fetch_all(sb, "fixtures", "id,gw,home_team_id,away_team_id", season, ["id"]):
        if r["gw"] is None:
            continue
        out.append(Fixture(r["gw"], r["home_team_id"], r["away_team_id"], True))
        out.append(Fixture(r["gw"], r["away_team_id"], r["home_team_id"], False))
    return out


def load_gameweeks(sb: Any, season: str) -> list[Gameweek]:
    """Load gameweek deadlines for a season."""
    return [
        Gameweek(r["gw"], datetime.fromisoformat(r["deadline_time"].replace("Z", "+00:00")))
        for r in _fetch_all(sb, "gameweeks", "gw,deadline_time", season, ["gw"])
    ]


def load_flags(sb: Any, season: str) -> list[FlagRow]:
    """Load daily availability flags, ordered by player_id, as_of_date."""
    return [
        FlagRow(
            r["player_id"], date.fromisoformat(r["as_of_date"]), r.get("status") or "a",
            r.get("chance_of_playing_next_round"),
        )
        for r in _fetch_all(
            sb, "player_daily", "player_id,as_of_date,status,chance_of_playing_next_round",
            season, ["player_id", "as_of_date"],
        )
    ]


def load_tracked_league(sb: Any) -> tuple[int, int]:
    """Return (league_id, my_fpl_team_id) from the first tracked_leagues row."""
    rows = sb.table("tracked_leagues").select("league_id,my_fpl_team_id").limit(1).execute().data
    if not rows:
        raise RuntimeError("tracked_leagues is empty")
    return rows[0]["league_id"], rows[0]["my_fpl_team_id"]
