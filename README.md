# FPL Sniper

Python engines that fetch Fantasy Premier League data into Supabase Postgres (Phases 1–3A), plus a weekly brief engine and a one-screen PWA that recommends transfers, XI, captain and chips (Phase 3D). The sections below start with Phase 1 ingestion.

## Files

```
.
├── fpl_engine.py                          # global ingestion (weekly full + --daily light run)
├── fpl_user_engine.py                     # user + rivals ingestion (Phase 2)
├── fpl_brief_engine.py                    # weekly brief engine (Phase 3D) — projections + optimiser → weekly_brief
├── brief/                                 # weekly-brief modules
├── tests/                                 # pytest suite for the brief engine
├── requirements.txt                       # Python dependencies
├── .env.example                           # template for local env vars
├── .gitignore
├── README.md
├── docs/                                  # phase planning + expansion roadmap
├── launchd/                               # LaunchAgent plists (scheduling — see below)
├── sql/queries/                           # curated analytics queries
└── supabase/
    └── migrations/                        # apply in numeric order (0001 → 0014)
```

## What it does

Each run, the script:

1. Fetches the FPL `bootstrap-static` snapshot (teams, players, gameweeks) and derives the current **season label** (e.g. `2025/26`) from GW1's deadline year
2. Cleans the data with pandas and **upserts** teams + players into the snapshot tables
3. For every player with minutes played or a price change, fetches per-gameweek `element-summary` history
4. Aggregates double-gameweek fixtures (when a player plays twice in one GW) and batch-upserts all history rows
5. Upserts all 380 fixtures (FDR, kickoff times, scores)

Every time-series row is stamped with the season, because FPL re-issues player/team/fixture IDs each season (see **Season rollover** below). The full run takes ~2–3 minutes and is idempotent — re-running just updates rows.

There is also a **daily light run** (`fpl_engine.py --daily`, ~5 seconds): one bootstrap call that refreshes the `players_master` snapshot and appends today's price/ownership/availability row per player to `player_daily` — the price-change and injury-news signals the weekly cadence can't see. Every run of either engine (including off-season early exits) records a row in `pipeline_runs` and pings a healthchecks.io URL if configured, so a missing row/ping always means "the run never happened".

---

## Local setup

### Prerequisites

- Python 3.11+
- A Supabase project (free tier is fine)

### 1. Clone and install

```bash
git clone <your-repo-url>
cd "Personal FPL Tool"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The project venv keeps the pipeline isolated from system-Python upgrades/removals — the LaunchAgents point at `.venv/bin/python`, not whatever `python3` happens to resolve to. (A system-Python wipe still deletes the venv itself — that's what the schema assert + healthchecks catch; see the season-start runbook.)

### 2. Apply the database schema

In your Supabase dashboard:
1. Open **SQL Editor**
2. Paste and run each file in `supabase/migrations/` **in numeric order** (0001 → 0007)

You should see "Success. No rows returned." This is correct — `CREATE TABLE` statements don't return data. If Supabase shows a Row Level Security warning, click **"Run without RLS"** — the data tables (`teams`, `players_master`, `player_history`) are intentionally public-readable; RLS is only applied to user-related tables.

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Then edit `.env`:

- `SUPABASE_URL` — Settings → **Data API** → Project URL (looks like `https://<ref>.supabase.co`)
- `SUPABASE_SERVICE_ROLE_KEY` — Settings → **API Keys** → **Secret key** (`sb_secret_...`). ⚠️ **Not** the publishable key.
- `HEALTHCHECK_URL_WEEKLY` / `HEALTHCHECK_URL_DAILY` / `HEALTHCHECK_URL_USER` / `HEALTHCHECK_URL_BRIEF` — optional. Create one check per schedule at [healthchecks.io](https://healthchecks.io) (free tier) and paste each check's ping URL. The engines ping on every run; healthchecks emails you when a ping **doesn't** arrive — the dead-man switch that catches a sleeping Mac, a wiped venv, or any other silent failure. Leave unset to disable.

`.env` is gitignored — it will not be committed.

### 4. Run

```bash
.venv/bin/python fpl_engine.py
```

Expected output: log lines for upserting teams (20), players (~840), history (~18,000+ rows). After it finishes, check Supabase Table Editor — all three FPL tables should be populated.

---

## Scheduling — launchd (the default)

The engines run on local macOS **launchd** LaunchAgents (migrated from cron in July 2026 — launchd runs a missed scheduled job when the Mac wakes from sleep; cron just skips it). The plists live in [`launchd/`](launchd/):

| Agent | Schedule (local/WIB) | Runs |
|---|---|---|
| `com.fplsniper.daily` | every day 9:00am | `fpl_engine.py --daily` (light run, ~5s) |
| `com.fplsniper.fetch` | Friday 5:00pm | `fpl_engine.py` (full run, ~2.5min) |
| `com.fplsniper.user` | Friday 5:30pm + Saturday 10:00am | `fpl_user_engine.py` |
| `com.fplsniper.brief` | every day 9:30am + Saturday 10:30am | `fpl_brief_engine.py` (weekly brief) |

Install (or re-install after editing a plist):

```bash
cp launchd/com.fplsniper.*.plist ~/Library/LaunchAgents/
for name in fetch daily user brief; do
  launchctl bootout gui/$(id -u)/com.fplsniper.$name 2>/dev/null
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fplsniper.$name.plist
done
launchctl list | grep fplsniper   # all agents should appear
```

All engines append to `~/Library/Logs/fplsniper/cron.log` (outside the repo — see below). To trigger a run manually: `launchctl kickstart gui/$(id -u)/com.fplsniper.daily`. To roll back to cron: `launchctl bootout` the agents and re-add the crontab lines from git history.

**Limits, honestly:** launchd catches sleep, not shutdown, and a scheduling fix can't catch a broken runtime (the July 2026 venv wipe). Detection is the healthchecks.io dead-man switch (see env vars above) plus the schema assert both engines run at startup — an un-migrated database or dead venv now fails loudly with instructions instead of silently.

## Season-start runbook (~August, before GW1)

Ten minutes, once a year. The June–July 2026 incident (system-Python wipe killed the venv; four scheduled runs vanished without a trace) is why this exists.

1. **Venv alive?** `.venv/bin/python -c "import supabase; print(supabase.__version__)"` — if it fails: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. **Migrations applied?** `.venv/bin/python fpl_engine.py --daily` — the startup schema assert names any missing migration; apply it in Supabase SQL Editor and re-run until the run succeeds.
3. **Agents loaded?** `launchctl list | grep fplsniper` — three entries; re-install per above if not.
4. **Dead-man switch armed?** All three `HEALTHCHECK_URL_*` vars set in `.env`, and the checks show a fresh ping after step 2's run.
5. **Dry-run the weekly:** `.venv/bin/python fpl_engine.py` then `.venv/bin/python fpl_user_engine.py` — check the summary lines and a new row each in `pipeline_runs`.

---

## Deploy to Railway (alternative, if local reliability isn't enough)

Railway runs your script on a schedule using its built-in cron feature. Free tier covers this comfortably — the script runs once a day for ~3 minutes.

### 1. Push the repo to GitHub

```bash
git init
git add .
git commit -m "FPL Sniper Phase 1"
gh repo create fpl-sniper --private --source=. --push
```

(If you don't have the GitHub CLI, create an empty private repo at github.com/new, then `git remote add origin <repo-url> && git push -u origin main`.)

### 2. Create a Railway project from the repo

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your `fpl-sniper` repo
4. Railway auto-detects Python via Nixpacks and starts a build

The first deploy will fail — that's expected. We haven't told Railway what command to run or given it env vars yet.

### 3. Set the start command

Railway needs to know how to run your script.

1. In your service, go to **Settings**
2. Scroll to **Deploy** → **Custom Start Command**
3. Enter: `python fpl_engine.py`
4. Click outside the field to save

### 4. Set environment variables

1. In your service, go to **Variables**
2. Click **New Variable** and add:
   - `SUPABASE_URL` = your project URL
   - `SUPABASE_SERVICE_ROLE_KEY` = your `sb_secret_...` key
3. Railway will trigger a redeploy automatically

### 5. Configure the cron schedule

1. In your service, go to **Settings**
2. Scroll to **Cron Schedule**
3. Enter: `0 3 * * *`
   This means *3:00 AM UTC, every day* — runs after FPL's nightly data update.
4. Save

Once a cron schedule is set, Railway treats the service as a scheduled job: it spins up, runs the start command, and shuts down. You aren't charged for idle time.

### 6. Test it manually

Before waiting for the cron to fire:

1. Go to **Deployments**
2. Click the **⋯** menu on the latest deployment → **Redeploy**
3. Watch the logs (see below) — should complete in ~3 minutes

### 7. View logs

1. In your service, go to **Deployments**
2. Click the deployment you want to inspect
3. The right pane shows live logs — look for `Upserted 20 teams`, `Upserted 840 players`, `Upserted N / N history rows`

Each day after 3 AM UTC you should see a new deployment in this list. Click into it to confirm the run succeeded.

---

## Troubleshooting

**"Invalid API key"** — You're using the publishable key (`sb_publishable_...`) instead of the secret key (`sb_secret_...`). Get the secret key from Settings → API Keys.

**"ON CONFLICT DO UPDATE command cannot affect row a second time"** — Should not happen any more (handled by DGW aggregation). If you see it, a player has duplicate `(player_id, gw)` rows from the FPL API that the aggregation didn't catch.

**Cron didn't fire** — Verify the schedule is set in Settings, and confirm Railway's project plan still has cron enabled. The free tier supports cron but with usage limits.

**Empty `player_history`** — The script only fetches history for players with `minutes > 0` or a recent price change. Very early in the season (GW1–2), this can be a small set. By mid-season most active squads should have rows.

---

## Schema overview

- **`teams`** — 20 Premier League clubs with strength ratings
- **`players_master`** — current snapshot per player (one row each, ~840 rows)
- **`player_history`** — per-gameweek time series (one row per `(season, player_id, gw)`, ~18k rows per season)
- **`team_history`** — view aggregating `player_history` to the team level per (season, GW)
- **`fixtures`** — all 380 fixtures per season with FDR, kickoff times, and scores; PK `(season, id)`
- **`players_season_archive` / `teams_season_archive`** — who each re-issuable ID referred to in a given season; snapshotted automatically at season end
- **`users`, `user_rivals`, `conversations`, `messages`, `user_profile`** — empty in Phase 1; used by the conversational app in Phase 3+

See the brief or the migration file for full column definitions.

## Season rollover

FPL re-issues player IDs, team IDs (1–20) and fixture IDs every season, so all time-series tables carry a `season` column (e.g. `2025/26`) as part of their primary key (migration 0005). How the engines behave around the boundary:

- **Mid-season** — every row written is stamped with the current season. Nothing changes operationally.
- **Season end (all 38 GWs finished)** — the next `fpl_engine.py` run does one final ingest, then archives the final `players_master` + `teams` snapshots into `players_season_archive` / `teams_season_archive` (preserving "who was player 233 in 2025/26?"). Runs after that exit early until FPL resets the API. `fpl_user_engine.py` exits early as soon as the season is complete.
- **New season (FPL API resets, typically early July)** — both engines pick up the new season label automatically; no manual action needed. The curated queries anchor on the latest season, so they switch over on their own (and return nothing in pre-season rather than showing last season's stats under re-issued IDs).

---

## Weekly brief (Phase 3D)

`fpl_brief_engine.py` projects every player over a 5-GW window, solves 15 transfer scenarios (free transfers 1-5 x hits 0/4/8) with rival-aware tie-breaking, evaluates chips, and writes one row to `weekly_brief`. The PWA is one screen with five cards — Transfers, Best XI, Captain, You vs rivals, Chips — and picks the scenario client-side.

Setup: apply `supabase/migrations/0014_weekly_brief.sql`, set `HEALTHCHECK_URL_BRIEF` in `.env` (optional), install the `com.fplsniper.brief` plist (see Scheduling above — it runs daily 9:30am + Saturday 10:30am WIB).

```bash
.venv/bin/python fpl_brief_engine.py             # real run: inserts a weekly_brief row
.venv/bin/python fpl_brief_engine.py --dry-run   # compute + log only; writes ~/Library/Logs/fplsniper/brief-dryrun.json, no DB write
.venv/bin/python -m pytest                       # test suite for brief/ and the engine
```

Before the season's first picks exist the engine records `skipped_preseason` in `pipeline_runs` and exits.

---

# Phase 2 — User & Rivals Ingestion

Additive layer on top of Phase 1. Captures **my own FPL squad** and the **squads of my rivals** across multiple mini-leagues per gameweek, then provides SQL queries to compare. Like Phase 1, this is a data-only phase — no chat, no LLM, no auth.

## What it adds

- **`fpl_user_engine.py`** — separate script that fetches user + rivals data and upserts into Supabase. Six-step pipeline: load config → my squad → league standings → rival squads → batch upsert → summary log.
- **Migration `0004_phase2_user_and_rivals.sql`** — adds four new tables: `tracked_leagues`, `user_team_snapshots`, `league_rivals`, `rival_team_snapshots`.
- **Four curated SQL queries** under `sql/queries/` for "me vs rivals" analysis.
- **One LaunchAgent with two firings** — Friday 5:30pm + Saturday 10am WIB (`com.fplsniper.user`).

Phase 1's `fpl_engine.py` is untouched. Phase 2 reads from Phase 1 tables (e.g. `players_master.ownership`) but doesn't write to them.

## Phase 2 setup

### 1. Apply the new migration

In Supabase SQL Editor, paste the contents of `supabase/migrations/0004_phase2_user_and_rivals.sql` and run. Creates the four new tables.

### 2. Configure tracked leagues

The script reads from `tracked_leagues` to know which leagues + my-team-id to use. Insert one row per league you want to follow. In Supabase SQL Editor:

```sql
INSERT INTO tracked_leagues (league_id, league_name, my_fpl_team_id, notes)
VALUES
  (298087, 'Cimanuk-ers',  453241, 'work league'),
  (123456, 'Friends 2025', 453241, 'main league');
```

- `league_id` — find in the FPL site URL when you open a league: `.../leagues/<league_id>/standings/c`
- `my_fpl_team_id` — find in your team page URL: `.../entry/<my_fpl_team_id>/`
- All rows can share the same `my_fpl_team_id` (this is the normal case)

### 3. Run

`.env` from Phase 1 is reused — no new variables.

```bash
.venv/bin/python fpl_user_engine.py
```

Expected: under 5 minutes for ~5 leagues × ~15 rivals/league. Re-running just updates rows (idempotent).

Look for the summary line at the end:
```
Phase 2 run complete: N leagues, N rivals, N squad snapshots, N pre-deadline skips, Ns
```

### 4. Scheduling — two runs per week

Handled by the `com.fplsniper.user` LaunchAgent (see **Scheduling — launchd** above): Friday 5:30pm WIB (30 minutes after Phase 1 finishes, so global data is fresh) and Saturday 10am WIB (captures rival squads after the typical Saturday-morning UK deadline — the canonical capture; Friday is a safety net).

## Important caveat — pre-deadline behavior

If `fpl_user_engine.py` runs before the GW deadline, the FPL picks endpoint returns either:
- **404** — for rivals whose squad hasn't been finalised for that GW, or
- **stale data** — last GW's picks, recognisable because `entry_history.event` doesn't match the target GW.

The script handles both: it logs `Rival X squad not yet finalized for GW Y, skipping` and continues. The skip count appears in the summary line. The Saturday 10am cron is the canonical capture for this reason.

For DGWs with earlier deadlines, add an ad-hoc manual run.

## The four SQL queries

Run any of these in Supabase SQL Editor:

| Query | Purpose |
|---|---|
| [`my_squad_vs_rivals.sql`](sql/queries/my_squad_vs_rivals.sql) | Your 15 picks ranked by % of rivals also owning them. Differentials at top. |
| [`rival_captain_consensus.sql`](sql/queries/rival_captain_consensus.sql) | How rivals are spreading their captaincy, with points scored. |
| [`rival_transfers_in_out.sql`](sql/queries/rival_transfers_in_out.sql) | Players being transferred in/out across rivals this GW. **Returns empty until the second weekly capture** — needs 2 GWs of data. |
| [`league_template_vs_global.sql`](sql/queries/league_template_vs_global.sql) | Players ≥50% owned by rivals but <30% globally — the mini-league template. |

All four queries anchor on the most recent GW present in `rival_team_snapshots`, so they keep working as more snapshots accumulate.

## Phase 2 schema cheat sheet

- **`tracked_leagues`** — config table. You insert rows manually. `(league_id, my_fpl_team_id)` per league you follow.
- **`user_team_snapshots`** — your squad per GW. PK `(season, fpl_team_id, gw)`. Includes captain, vice, chip, bench order, transfers, ranks, bank, team value.
- **`league_rivals`** — standings per league, replaced each run (rivals who leave a league are removed). PK `(league_id, rival_fpl_team_id)`.
- **`rival_team_snapshots`** — rivals' squads per GW. PK `(season, rival_fpl_team_id, gw)`. Same shape as `user_team_snapshots` minus personal-finance fields.

See `supabase/migrations/0004_phase2_user_and_rivals.sql` for full column definitions.

