"""FPL Sniper weekly brief engine.

Wires the `brief/` modules together: reads the live FPL API plus this season's
Supabase history, projects every player over a 5-GW window, solves 15
(free transfers x max hits) scenarios with rival-aware tie-breaking, evaluates
chips, and writes one row into `weekly_brief` for the PWA to read.

Runs daily at 09:30 WIB plus Saturday 10:30 WIB via launchd. Every run records
a row in pipeline_runs and pings HEALTHCHECK_URL_BRIEF (if configured), so a
missing row/ping always means "the run never happened".

`--dry-run` computes the payload, logs a summary and writes the JSON to
~/Library/Logs/fplsniper/brief-dryrun.json without touching the database.

Writes only `weekly_brief`; the ops helpers below are deliberately duplicated
from fpl_user_engine.py, same as the other engines.
"""

import dataclasses
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import Client, create_client

from brief import data, fpl_api
from brief.availability import availability, can_buy, is_priority_sell
from brief.chips import evaluate_chips, solve_freehit, solve_wildcard
from brief.model import Projection, project_all
from brief.optimise import Solution, optimise
from brief.payload import ScenarioResult, build_payload
from brief.rivals import (
    Mode,
    Rival,
    captain_share,
    decide_mode,
    optimise_with_guardrail,
    ownership,
    pick_captain,
    utility_weights,
)
from brief.squad import build_my_squad
from brief.types import Gameweek, HistoryRow
from brief.window import target_gw, window_gws

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# The Supabase client logs every HTTP request at INFO via httpx — too noisy.
logging.getLogger("httpx").setLevel(logging.WARNING)

ENGINE_NAME = "fpl_brief_engine"
FREE_TRANSFER_OPTIONS = [1, 2, 3, 4, 5]
HIT_OPTIONS = [0, 4, 8]
HIT_COST = 4
# How many GWs back from target-1 to look for an entry's latest picks.
PICKS_LOOKBACK = 3
DRY_RUN_PATH = Path.home() / "Library" / "Logs" / "fplsniper" / "brief-dryrun.json"

# launchd fires a missed job the moment the Mac wakes, often before WiFi is back.
NETWORK_PROBE_ATTEMPTS = 6
NETWORK_PROBE_BACKOFF_SECONDS = 15

# The only Postgres SQLSTATEs that genuinely mean "the migration isn't applied".
MISSING_SCHEMA_SQLSTATES = frozenset({"42703", "42P01"})

# (table, column, migration that provides it) — checked at startup.
SCHEMA_CHECKS = [
    ("weekly_brief", "payload", "0014_weekly_brief.sql"),
    ("players_master", "last_seen_season", "0013_players_master_season_stamp.sql"),
    ("pipeline_runs", "engine", "0007_player_daily_and_pipeline_runs.sql"),
]


class SeasonComplete(Exception):
    """Every gameweek is finished: there is no brief to build until next season."""

    def __init__(self, season: str) -> None:
        """Remember which season ended."""
        super().__init__(f"season {season} is complete")
        self.season = season


class PreSeason(Exception):
    """No locked picks exist yet (before the GW1 deadline): nothing to brief, not a failure."""

    def __init__(self, season: str, reason: str) -> None:
        """Remember the season and why the run skipped."""
        super().__init__(reason)
        self.season = season


# ---------------------------------------------------------------- ops helpers


def get_supabase_client() -> Client:
    """Construct a Supabase client using the service-role key from env."""
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def is_missing_schema(exc: Exception) -> bool:
    """True when Supabase answered and told us a column or table doesn't exist."""
    return isinstance(exc, APIError) and exc.code in MISSING_SCHEMA_SQLSTATES


def wait_for_supabase(supabase: Client) -> None:
    """Poll Supabase until it answers, so a just-woken Mac isn't a failed run."""
    for attempt in range(1, NETWORK_PROBE_ATTEMPTS + 1):
        try:
            supabase.table("pipeline_runs").select("engine").limit(1).execute()
            if attempt > 1:
                logger.info("Supabase reachable after %s attempts — network was waking up", attempt)
            return
        except Exception as exc:
            if is_missing_schema(exc):
                return  # server answered; let assert_schema name the migration
            if attempt == NETWORK_PROBE_ATTEMPTS:
                raise RuntimeError(
                    f"Supabase unreachable after {attempt} attempts over "
                    f"{(attempt - 1) * NETWORK_PROBE_BACKOFF_SECONDS}s — this is a "
                    f"network or Supabase outage, not a missing migration. ({exc})"
                ) from exc
            logger.info("Supabase not reachable yet (attempt %s/%s), retrying in %ss…",
                        attempt, NETWORK_PROBE_ATTEMPTS, NETWORK_PROBE_BACKOFF_SECONDS)
            time.sleep(NETWORK_PROBE_BACKOFF_SECONDS)


def assert_schema(supabase: Client, checks: list[tuple[str, str, str]] = SCHEMA_CHECKS) -> None:
    """Fail loudly at startup if an expected migration hasn't been applied."""
    for table, column, migration in checks:
        try:
            supabase.table(table).select(column).limit(1).execute()
        except Exception as exc:
            if not is_missing_schema(exc):
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
            "engine": ENGINE_NAME,
            "season": season,
            "gw": gw,
            "rows_written": rows_written,
            "duration_seconds": duration_seconds,
            "status": status,
            "detail": detail,
        }).execute()
    except Exception as exc:
        logger.warning("Could not record pipeline run (is migration 0007 applied?): %s", exc)


def ping_healthcheck(ok: bool) -> None:
    """Ping the dead-man switch; a missing ping is what triggers the alert email."""
    url = os.environ.get("HEALTHCHECK_URL_BRIEF", "").strip()
    if not url:
        return
    try:
        requests.get(url if ok else url.rstrip("/") + "/fail", timeout=10)
    except Exception as exc:
        logger.warning("Healthcheck ping failed (HEALTHCHECK_URL_BRIEF): %s", exc)


# ---------------------------------------------------------------- run helpers


def determine_season(bootstrap: dict[str, Any]) -> str:
    """Derive the season label (e.g. '2025/26') from GW1's deadline year."""
    events = bootstrap.get("events", [])
    if not events:
        raise ValueError("bootstrap-static has no events; cannot determine season")
    start_year = int(events[0]["deadline_time"][:4])
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def season_is_complete(bootstrap: dict[str, Any]) -> bool:
    """True once every gameweek in the bootstrap is marked finished."""
    events = bootstrap.get("events", [])
    return bool(events) and all(e.get("finished") for e in events)


def gameweeks_from_bootstrap(bootstrap: dict[str, Any]) -> list[Gameweek]:
    """Every GW and its (tz-aware) deadline, straight from the live API."""
    return [
        Gameweek(e["id"], datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")))
        for e in bootstrap["events"]
    ]


def gw1_prices(history: list[HistoryRow]) -> dict[int, float]:
    """Each player's price in his earliest history row (≈ an original pick's purchase price)."""
    first: dict[int, HistoryRow] = {}
    for row in history:
        if row.player_id not in first or row.gw < first[row.player_id].gw:
            first[row.player_id] = row
    return {pid: row.price for pid, row in first.items()}


def latest_picks(entry_id: int, target: int) -> tuple[int, dict] | None:
    """(gw, picks) for the latest locked non-Free-Hit GW from target-1 back PICKS_LOOKBACK GWs.

    A Free Hit squad reverts at the next deadline, so it says nothing about the
    squad that will play the target GW — step past it to the GW before.
    """
    for gw in range(target - 1, max(target - 1 - PICKS_LOOKBACK, 0), -1):
        picks = fpl_api.fetch_entry_picks(entry_id, gw)
        if picks is not None and picks.get("active_chip") != "freehit":
            return gw, picks
    return None


def normalise_picks(picks: list[dict]) -> list[dict]:
    """Picks with last GW's chip multipliers (3xc, bboost) reset to a plain captain/XI/bench."""
    return [
        {**p, "multiplier": 2 if p.get("is_captain") else (1 if p["position"] <= 11 else 0)}
        for p in picks
    ]


def as_of_gw(history: dict, transfers: list[dict], gw: int) -> tuple[dict, list[dict]]:
    """History and transfers trimmed to GW `gw`, so bank/purchases match the picks used."""
    trimmed = {**history, "current": [r for r in history["current"] if r["event"] <= gw]}
    return trimmed, [t for t in transfers if t["event"] <= gw]


def build_rivals(standings: list[dict], my_entry: int, my_picks: dict, target: int) -> list[Rival]:
    """A Rival per league entry (me included); a rival whose picks can't be fetched gets None.

    Every squad is normalised to no chip: last GW's chip never applies to the target GW.
    """
    if not any(row["entry"] == my_entry for row in standings):
        raise RuntimeError(f"My entry {my_entry} is not in league standings — check tracked_leagues")
    rivals: list[Rival] = []
    for row in standings:
        if row["entry"] == my_entry:
            picks: dict | None = my_picks
        else:
            try:
                found = latest_picks(row["entry"], target)
                picks = found[1] if found else None
            except Exception as exc:
                logger.warning("Picks for entry %s failed (%s); treating as no squad yet", row["entry"], exc)
                picks = None
        rivals.append(Rival(
            entry_id=row["entry"],
            team_name=row.get("entry_name") or "",
            player_name=row.get("player_name") or "",
            rank=row["rank"],
            total=row.get("total") or 0,
            picks=normalise_picks(picks["picks"]) if picks else None,
            chip=None,
        ))
    return rivals


def display_captains(
    sol: Solution, projs: dict[int, Projection], window: list[int], mode: Mode,
    own_captain: dict[int, float],
) -> Solution:
    """The Solution with captain/vice per GW replaced by pick_captain's (displayed) choice."""
    captain, vice = {}, {}
    for gw in window:
        captain[gw], vice[gw] = pick_captain(sol.xi[gw], projs, gw, mode, own_captain)
    return dataclasses.replace(sol, captain=captain, vice=vice)


class _Timer:
    """Logs how long each phase of the run took."""

    def __init__(self) -> None:
        """Start the clock."""
        self.started = time.monotonic()
        self.last = self.started
        self.phases: list[tuple[str, float]] = []

    def lap(self, phase: str) -> None:
        """Record and log the time since the previous lap."""
        now = time.monotonic()
        self.phases.append((phase, now - self.last))
        logger.info("Phase %-12s %.1fs", phase, now - self.last)
        self.last = now

    def total(self) -> float:
        """Seconds since the timer started."""
        return time.monotonic() - self.started


def run(sb: Any, now: datetime) -> dict:
    """Compute this week's brief payload (raises SeasonComplete in the off-season)."""
    timer = _Timer()
    bootstrap = fpl_api.fetch_bootstrap()
    season = determine_season(bootstrap)
    if season_is_complete(bootstrap):
        raise SeasonComplete(season)
    gameweeks = gameweeks_from_bootstrap(bootstrap)
    target = target_gw(gameweeks, now)
    window = window_gws(target, last_gw=max(g.gw for g in gameweeks))
    today = now.date()
    if target == 1:
        raise PreSeason(season, "before the GW1 deadline; no locked picks yet")
    logger.info("Season %s, target GW%d, window %s", season, target, window)
    timer.lap("bootstrap")

    history = data.load_history(sb, season)
    fixtures = data.load_fixtures(sb, season)
    flags = data.load_flags(sb, season)
    league_id, my_entry = data.load_tracked_league(sb)
    logger.info("Loaded %d history rows, %d fixture sides, %d flag rows",
                len(history), len(fixtures), len(flags))
    timer.lap("supabase")

    # Live bootstrap only lists current-season players, so no last_seen_season filter (R9).
    players = fpl_api.players_from_bootstrap(bootstrap)
    projs = project_all(players, history, fixtures, flags, gameweeks, window, today)
    missing = [pid for pid in players if pid not in projs]
    if missing:
        logger.warning("%d players have no projection; they count as 0 points", len(missing))
    timer.lap("project")

    my_history = fpl_api.fetch_entry_history(my_entry)
    my_transfers = fpl_api.fetch_entry_transfers(my_entry)
    found = latest_picks(my_entry, target)
    if found is None:
        raise PreSeason(season, f"no non-Free-Hit picks for my entry {my_entry} in "
                                f"GW{max(target - PICKS_LOOKBACK, 1)}..GW{target - 1} yet")
    picks_gw, my_picks = found
    if picks_gw != target - 1:
        logger.info("Using my GW%d picks (GW%d was a Free Hit or missing)", picks_gw, target - 1)
    my_history, my_transfers = as_of_gw(my_history, my_transfers, picks_gw)
    squad = build_my_squad(my_history, my_transfers, my_picks, players, gw1_prices(history), target)
    standings = fpl_api.fetch_league_standings(league_id)
    rivals = build_rivals(standings, my_entry, my_picks, target)
    mode = decide_mode(rivals, my_entry)
    logger.info("Mode %s: rank %d, target %s, gap %d", mode.kind, mode.my_rank,
                mode.target.player_name if mode.target else "none", mode.gap)
    timer.lap("fpl_api")

    own = ownership(rivals, my_entry)
    own_captain = captain_share(rivals, my_entry)
    if mode.kind == "chase":
        weights = utility_weights(mode, own, player_ids=set(projs))  # R8: unowned get the bonus
    else:
        weights = utility_weights(mode, own)
    buyable = {pid for pid, p in players.items() if can_buy(p)}

    hold = optimise(projs, players, squad, window, max_transfers=0, free_transfers=0)
    freehit = (solve_freehit(projs, players, squad, target, buyable)
               if "freehit" in squad.chips_available else None)
    wildcard = (solve_wildcard(projs, players, squad, window, buyable)
                if "wildcard" in squad.chips_available else None)
    timer.lap("hold+chips")

    scenarios: list[ScenarioResult] = []
    for ft in FREE_TRANSFER_OPTIONS:
        for hits in HIT_OPTIONS:
            sol, changed = optimise_with_guardrail(
                projs, players, squad, window, ft + hits // HIT_COST, ft, buyable, weights)
            shown = display_captains(sol, projs, window, mode, own_captain)
            chips = evaluate_chips(squad.chips_available, shown, projs, window, freehit, wildcard, players)
            scenarios.append(ScenarioResult(ft, hits, shown, changed, chips))
    timer.lap("scenarios")

    priority_sells: dict[int, int] = {}
    for pid in squad.player_ids:
        mults = availability(players[pid], window, gameweeks, today)
        if is_priority_sell(mults):
            priority_sells[pid] = sum(1 for m in mults if m == 0.0)

    payload = build_payload(
        season=season, window=window, generated_at=now, mode=mode, rivals=rivals,
        my_entry=my_entry, players=players, projs=projs, squad=squad, scenarios=scenarios,
        hold_total=hold.raw_total, priority_sells=priority_sells,
    )
    timer.lap("payload")
    logger.info("Brief computed in %.1fs (%s)", timer.total(),
                ", ".join(f"{name} {secs:.1f}s" for name, secs in timer.phases))
    return payload


def _names(slots: list[dict]) -> str:
    """Comma-separated player names from payload slots."""
    return ", ".join(s["name"] for s in slots)


def log_summary(payload: dict) -> None:
    """Log a human-readable summary of the brief."""
    mode = payload["mode"]
    target = mode["target"]
    logger.info("Brief GW%d (window %s): %s, rank %d, target %s, gap %d",
                payload["gw"], payload["window"], mode["kind"], mode["my_rank"],
                target["player_name"] if target else "none", mode["gap"])
    for key in ("1_0", "2_0"):
        block = payload["scenarios"].get(key)
        if block is None:
            continue
        logger.info("[%s] projected %.1f, net %+.1f over window, hit %d", key,
                    block["projected_points"], block["net_gain_window"], block["hit_cost"])
        for t in block["transfers"]:
            logger.info("[%s]   %s -> %s: %s", key, t["out"]["name"], t["in"]["name"], t["reason"])
        logger.info("[%s]   XI (%s): %s", key, block["formation"], _names(block["xi"]))
        logger.info("[%s]   captain %s (%s), vice %s", key, block["captain"]["name"],
                    block["captain"]["reason"], block["vice"]["name"])
        for chip in block["chips"]:
            logger.info("[%s]   chip %s: %s", key, chip["chip"], chip["reason"])
    for r in payload["rivals"]:
        logger.info("Rival #%d %s (%s): projected %s, captain %s", r["rank"], r["player_name"],
                    r["team_name"], r["projected_points"], r["captain"])


def main() -> None:
    """Run the weekly brief engine, fully instrumented (or uninstrumented with --dry-run)."""
    dry_run = "--dry-run" in sys.argv[1:]
    started = time.monotonic()
    supabase = get_supabase_client()

    status = "success"
    detail: str | None = None
    rows_written = 0
    season: str | None = None
    gw: int | None = None
    try:
        wait_for_supabase(supabase)
        checks = [c for c in SCHEMA_CHECKS if not (dry_run and c[0] == "weekly_brief")]
        assert_schema(supabase, checks)

        payload = run(supabase, datetime.now(timezone.utc))
        season, gw = payload["season"], payload["gw"]
        mode = payload["mode"]
        target = mode["target"]["player_name"] if mode["target"] else "none"

        if dry_run:
            DRY_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
            DRY_RUN_PATH.write_text(json.dumps(payload, indent=2))
            logger.info("Dry run: payload written to %s; nothing inserted", DRY_RUN_PATH)
        else:
            supabase.table("weekly_brief").insert({
                "season": season, "gw": gw, "mode": mode["kind"], "payload": payload,
            }).execute()
            rows_written = 1
        try:
            log_summary(payload)
        except Exception as exc:  # cosmetic only: never fail a computed brief over a log line
            logger.warning("Could not log the brief summary: %s", exc)
        detail = (f"mode={mode['kind']} target={target} {len(payload['scenarios'])} scenarios "
                  f"{round(time.monotonic() - started)}s")
    except SeasonComplete as done:
        status = "skipped_offseason"
        season = done.season
        detail = "season complete; no brief to build"
        logger.info("Season %s is complete — no brief to build. Exiting.", done.season)
    except PreSeason as early:
        status = "skipped_preseason"
        season = early.season
        detail = str(early)
        logger.info("Pre-season (%s) — no brief to build. Exiting.", early)
    except Exception as exc:
        status = "failed"
        detail = str(exc)[:500]
        logger.exception("%s run failed", ENGINE_NAME)
        raise SystemExit(1) from exc
    finally:
        duration = round(time.monotonic() - started, 1)
        if not dry_run:
            log_pipeline_run(supabase, season, gw, rows_written, duration, status, detail)
            ping_healthcheck(ok=(status != "failed"))
        logger.info("%s finished: status=%s duration=%ss detail=%s%s", ENGINE_NAME, status,
                    duration, detail, " (dry run)" if dry_run else "")


if __name__ == "__main__":
    main()
