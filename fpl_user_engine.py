"""FPL Sniper Phase 2 — user and rivals ingestion pipeline.

Fetches my own FPL squad and the squads of rivals across my tracked
mini-leagues, then upserts them into Supabase. Runs twice weekly via
local cron (Friday 5:30pm + Saturday 10am WIB).

Separate from fpl_engine.py (Phase 1) which ingests global FPL data.
"""

import logging
import os
import random
import time
from typing import Any

import requests
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
PICKS_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/"
ENTRY_HISTORY_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/history/"
STANDINGS_URL = (
    "https://fantasy.premierleague.com/api/leagues-classic/{league_id}/standings/"
    "?page_standings={page}"
)
REQUEST_TIMEOUT_SECONDS = 30
STANDINGS_PAGE_SLEEP_RANGE = (0.1, 0.15)
RIVAL_PICKS_SLEEP_RANGE = (0.1, 0.15)
RIVAL_BATCH_SIZE = 200
RIVAL_PROGRESS_LOG_EVERY = 25


def get_supabase_client() -> Client:
    """Construct a Supabase client using the service-role key from env."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def load_tracked_leagues(supabase: Client) -> list[dict[str, Any]]:
    """Read tracked_leagues config. Empty means user hasn't set up any leagues."""
    response = supabase.table("tracked_leagues").select("*").execute()
    rows = response.data or []
    logger.info("Loaded %d tracked leagues from config", len(rows))
    return rows


def fetch_bootstrap() -> dict[str, Any]:
    """Fetch FPL bootstrap-static (used here only to find the current gameweek)."""
    response = requests.get(BOOTSTRAP_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def determine_current_gw(bootstrap: dict[str, Any]) -> int | None:
    """Find the current gameweek from bootstrap-static events. None if season idle."""
    for event in bootstrap.get("events", []):
        if event.get("is_current"):
            return int(event["id"])
    # Pre-season or between GWs — fall back to the next gameweek if any
    for event in bootstrap.get("events", []):
        if event.get("is_next"):
            logger.info("No current GW; using next GW %d as target", event["id"])
            return int(event["id"])
    return None


def _build_squad_row(
    team_id: int, gw: int, picks_payload: dict[str, Any], history_payload: dict[str, Any],
) -> dict[str, Any]:
    """Translate FPL picks + history responses into a user_team_snapshots row."""
    picks = sorted(picks_payload["picks"], key=lambda p: p["position"])
    player_ids = [p["element"] for p in picks]
    bench_order = [p["element"] for p in picks if p["position"] >= 12]

    captain = next((p for p in picks if p.get("is_captain")), None)
    vice = next((p for p in picks if p.get("is_vice_captain")), None)

    # entry_history is a per-GW list; find the row matching this GW.
    gw_history = next(
        (h for h in history_payload.get("current", []) if h.get("event") == gw),
        {},
    )

    return {
        "fpl_team_id": team_id,
        "gw": gw,
        "player_ids": player_ids,
        "captain_id": captain["element"] if captain else None,
        "vice_captain_id": vice["element"] if vice else None,
        "chip_used": picks_payload.get("active_chip"),
        "bench_order": bench_order,
        "transfers_made": gw_history.get("event_transfers", 0),
        "transfer_cost": gw_history.get("event_transfers_cost", 0),
        "event_points": gw_history.get("points"),
        "event_rank": gw_history.get("rank"),
        "overall_rank": gw_history.get("overall_rank"),
        "bank": gw_history.get("bank", 0) / 10 if gw_history.get("bank") is not None else None,
        "team_value": gw_history.get("value", 0) / 10 if gw_history.get("value") is not None else None,
    }


def fetch_and_write_my_squads(
    leagues: list[dict[str, Any]], gw: int, supabase: Client,
) -> int:
    """For each unique my_fpl_team_id, fetch picks + history and upsert one row."""
    my_team_ids = sorted({row["my_fpl_team_id"] for row in leagues})
    logger.info("Fetching my squad for %d unique team ID(s): %s", len(my_team_ids), my_team_ids)

    written = 0
    for team_id in my_team_ids:
        try:
            picks_resp = requests.get(
                PICKS_URL.format(team_id=team_id, gw=gw),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            picks_resp.raise_for_status()
            picks_payload = picks_resp.json()

            history_resp = requests.get(
                ENTRY_HISTORY_URL.format(team_id=team_id),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            history_resp.raise_for_status()
            history_payload = history_resp.json()

            row = _build_squad_row(team_id, gw, picks_payload, history_payload)
            supabase.table("user_team_snapshots").upsert(row).execute()
            logger.info(
                "Upserted my squad: team_id=%d gw=%d points=%s rank=%s",
                team_id, gw, row["event_points"], row["overall_rank"],
            )
            written += 1
        except Exception as exc:
            logger.error("Failed to fetch/write my squad for team_id %d: %s", team_id, exc)
            continue

    return written


def fetch_league_standings(league_id: int, my_team_id: int) -> list[dict[str, Any]]:
    """Paginate the classic-league standings endpoint, returning rival rows only."""
    rivals: list[dict[str, Any]] = []
    page = 1
    while True:
        response = requests.get(
            STANDINGS_URL.format(league_id=league_id, page=page),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        standings = payload.get("standings", {})
        results = standings.get("results", [])

        for entry in results:
            if entry["entry"] == my_team_id:
                continue
            rivals.append({
                "league_id": league_id,
                "rival_fpl_team_id": entry["entry"],
                "rival_name": entry.get("entry_name"),
                "rival_player_name": entry.get("player_name"),
                "total_points": entry.get("total"),
                "league_rank": entry.get("rank"),
                "last_rank": entry.get("last_rank"),
            })

        if not standings.get("has_next"):
            break
        page += 1
        time.sleep(random.uniform(*STANDINGS_PAGE_SLEEP_RANGE))

    return rivals


def write_league_standings(
    leagues: list[dict[str, Any]], supabase: Client,
) -> int:
    """Fetch and upsert league_rivals for every tracked league. Returns total rows."""
    total_written = 0
    for league in leagues:
        league_id = league["league_id"]
        my_team_id = league["my_fpl_team_id"]
        try:
            rivals = fetch_league_standings(league_id, my_team_id)
        except Exception as exc:
            logger.error("Failed to fetch standings for league %d: %s", league_id, exc)
            continue

        if not rivals:
            logger.warning("League %d returned 0 rivals (excluding self)", league_id)
            continue

        supabase.table("league_rivals").upsert(rivals).execute()
        logger.info(
            "Upserted %d rivals for league %d (%s)",
            len(rivals), league_id, league.get("league_name") or "unnamed",
        )
        total_written += len(rivals)

    return total_written


def load_unique_rival_ids(supabase: Client) -> list[int]:
    """Return deduplicated rival team IDs across all tracked leagues."""
    response = supabase.table("league_rivals").select("rival_fpl_team_id").execute()
    rows = response.data or []
    return sorted({r["rival_fpl_team_id"] for r in rows})


def _build_rival_row(
    rival_id: int, gw: int, picks_payload: dict[str, Any],
) -> dict[str, Any]:
    """Translate FPL picks response into a rival_team_snapshots row."""
    picks = sorted(picks_payload["picks"], key=lambda p: p["position"])
    player_ids = [p["element"] for p in picks]
    bench_order = [p["element"] for p in picks if p["position"] >= 12]
    captain = next((p for p in picks if p.get("is_captain")), None)
    vice = next((p for p in picks if p.get("is_vice_captain")), None)
    entry_history = picks_payload.get("entry_history") or {}

    return {
        "rival_fpl_team_id": rival_id,
        "gw": gw,
        "player_ids": player_ids,
        "captain_id": captain["element"] if captain else None,
        "vice_captain_id": vice["element"] if vice else None,
        "chip_used": picks_payload.get("active_chip"),
        "bench_order": bench_order,
        "transfers_made": entry_history.get("event_transfers", 0),
        "transfer_cost": entry_history.get("event_transfers_cost", 0),
        "event_points": entry_history.get("points"),
    }


def fetch_rival_squads(
    rival_ids: list[int], gw: int,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch every rival's picks for the GW. Returns (rows, skipped_count).

    Skips rivals where the API returns 404 or stale (pre-deadline) data —
    common pattern before the GW deadline locks. Each rival wrapped in
    try/except so one bad request doesn't kill the run.
    """
    rows: list[dict[str, Any]] = []
    skipped = 0
    total = len(rival_ids)
    logger.info("Fetching picks for %d unique rivals at GW %d", total, gw)

    for idx, rival_id in enumerate(rival_ids, start=1):
        try:
            response = requests.get(
                PICKS_URL.format(team_id=rival_id, gw=gw),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            if response.status_code == 404:
                logger.info("Rival %d squad not yet finalized for GW %d, skipping", rival_id, gw)
                skipped += 1
            else:
                response.raise_for_status()
                payload = response.json()
                returned_gw = (payload.get("entry_history") or {}).get("event")
                if returned_gw != gw:
                    logger.info(
                        "Rival %d returned stale GW %s (expected %d), skipping",
                        rival_id, returned_gw, gw,
                    )
                    skipped += 1
                else:
                    rows.append(_build_rival_row(rival_id, gw, payload))
        except Exception as exc:
            logger.error("Failed to fetch picks for rival %d: %s", rival_id, exc)
            continue

        if idx % RIVAL_PROGRESS_LOG_EVERY == 0:
            logger.info("Fetched picks for %d / %d rivals", idx, total)

        time.sleep(random.uniform(*RIVAL_PICKS_SLEEP_RANGE))

    return rows, skipped


def write_rival_squads(rows: list[dict[str, Any]], supabase: Client) -> None:
    """Batch upsert rival squad rows into rival_team_snapshots."""
    if not rows:
        logger.warning("No rival squad rows to write")
        return

    total = len(rows)
    for start in range(0, total, RIVAL_BATCH_SIZE):
        batch = rows[start : start + RIVAL_BATCH_SIZE]
        supabase.table("rival_team_snapshots").upsert(batch).execute()
        logger.info(
            "Upserted %d / %d rival squad rows",
            min(start + RIVAL_BATCH_SIZE, total), total,
        )


def main() -> None:
    """Run the Phase 2 user + rivals ingestion pipeline."""
    started = time.monotonic()
    supabase = get_supabase_client()

    leagues = load_tracked_leagues(supabase)
    if not leagues:
        logger.warning("No rows in tracked_leagues — insert league config and re-run. Exiting.")
        return

    bootstrap = fetch_bootstrap()
    current_gw = determine_current_gw(bootstrap)
    if current_gw is None:
        logger.warning("No current or next gameweek found in bootstrap-static. Exiting.")
        return
    logger.info("Targeting gameweek %d", current_gw)

    fetch_and_write_my_squads(leagues, current_gw, supabase)
    write_league_standings(leagues, supabase)

    rival_ids = load_unique_rival_ids(supabase)
    rival_rows, skipped = fetch_rival_squads(rival_ids, current_gw)
    write_rival_squads(rival_rows, supabase)

    duration = round(time.monotonic() - started, 1)
    logger.info(
        "Phase 2 run complete: %d leagues, %d rivals, %d squad snapshots, %d pre-deadline skips, %ss",
        len(leagues), len(rival_ids), len(rival_rows), skipped, duration,
    )


if __name__ == "__main__":
    main()
