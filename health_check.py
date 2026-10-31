"""FPL Sniper pipeline health check.

Read-only status report over the Supabase tables the two engines write.
Answers "is the pipeline actually healthy right now?" in one pass:

  1. season state    — which season is live, next gameweek deadline
  2. engine runs     — last run + last-7-days count per engine vs expected
  3. data freshness  — how stale each table is
  4. config sanity   — tracked_leagues points at a plausible league
  5. warnings        — the actionable subset of the above

Writes nothing to Supabase. Safe to run any time, as often as you like.

  .venv/bin/python health_check.py            # print the report
  .venv/bin/python health_check.py --notify    # print it and send it to Telegram

--notify is what the weekly heartbeat uses (launchd, Thursday 8pm WIB — the
evening before a typical Friday gameweek deadline, so there's still time to
fix a broken pipeline before it matters). It needs TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID in .env; without them the flag exits non-zero rather than
silently reporting to nobody.

Exit code is 0 when everything is healthy and 1 when any warning fired (or
the Telegram send failed), so launchd and healthchecks.io can branch on it.
The report itself always prints.
"""

import argparse
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# How many runs each launchd agent should produce in a healthy 7-day window.
# Mirrors launchd/: daily fires 7x, fetch 1x (Fri), user 2x (Fri + Sat),
# brief 8x (daily 09:30 + Sat 10:30).
EXPECTED_RUNS_PER_WEEK = {
    "fpl_engine --daily": 7,
    "fpl_engine": 1,
    "fpl_user_engine": 2,
    "fpl_brief_engine": 8,
}

# player_daily should gain a row set every day; more than this many days
# without one means the daily agent is not landing.
MAX_PLAYER_DAILY_STALENESS_DAYS = 2

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_TIMEOUT_SECONDS = 20
# Telegram rejects messages over 4096 characters.
TELEGRAM_MAX_CHARS = 4000
TELEGRAM_SEND_ATTEMPTS = 3

# launchd fires a missed job the moment the Mac wakes, which is routinely
# before WiFi has reassociated — the first run of this script died on a
# ReadTimeout against Supabase for exactly that reason. Poll until the
# network answers rather than reporting a phantom outage.
NETWORK_PROBE_ATTEMPTS = 6
NETWORK_PROBE_BACKOFF_SECONDS = 15


class Report:
    """Collects the report as text while logging it line by line."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.warnings: list[str] = []

    def line(self, message: str, *args: object) -> None:
        """Log one report line and keep it for the notification body."""
        rendered = message % args if args else message
        logger.info(rendered)
        self.lines.append(rendered)

    def warn(self, message: str) -> None:
        """Record an actionable problem, surfaced in the warnings section."""
        self.warnings.append(message)

    def as_text(self) -> str:
        """The whole report as one string, warnings included."""
        body = list(self.lines)
        if self.warnings:
            body.append("")
            body.append(f"WARNINGS ({len(self.warnings)})")
            body.extend(f"  - {w}" for w in self.warnings)
        else:
            body.append("")
            body.append("HEALTHY - no warnings")
        return "\n".join(body)


def get_supabase_client() -> Client:
    """Construct a Supabase client using the service-role key from env."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
    return create_client(url, key)


def wait_for_supabase(supabase: Client, report: Report) -> bool:
    """Poll Supabase until it answers, so a just-woken Mac isn't called an outage."""
    for attempt in range(1, NETWORK_PROBE_ATTEMPTS + 1):
        try:
            supabase.table("pipeline_runs").select("engine").limit(1).execute()
            if attempt > 1:
                report.line("(Supabase reachable after %s attempts — network was waking up)", attempt)
            return True
        except Exception as exc:
            if attempt == NETWORK_PROBE_ATTEMPTS:
                report.warn(
                    f"Supabase unreachable after {attempt} attempts over "
                    f"{(attempt - 1) * NETWORK_PROBE_BACKOFF_SECONDS}s — "
                    f"no checks could run ({str(exc)[:120]})"
                )
                return False
            logger.info("Supabase not reachable yet (attempt %s), retrying…", attempt)
            time.sleep(NETWORK_PROBE_BACKOFF_SECONDS)
    return False


def run_check(check, supabase: Client, report: Report) -> None:
    """Run one check section, turning a crash into a warning instead of a dead run.

    The whole point of a heartbeat is to speak up when things are broken, so
    no single failing query may take the report — and the notification with
    it — down. The first scheduled run died exactly this way.
    """
    try:
        check(supabase, report)
    except Exception as exc:
        name = check.__name__.replace("report_", "").replace("_", " ")
        logger.exception("check '%s' failed", name)
        report.line("  (%s check failed: %s)", name, str(exc)[:150])
        report.warn(f"the '{name}' check itself failed: {str(exc)[:150]}")


def report_season_state(supabase: Client, report: Report) -> None:
    """Log which season is live and when the next gameweek deadline lands."""
    report.line("== SEASON ==")

    seasons = supabase.table("fixtures").select("season").order("season", desc=True).limit(1).execute()
    if not seasons.data:
        report.warn("fixtures table is empty — no season data at all")
        return
    latest_season = seasons.data[0]["season"]

    total = supabase.table("fixtures").select("id", count="exact").eq("season", latest_season).execute().count
    finished = (
        supabase.table("fixtures")
        .select("id", count="exact")
        .eq("season", latest_season)
        .eq("finished", True)
        .execute()
        .count
    )
    report.line("latest season in fixtures: %s (%s/%s fixtures finished)", latest_season, finished, total)

    upcoming = (
        supabase.table("gameweeks")
        .select("gw,deadline_time,is_current,is_next,finished")
        .eq("season", latest_season)
        .eq("finished", False)
        .order("gw")
        .limit(1)
        .execute()
    )
    if not upcoming.data:
        report.line("no unfinished gameweeks — season %s is complete", latest_season)
        return

    gw = upcoming.data[0]
    deadline = datetime.fromisoformat(gw["deadline_time"])
    hours_away = (deadline - datetime.now(timezone.utc)).total_seconds() / 3600
    state = "in progress" if gw["is_current"] else "upcoming"
    report.line(
        "next gameweek: GW%s (%s), deadline %s (%s)",
        gw["gw"], state, deadline.strftime("%Y-%m-%d %H:%M UTC"),
        f"{hours_away:.0f}h away" if hours_away < 72 else f"{hours_away / 24:.0f} days away",
    )

    if finished == 0 and hours_away > 0:
        report.line(
            "pre-season: no games played yet in %s, so history/rival capture is idle by design",
            latest_season,
        )


def report_engine_runs(supabase: Client, report: Report) -> None:
    """Log each engine's last run and its run count over the last 7 days."""
    report.line("")
    report.line("== ENGINE RUNS (last 7 days) ==")

    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    for engine, expected in EXPECTED_RUNS_PER_WEEK.items():
        # engine names overlap ('fpl_engine' is a prefix of 'fpl_engine --daily'),
        # so match exactly rather than with a LIKE.
        recent = (
            supabase.table("pipeline_runs")
            .select("ran_at,status,gw,rows_written,detail")
            .eq("engine", engine)
            .gte("ran_at", week_ago)
            .order("ran_at", desc=True)
            .execute()
        )
        runs = recent.data
        ok = [r for r in runs if r["status"] == "success"]
        failed = [r for r in runs if r["status"] == "failed"]
        skipped = [r for r in runs if str(r["status"]).startswith("skipped")]

        last = (
            supabase.table("pipeline_runs")
            .select("ran_at,status,detail")
            .eq("engine", engine)
            .order("ran_at", desc=True)
            .limit(1)
            .execute()
        )
        last_desc = "never run"
        if last.data:
            row = last.data[0]
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["ran_at"])).days
            last_desc = f"{row['ran_at'][:16]} ({age}d ago) status={row['status']}"

        report.line(
            "%-20s %s/%s expected  (ok=%s failed=%s skipped=%s)  last: %s",
            engine, len(runs), expected, len(ok), len(failed), len(skipped), last_desc,
        )

        for run in failed:
            report.line("    FAILED %s — %s", run["ran_at"][:16], str(run["detail"])[:120])

        # A failed run at least recorded itself. A *missing* run means launchd
        # never fired, or the engine died before it could log — the worse case.
        if len(runs) < expected:
            report.warn(
                f"{engine}: only {len(runs)} of {expected} expected runs in the last 7 days "
                f"({expected - len(runs)} never recorded a row)"
            )
        if failed:
            report.warn(f"{engine}: {len(failed)} failed run(s) in the last 7 days")


def report_data_freshness(supabase: Client, report: Report) -> None:
    """Log how current each time-series table is."""
    report.line("")
    report.line("== DATA FRESHNESS ==")

    daily = (
        supabase.table("player_daily")
        .select("as_of_date")
        .order("as_of_date", desc=True)
        .limit(1)
        .execute()
    )
    if daily.data:
        latest = date.fromisoformat(daily.data[0]["as_of_date"])
        stale_days = (date.today() - latest).days
        report.line("player_daily:          latest %s (%s days old)", latest, stale_days)
        if stale_days > MAX_PLAYER_DAILY_STALENESS_DAYS:
            report.warn(f"player_daily is {stale_days} days stale — the daily run is not landing")
    else:
        report.warn("player_daily is empty")

    for table in ("player_history", "rival_team_snapshots", "user_team_snapshots"):
        rows = (
            supabase.table(table)
            .select("season,gw")
            .order("season", desc=True)
            .order("gw", desc=True)
            .limit(1)
            .execute()
        )
        if rows.data:
            report.line("%-22s latest %s GW%s", table + ":", rows.data[0]["season"], rows.data[0]["gw"])
        else:
            report.line("%-22s empty", table + ":")

    report_snapshot_currency(supabase, report)


def report_snapshot_currency(supabase: Client, report: Report) -> None:
    """Log how much of players_master belongs to the current season.

    players_master is upserted by id and never deleted (player_history holds
    an FK onto it), so rows from earlier seasons linger under re-issued IDs.
    last_seen_season (migration 0013) is what tells them apart.
    """
    total = supabase.table("players_master").select("id", count="exact").execute().count

    seasons = supabase.table("fixtures").select("season").order("season", desc=True).limit(1).execute()
    current = seasons.data[0]["season"] if seasons.data else None

    try:
        fresh = (
            supabase.table("players_master")
            .select("id", count="exact")
            .eq("last_seen_season", current)
            .execute()
            .count
        )
    except Exception:
        # Pre-0013 database: the column doesn't exist yet.
        report.line("players_master:        %s rows (apply migration 0013 to split by season)", total)
        report.warn(
            "players_master has no last_seen_season column — apply "
            "supabase/migrations/0013_players_master_season_stamp.sql"
        )
        return

    stale = total - fresh
    report.line("players_master:        %s rows — %s current (%s), %s stale from earlier seasons",
                total, fresh, current, stale)
    if fresh == 0:
        report.warn(
            f"no players_master rows stamped {current} — the engine has not run since migration 0013"
        )


def report_config(supabase: Client, report: Report) -> None:
    """Log the tracked_leagues config the Phase 2 engine depends on."""
    report.line("")
    report.line("== CONFIG ==")

    leagues = supabase.table("tracked_leagues").select("*").execute()
    if not leagues.data:
        report.warn("tracked_leagues is empty — fpl_user_engine will exit without capturing anything")
        report.line("tracked_leagues: empty")
        return

    for league in leagues.data:
        report.line(
            "tracked league %s (%s), my team id %s",
            league["league_id"], league.get("league_name"), league["my_fpl_team_id"],
        )


def send_telegram(report: Report) -> bool:
    """Push the report to Telegram. True if it was delivered."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error(
            "--notify needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env "
            "(create a bot with @BotFather, then read your chat id from "
            "https://api.telegram.org/bot<TOKEN>/getUpdates after messaging it)"
        )
        return False

    headline = (
        f"FPL Sniper — {len(report.warnings)} warning(s)"
        if report.warnings else "FPL Sniper — all healthy"
    )
    text = f"{headline}\n\n{report.as_text()}"
    if len(text) > TELEGRAM_MAX_CHARS:
        text = text[:TELEGRAM_MAX_CHARS] + "\n… (truncated)"

    # Same wake-up race as the Supabase probe: the send is the one step that
    # must not be lost, so retry it rather than failing on a cold network.
    for attempt in range(1, TELEGRAM_SEND_ATTEMPTS + 1):
        try:
            response = requests.post(
                TELEGRAM_API.format(token=token),
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=TELEGRAM_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except Exception as exc:
            if attempt == TELEGRAM_SEND_ATTEMPTS:
                logger.error("Telegram send failed after %s attempts: %s", attempt, exc)
                return False
            logger.info("Telegram send attempt %s failed (%s), retrying…", attempt, exc)
            time.sleep(NETWORK_PROBE_BACKOFF_SECONDS)
            continue
        logger.info("Report sent to Telegram chat %s", chat_id)
        return True
    return False


def main() -> None:
    """Run every check, print the report, exit non-zero if anything warrants attention."""
    parser = argparse.ArgumentParser(description="FPL Sniper pipeline health check")
    parser.add_argument(
        "--notify",
        action="store_true",
        help="also send the report to Telegram (needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)",
    )
    args = parser.parse_args()

    report = Report()
    report.line("FPL Sniper health check — %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
    report.line("")

    try:
        supabase = get_supabase_client()
    except Exception as exc:
        # No client means no checks at all — still worth telling someone.
        report.warn(f"could not build the Supabase client: {exc}")
        supabase = None

    if supabase is not None and wait_for_supabase(supabase, report):
        for check in (
            report_season_state,
            report_engine_runs,
            report_data_freshness,
            report_config,
        ):
            run_check(check, supabase, report)

    logger.info("")
    if report.warnings:
        logger.info("== WARNINGS (%s) ==", len(report.warnings))
        for warning in report.warnings:
            logger.info("  - %s", warning)
    else:
        logger.info("== HEALTHY == no warnings")

    delivered = send_telegram(report) if args.notify else True

    if report.warnings or not delivered:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
