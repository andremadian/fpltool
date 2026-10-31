"""Live FPL API client for the weekly brief (stands alone; no cross-engine imports)."""
import random
import time
from typing import Any

import requests

from brief.types import Player

BASE_URL = "https://fantasy.premierleague.com/api"
REQUEST_TIMEOUT_SECONDS = 30
SLEEP_RANGE = (0.5, 1.0)
POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _sleep() -> None:
    """Pause between per-entry calls; tests replace this to avoid sleeping."""
    time.sleep(random.uniform(*SLEEP_RANGE))


def _get(path: str) -> requests.Response:
    """GET an FPL API path and raise on non-2xx."""
    response = requests.get(f"{BASE_URL}/{path}", timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response


def fetch_bootstrap() -> dict:
    """Fetch bootstrap-static."""
    return _get("bootstrap-static/").json()


def fetch_entry_history(entry_id: int) -> dict:
    """Fetch an entry's season history (current GWs, past seasons, chips)."""
    data = _get(f"entry/{entry_id}/history/").json()
    _sleep()
    return data


def fetch_entry_transfers(entry_id: int) -> list[dict]:
    """Fetch every transfer an entry has made this season."""
    data = _get(f"entry/{entry_id}/transfers/").json()
    _sleep()
    return data


def fetch_entry_picks(entry_id: int, gw: int) -> dict | None:
    """Fetch an entry's picks for a GW; None if the API returns 404."""
    response = requests.get(
        f"{BASE_URL}/entry/{entry_id}/event/{gw}/picks/",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    _sleep()
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def fetch_league_standings(league_id: int) -> list[dict]:
    """Paginate classic-league standings, keeping entry/entry_name/player_name/rank/total."""
    keep = ("entry", "entry_name", "player_name", "rank", "total")
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        standings = _get(
            f"leagues-classic/{league_id}/standings/?page_standings={page}"
        ).json().get("standings", {})
        rows.extend({k: item.get(k) for k in keep} for item in standings.get("results", []))
        if not standings.get("has_next"):
            break
        page += 1
        _sleep()
    return rows


def players_from_bootstrap(
    bootstrap: dict, season_players: set[int] | None = None
) -> dict[int, Player]:
    """Build Player records from bootstrap, optionally restricted to a set of ids."""
    short = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    players: dict[int, Player] = {}
    for el in bootstrap["elements"]:
        if season_players is not None and el["id"] not in season_players:
            continue
        players[el["id"]] = Player(
            id=el["id"],
            name=el["web_name"],
            team_id=el["team"],
            team_short=short.get(el["team"], ""),
            pos=POSITIONS[el["element_type"]],
            price=el["now_cost"] / 10,
            status=el.get("status") or "a",
            chance=el.get("chance_of_playing_next_round"),
            news=el.get("news") or "",
        )
    return players
