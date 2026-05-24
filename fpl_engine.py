"""FPL Sniper daily ingestion pipeline.

Fetches Fantasy Premier League data from the public API and upserts it into
Supabase Postgres. Designed to run once per day on Railway's cron scheduler.
"""

import json
import logging
import os
import random
import time
from typing import Any

import pandas as pd
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
ELEMENT_SUMMARY_URL = "https://fantasy.premierleague.com/api/element-summary/{player_id}/"
REQUEST_TIMEOUT_SECONDS = 30
POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
HISTORY_BATCH_SIZE = 500
PROGRESS_LOG_EVERY = 50


def get_supabase_client() -> Client:
    """Construct a Supabase client using the service-role key from env."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def fetch_bootstrap() -> dict[str, Any]:
    """Fetch the FPL bootstrap-static snapshot (teams, players, gameweeks)."""
    logger.info("Fetching bootstrap-static from FPL API")
    response = requests.get(BOOTSTRAP_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def write_snapshot(data: dict[str, Any], supabase: Client) -> None:
    """Clean teams + players from bootstrap and upsert into snapshot tables."""
    teams_df = pd.DataFrame(data["teams"])[[
        "id", "name", "short_name", "strength_overall_home", "strength_overall_away",
    ]]
    teams_rows = json.loads(teams_df.to_json(orient="records"))
    supabase.table("teams").upsert(teams_rows).execute()
    logger.info("Upserted %d teams", len(teams_rows))

    raw = pd.DataFrame(data["elements"])

    has_tackles = "tackles" in raw.columns
    has_cbi = "clearances_blocks_interceptions" in raw.columns
    if not has_cbi:
        logger.warning(
            "FPL API missing 'clearances_blocks_interceptions'; cbit will use tackles only"
        )

    cbi = raw["clearances_blocks_interceptions"].fillna(0).astype(int) if has_cbi else 0
    tackles = raw["tackles"].fillna(0).astype(int) if has_tackles else 0

    minutes = raw["minutes"]
    total_points = raw["total_points"]
    price = raw["now_cost"] / 10

    # .where(cond) keeps value where cond is True, else NaN — naturally
    # produces None for points_per_90 / price_per_point when the divisor is 0.
    snapshot_df = pd.DataFrame({
        "id": raw["id"],
        "web_name": raw["web_name"],
        "team_id": raw["team"],
        "position": raw["element_type"].map(POSITION_MAP),
        "price": price,
        "total_points": total_points,
        "ownership": pd.to_numeric(raw["selected_by_percent"], errors="coerce"),
        "points_per_90": total_points * 90 / minutes.where(minutes > 0),
        "price_per_point": price / total_points.where(total_points > 0),
        "cbit": cbi + tackles,
        "xg": pd.to_numeric(raw["expected_goals"], errors="coerce"),
        "xa": pd.to_numeric(raw["expected_assists"], errors="coerce"),
        "xgi": pd.to_numeric(raw["expected_goal_involvements"], errors="coerce"),
        "xgc": pd.to_numeric(raw["expected_goals_conceded"], errors="coerce"),
        "ict_index": pd.to_numeric(raw["ict_index"], errors="coerce"),
        "form": pd.to_numeric(raw["form"], errors="coerce"),
        "minutes": minutes,
    })

    players_rows = json.loads(snapshot_df.to_json(orient="records"))
    supabase.table("players_master").upsert(players_rows).execute()
    logger.info("Upserted %d players", len(players_rows))


def _to_float_or_none(value: Any) -> float | None:
    """Cast an FPL string/number field to float, or None if empty/invalid."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_player_history(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch element-summary for active players, return flat list of history rows."""
    active = [
        e for e in data["elements"]
        if e["minutes"] > 0 or e["cost_change_event"] != 0
    ]
    skipped = len(data["elements"]) - len(active)
    logger.info(
        "Fetching history for %d active players (skipping %d inactive)",
        len(active), skipped,
    )

    history_rows: list[dict[str, Any]] = []
    for idx, player in enumerate(active, start=1):
        player_id = player["id"]
        try:
            response = requests.get(
                ELEMENT_SUMMARY_URL.format(player_id=player_id),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            summary = response.json()

            for row in summary.get("history", []):
                cbi = row.get("clearances_blocks_interceptions") or 0
                tackles = row.get("tackles") or 0
                history_rows.append({
                    "player_id": player_id,
                    "gw": row["round"],
                    "minutes": row.get("minutes", 0),
                    "total_points": row.get("total_points", 0),
                    "goals": row.get("goals_scored", 0),
                    "assists": row.get("assists", 0),
                    "clean_sheets": row.get("clean_sheets", 0),
                    "xg": _to_float_or_none(row.get("expected_goals")),
                    "xa": _to_float_or_none(row.get("expected_assists")),
                    "xgi": _to_float_or_none(row.get("expected_goal_involvements")),
                    "xgc": _to_float_or_none(row.get("expected_goals_conceded")),
                    "bps": row.get("bps", 0),
                    "cbit": int(cbi) + int(tackles),
                    "price": row["value"] / 10,
                })
        except Exception as exc:
            logger.error("Failed to fetch history for player %d: %s", player_id, exc)
            continue

        if idx % PROGRESS_LOG_EVERY == 0:
            logger.info("Fetched history for %d / %d players", idx, len(active))

        time.sleep(random.uniform(0.1, 0.15))

    logger.info(
        "Collected %d raw fixture rows from %d players", len(history_rows), len(active)
    )
    return _aggregate_double_gameweeks(history_rows)


def _aggregate_double_gameweeks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum stats across fixtures sharing the same (player_id, gw) — handles DGWs."""
    if not rows:
        return rows
    df = pd.DataFrame(rows)
    if not df.duplicated(subset=["player_id", "gw"]).any():
        return rows
    agg = df.groupby(["player_id", "gw"], as_index=False).agg({
        "minutes": "sum",
        "total_points": "sum",
        "goals": "sum",
        "assists": "sum",
        "clean_sheets": "sum",
        "xg": "sum",
        "xa": "sum",
        "xgi": "sum",
        "xgc": "sum",
        "bps": "sum",
        "cbit": "sum",
        "price": "first",
    })
    logger.info("Aggregated %d fixture rows → %d gameweek rows (DGW handling)", len(df), len(agg))
    return json.loads(agg.to_json(orient="records"))


def write_history(history_rows: list[dict[str, Any]], supabase: Client) -> None:
    """Batch upsert history rows into player_history."""
    if not history_rows:
        logger.warning("No history rows to write; skipping player_history upsert")
        return

    total = len(history_rows)
    for start in range(0, total, HISTORY_BATCH_SIZE):
        batch = history_rows[start : start + HISTORY_BATCH_SIZE]
        supabase.table("player_history").upsert(batch).execute()
        logger.info("Upserted %d / %d history rows", min(start + HISTORY_BATCH_SIZE, total), total)


def main() -> None:
    """Run the full daily ingestion pipeline."""
    supabase = get_supabase_client()
    data = fetch_bootstrap()
    write_snapshot(data, supabase)
    history_rows = fetch_player_history(data)
    write_history(history_rows, supabase)


if __name__ == "__main__":
    main()
