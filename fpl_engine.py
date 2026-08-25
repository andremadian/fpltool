"""FPL Sniper global ingestion pipeline.

Fetches Fantasy Premier League data from the public API and upserts it into
Supabase Postgres. Two modes, both scheduled via launchd (see launchd/):

  weekly (default) — full run, Friday 5pm WIB: snapshot + per-player
      history crawl + fixtures (~2.5 minutes)
  --daily          — light run, 9am WIB: one bootstrap call, refreshes the
      players_master snapshot and appends today's price/ownership/news row
      per player to player_daily (~5 seconds)

Every time-series row is stamped with the season it belongs to (e.g.
'2025/26') because FPL re-issues player, team and fixture IDs each season.
At season end (all gameweeks finished) the run archives the final
players_master + teams snapshots into the season archive tables, then
subsequent off-season runs exit early until the new season's API goes live.

Every run — including off-season early exits — records a row in
pipeline_runs and pings its healthchecks.io URL (if configured), so a
missing row/ping always means "the run never happened".
"""

import argparse
import json
import logging
import os
import random
import time
from datetime import date
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import Client, create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# The Supabase client logs every HTTP request at INFO via httpx — hundreds of
# lines per run that drown out the pipeline's own progress messages.
logging.getLogger("httpx").setLevel(logging.WARNING)

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
ELEMENT_SUMMARY_URL = "https://fantasy.premierleague.com/api/element-summary/{player_id}/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"
REQUEST_TIMEOUT_SECONDS = 30
POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
HISTORY_BATCH_SIZE = 500
PROGRESS_LOG_EVERY = 50


def get_supabase_client() -> Client:
    """Construct a Supabase client using the service-role key from env."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


# launchd fires a missed job the moment the Mac wakes, which is routinely before
# WiFi has reassociated. A dropped connection there used to surface as a bogus
# "apply migration X" error and silently cost the run (an Aug 2026 blip lost a
# whole gameweek's rival capture) — so poll before concluding anything is wrong.
NETWORK_PROBE_ATTEMPTS = 6
NETWORK_PROBE_BACKOFF_SECONDS = 15

# The only Postgres SQLSTATEs that genuinely mean "the migration isn't applied":
# undefined_column and undefined_table. Anything else is a transport problem.
MISSING_SCHEMA_SQLSTATES = frozenset({"42703", "42P01"})

# (table, column, migration that provides it) — checked at startup so an
# un-migrated database fails loudly with instructions instead of mid-run.
SCHEMA_CHECKS = [
    ("players_season_archive", "id", "0005_season_rollover.sql"),
    ("players_master", "status", "0006_player_availability_fields.sql"),
    ("player_daily", "as_of_date", "0007_player_daily_and_pipeline_runs.sql"),
    ("pipeline_runs", "engine", "0007_player_daily_and_pipeline_runs.sql"),
    ("gameweeks", "deadline_time", "0008_pwa_foundation.sql"),
    ("players_master", "last_seen_season", "0013_players_master_season_stamp.sql"),
]


def is_missing_schema(exc: Exception) -> bool:
    """True when Supabase answered and told us a column or table doesn't exist."""
    return isinstance(exc, APIError) and exc.code in MISSING_SCHEMA_SQLSTATES


def wait_for_supabase(supabase: Client) -> None:
    """Poll Supabase until it answers, so a just-woken Mac isn't a failed run."""
    for attempt in range(1, NETWORK_PROBE_ATTEMPTS + 1):
        try:
            supabase.table("pipeline_runs").select("engine").limit(1).execute()
            if attempt > 1:
                logger.info(
                    "Supabase reachable after %s attempts — network was waking up",
                    attempt,
                )
            return
        except Exception as exc:
            if is_missing_schema(exc):
                # The server answered, it just lacks the column. Return and let
                # assert_schema name the migration instead of blaming the network.
                return
            if attempt == NETWORK_PROBE_ATTEMPTS:
                raise RuntimeError(
                    f"Supabase unreachable after {attempt} attempts over "
                    f"{(attempt - 1) * NETWORK_PROBE_BACKOFF_SECONDS}s — this is a "
                    f"network or Supabase outage, not a missing migration. ({exc})"
                ) from exc
            logger.info(
                "Supabase not reachable yet (attempt %s/%s), retrying in %ss…",
                attempt,
                NETWORK_PROBE_ATTEMPTS,
                NETWORK_PROBE_BACKOFF_SECONDS,
            )
            time.sleep(NETWORK_PROBE_BACKOFF_SECONDS)


def assert_schema(supabase: Client) -> None:
    """Fail loudly at startup if an expected migration hasn't been applied."""
    for table, column, migration in SCHEMA_CHECKS:
        try:
            supabase.table(table).select(column).limit(1).execute()
        except Exception as exc:
            if not is_missing_schema(exc):
                # A dropped connection mid-check is not a migration problem.
                # Saying so stops the next reader chasing an applied migration.
                raise RuntimeError(
                    f"Could not verify {table}.{column} — the Supabase call itself "
                    f"failed ({exc}). This is a connection problem, not a missing "
                    f"migration; re-run once the network is stable."
                ) from exc
            raise RuntimeError(
                f"Schema check failed on {table}.{column} — apply "
                f"supabase/migrations/{migration} in the Supabase SQL Editor, "
                f"then re-run. ({exc})"
            ) from exc


def log_pipeline_run(
    supabase: Client,
    engine: str,
    season: str | None,
    gw: int | None,
    rows_written: int,
    duration_seconds: float,
    status: str,
    detail: str | None,
) -> None:
    """Record the run in pipeline_runs; never let logging kill the run itself."""
    try:
        supabase.table("pipeline_runs").insert({
            "engine": engine,
            "season": season,
            "gw": gw,
            "rows_written": rows_written,
            "duration_seconds": duration_seconds,
            "status": status,
            "detail": detail,
        }).execute()
    except Exception as exc:
        logger.warning("Could not record pipeline run (is migration 0007 applied?): %s", exc)


def ping_healthcheck(env_key: str, ok: bool) -> None:
    """Ping the dead-man switch; a missing ping is what triggers the alert email."""
    url = os.environ.get(env_key, "").strip()
    if not url:
        return
    try:
        requests.get(url if ok else url.rstrip("/") + "/fail", timeout=10)
    except Exception as exc:
        logger.warning("Healthcheck ping failed (%s): %s", env_key, exc)


def fetch_bootstrap() -> dict[str, Any]:
    """Fetch the FPL bootstrap-static snapshot (teams, players, gameweeks)."""
    logger.info("Fetching bootstrap-static from FPL API")
    response = requests.get(BOOTSTRAP_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def determine_season(data: dict[str, Any]) -> str:
    """Derive the season label (e.g. '2025/26') from GW1's deadline year."""
    events = data.get("events", [])
    if not events:
        raise ValueError("bootstrap-static has no events; cannot determine season")
    start_year = int(events[0]["deadline_time"][:4])
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def determine_current_gw(data: dict[str, Any]) -> int | None:
    """Current gameweek id, falling back to the next GW between gameweeks."""
    events = data.get("events", [])
    for key in ("is_current", "is_next"):
        for event in events:
            if event.get(key):
                return event["id"]
    return None


def season_is_complete(data: dict[str, Any]) -> bool:
    """True once every gameweek in the bootstrap is marked finished."""
    events = data.get("events", [])
    return bool(events) and all(e.get("finished") for e in events)


def season_already_archived(season: str, supabase: Client) -> bool:
    """Check whether the identity archive already has rows for this season."""
    response = (
        supabase.table("players_season_archive")
        .select("id")
        .eq("season", season)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def archive_season_identities(data: dict[str, Any], season: str, supabase: Client) -> None:
    """Snapshot final player + team identities before FPL re-issues the IDs."""
    player_rows = [
        {
            "season": season,
            "id": e["id"],
            "web_name": e["web_name"],
            "team_id": e["team"],
            "position": POSITION_MAP.get(e["element_type"]),
            "price": e["now_cost"] / 10,
            "total_points": e["total_points"],
        }
        for e in data["elements"]
    ]
    team_rows = [
        {
            "season": season,
            "id": t["id"],
            "name": t["name"],
            "short_name": t["short_name"],
        }
        for t in data["teams"]
    ]
    supabase.table("players_season_archive").upsert(player_rows).execute()
    supabase.table("teams_season_archive").upsert(team_rows).execute()
    logger.info(
        "Archived season %s identities: %d players, %d teams",
        season, len(player_rows), len(team_rows),
    )


def _availability_fields(raw: pd.DataFrame) -> dict[str, Any]:
    """Availability + transfer-momentum columns, defensive against API renames.

    The FPL API has renamed/dropped fields before; missing ones get safe
    defaults so a rename degrades the data instead of killing the run.
    cost_change_event arrives in tenths and is stored in £m, matching price.
    """
    expected = (
        "status", "news", "chance_of_playing_next_round",
        "transfers_in_event", "transfers_out_event", "cost_change_event",
    )
    missing = [c for c in expected if c not in raw.columns]
    if missing:
        logger.warning("FPL API missing fields %s; storing defaults", missing)

    def has(col: str) -> bool:
        return col not in missing

    return {
        "status": raw["status"] if has("status") else None,
        "news": raw["news"] if has("news") else None,
        "chance_of_playing_next_round": (
            pd.to_numeric(raw["chance_of_playing_next_round"], errors="coerce").astype("Int64")
            if has("chance_of_playing_next_round") else None
        ),
        "transfers_in_event": (
            raw["transfers_in_event"].fillna(0).astype(int) if has("transfers_in_event") else 0
        ),
        "transfers_out_event": (
            raw["transfers_out_event"].fillna(0).astype(int) if has("transfers_out_event") else 0
        ),
        "cost_change_event": (
            raw["cost_change_event"].fillna(0).astype(int) / 10 if has("cost_change_event") else 0
        ),
    }


def write_snapshot(data: dict[str, Any], season: str, supabase: Client) -> None:
    """Clean teams + players from bootstrap and upsert into snapshot tables.

    Every player row is stamped with `season` so a later season can tell its
    own players apart from re-issued IDs left behind by an earlier one. The
    upsert never deletes (player_history holds an FK onto players_master), so
    without the stamp the snapshot silently accumulates past seasons — see
    migration 0013.
    """
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
        "last_seen_season": season,
        **_availability_fields(raw),
    })

    players_rows = json.loads(snapshot_df.to_json(orient="records"))
    supabase.table("players_master").upsert(players_rows).execute()
    logger.info("Upserted %d players", len(players_rows))


def write_gameweeks(data: dict[str, Any], season: str, supabase: Client) -> int:
    """Upsert gameweek deadlines/status from bootstrap events — the This-week countdown source."""
    events = data.get("events", [])
    expected = ("finished", "is_current", "is_next")
    if events:
        missing = [f for f in expected if f not in events[0]]
        if missing:
            logger.warning("FPL API missing gameweek fields %s; storing defaults", missing)

    rows = [
        {
            "season": season,
            "gw": e["id"],
            "deadline_time": e["deadline_time"],
            "finished": e.get("finished", False),
            "is_current": e.get("is_current", False),
            "is_next": e.get("is_next", False),
        }
        for e in events
    ]
    supabase.table("gameweeks").upsert(rows).execute()
    logger.info("Upserted %d gameweeks", len(rows))
    return len(rows)


def write_player_daily(data: dict[str, Any], season: str, supabase: Client) -> int:
    """Append today's per-player price/ownership/news row to player_daily."""
    raw = pd.DataFrame(data["elements"])
    daily_df = pd.DataFrame({
        "season": season,
        "player_id": raw["id"],
        "as_of_date": date.today().isoformat(),
        "price": raw["now_cost"] / 10,
        "ownership": pd.to_numeric(raw["selected_by_percent"], errors="coerce"),
        "form": pd.to_numeric(raw["form"], errors="coerce"),
        "total_points": raw["total_points"],
        **_availability_fields(raw),
    })

    rows = json.loads(daily_df.to_json(orient="records"))
    for start in range(0, len(rows), HISTORY_BATCH_SIZE):
        supabase.table("player_daily").upsert(rows[start : start + HISTORY_BATCH_SIZE]).execute()
    logger.info("Upserted %d player_daily rows for %s", len(rows), date.today().isoformat())
    return len(rows)


def _to_float_or_none(value: Any) -> float | None:
    """Cast an FPL string/number field to float, or None if empty/invalid."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_player_history(data: dict[str, Any], season: str) -> list[dict[str, Any]]:
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
                    "season": season,
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
        "season": "first",
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


def fetch_fixtures(season: str) -> list[dict[str, Any]]:
    """Fetch the FPL fixtures list (past + future) and return cleaned records."""
    logger.info("Fetching fixtures from FPL API")
    response = requests.get(FIXTURES_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    df = pd.DataFrame(response.json())

    # Use pandas nullable Int64 so columns with occasional nulls (gw, scores)
    # stay as integers — float dtype would JSON-serialize "2.0" which
    # Postgres rejects when upserting into int columns.
    snapshot = pd.DataFrame({
        "season": season,
        "id": df["id"].astype("Int64"),
        "gw": df["event"].astype("Int64"),
        "kickoff_time": df["kickoff_time"],
        "home_team_id": df["team_h"].astype("Int64"),
        "away_team_id": df["team_a"].astype("Int64"),
        "home_difficulty": df["team_h_difficulty"].astype("Int64"),
        "away_difficulty": df["team_a_difficulty"].astype("Int64"),
        "home_score": df["team_h_score"].astype("Int64"),
        "away_score": df["team_a_score"].astype("Int64"),
        "finished": df["finished"].astype(bool),
    })
    return json.loads(snapshot.to_json(orient="records"))


def write_fixtures(rows: list[dict[str, Any]], supabase: Client) -> None:
    """Upsert fixtures into the fixtures table."""
    if not rows:
        logger.warning("No fixtures to write")
        return
    supabase.table("fixtures").upsert(rows).execute()
    unfinished = sum(1 for r in rows if not r.get("finished"))
    logger.info(
        "Upserted %d fixtures (%d unfinished — projections will use these)",
        len(rows), unfinished,
    )


def main() -> None:
    """Run the ingestion pipeline (weekly full or --daily light), fully instrumented."""
    parser = argparse.ArgumentParser(description="FPL Sniper global ingestion engine")
    parser.add_argument(
        "--daily",
        action="store_true",
        help="light run: refresh snapshot + append player_daily rows (no history crawl)",
    )
    args = parser.parse_args()

    engine_label = "fpl_engine --daily" if args.daily else "fpl_engine"
    healthcheck_key = "HEALTHCHECK_URL_DAILY" if args.daily else "HEALTHCHECK_URL_WEEKLY"

    started = time.monotonic()
    supabase = get_supabase_client()

    status = "success"
    detail: str | None = None
    rows_written = 0
    season: str | None = None
    gw: int | None = None
    try:
        wait_for_supabase(supabase)
        assert_schema(supabase)
        data = fetch_bootstrap()
        season = determine_season(data)
        gw = determine_current_gw(data)
        logger.info("Ingesting season %s (%s mode)", season, "daily" if args.daily else "weekly")

        season_over = season_is_complete(data)
        if season_over and season_already_archived(season, supabase):
            status = "skipped_offseason"
            detail = "season complete and archived; waiting for the new season's API"
            logger.info(
                "Season %s is complete and already archived — nothing to ingest "
                "until the new season's API goes live. Exiting.", season,
            )
        elif args.daily:
            write_snapshot(data, season, supabase)
            gw_rows = write_gameweeks(data, season, supabase)
            rows_written = write_player_daily(data, season, supabase)
            detail = f"snapshot refreshed + {rows_written} player_daily rows + {gw_rows} gameweeks"
        else:
            write_snapshot(data, season, supabase)
            gw_rows = write_gameweeks(data, season, supabase)
            history_rows = fetch_player_history(data, season)
            write_history(history_rows, supabase)
            fixtures = fetch_fixtures(season)
            write_fixtures(fixtures, supabase)
            rows_written = len(history_rows) + len(fixtures)
            detail = f"{len(history_rows)} history rows + {len(fixtures)} fixtures + {gw_rows} gameweeks"

            # Final run of the season: preserve who each re-issuable ID referred to.
            if season_over:
                archive_season_identities(data, season, supabase)
    except Exception as exc:
        status = "failed"
        detail = str(exc)[:500]
        logger.exception("%s run failed", engine_label)
        raise SystemExit(1) from exc
    finally:
        duration = round(time.monotonic() - started, 1)
        log_pipeline_run(supabase, engine_label, season, gw, rows_written, duration, status, detail)
        ping_healthcheck(healthcheck_key, ok=(status != "failed"))
        logger.info("%s finished: status=%s duration=%ss", engine_label, status, duration)


if __name__ == "__main__":
    main()
