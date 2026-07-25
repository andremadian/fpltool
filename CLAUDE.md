# CLAUDE.md — Project context for Claude Code

Read this first when working in this project. Detailed setup is in [README.md](README.md). The canonical source-of-truth for what each phase was supposed to build is the corresponding brief: [Phase 1](FPL_Sniper_Phase1_ClaudeCode_Brief.md), [Phase 2](FPL_Sniper_Phase2_ClaudeCode_Brief.md), [Phase 3B — PWA](FPL_Sniper_Phase3B_PWA_Brief.md) (the [agent brief](FPL_Sniper_Phase3B_ClaudeCode_Brief.md) is deferred). The ordered backlog is [docs/TODOS.md](docs/TODOS.md).

## What this project is

**FPL Sniper** — a conversational-first Fantasy Premier League companion app, built in 5 phases. It now has two halves: the **data ingestion pipeline** (Python engines → Supabase, Phases 1–3A) and the **PWA frontend** (`web/`, a React 4-tab installable app, Phase 3B).

The engines fetch FPL data on a schedule and write it to Supabase Postgres; the PWA reads it back through anon-key + RLS-locked curated views behind magic-link auth. (Supabase Studio is still available as a raw-SQL research surface.)

| Phase | Status | Scope |
|-------|--------|-------|
| 1. Global data ingestion | ✅ shipped | `fpl_engine.py` + Supabase schema |
| 2. User + rivals ingestion | ✅ shipped | `fpl_user_engine.py` + 4 new tables + 4 analytics SQL queries |
| 3A. Pre-season hardening | ✅ shipped (Jul 2026) | daily light run, `player_daily` + `pipeline_runs`, launchd, dead-man alerting, schema assert |
| 3B. Personal edge PWA | ✅ shipped (Jul 2026) | [PWA brief](FPL_Sniper_Phase3B_PWA_Brief.md): `web/` React+Vite 4-tab installable app (This week / Transfers / Rivals / Chart maker), magic-link auth, migrations 0008 (RLS security lockdown + curated views + `gameweeks`) + 0009 (projection views). Reads Supabase via anon key. $0/month. |
| 3C. Stats Explorer | ✅ shipped (Jul 2026) | 5th PWA tab: filterable/sortable players & teams tables (season + last-5), migration 0010 (4 explorer views). Reads Supabase via anon key. |
| — AI chat agent | ⏸ deferred (Jul 2026) | [Agent brief](FPL_Sniper_Phase3B_ClaudeCode_Brief.md) kept for revival as a PWA chat tab if fixed views prove insufficient |
| 4+. Sniper Brief, league surface | — | roadmap in [docs/EXPANSION_PLAN.md](docs/EXPANSION_PLAN.md) |

Strategic direction (ratified July 2026): **option A — personal edge tool, built league-product-compatible.** Full market review + roadmap in [docs/EXPANSION_PLAN.md](docs/EXPANSION_PLAN.md).

The `users`, `user_rivals`, `conversations`, `messages`, `user_profile` tables exist in the schema **but stay empty in Phases 1–2** — they're scaffolded for Phase 3+. Phase 2 deliberately uses its own tables (`user_team_snapshots`, `league_rivals`, etc.) that don't depend on Supabase Auth.

## How the pipelines work

The two engines run on separate launchd schedules and write to disjoint sets of tables. They share `.env` and the same Supabase client pattern but are otherwise independent (ops helpers like `assert_schema`/`log_pipeline_run`/`ping_healthcheck` are deliberately duplicated in each, same as `fetch_bootstrap`). Both engines: assert the expected schema at startup (fail loudly naming the missing migration), record every run in `pipeline_runs`, and ping a healthchecks.io URL if configured.

### Phase 1 — `fpl_engine.py` (global FPL data)

1. `fetch_bootstrap()` — GET `bootstrap-static`, returns ~840-player snapshot + 20 teams + gameweek data
2. `determine_season(data)` — derive season label (e.g. `2025/26`) from GW1's deadline year; every time-series row is stamped with it
3. `write_snapshot(data, supabase)` — cleans with pandas, upserts `teams` and `players_master`
4. `fetch_player_history(data, season)` — filters to active players (`minutes > 0 OR cost_change_event != 0`), loops `element-summary/{id}` with jittered sleep, returns flat list of GW history rows
5. `write_history(rows, supabase)` — batches upserts to `player_history` in chunks of 500
6. `fetch_fixtures(season)` + `write_fixtures(rows, supabase)` — upserts all 380 fixtures (FDR, kickoff, scores)

Season-end behavior: once every GW is `finished`, the run archives the final `players_master`/`teams` snapshots into `players_season_archive`/`teams_season_archive`, and subsequent runs exit early until the new season's API goes live (see decision #10).

Full end-to-end runtime: ~2.5 minutes. Idempotent — re-running just updates existing rows.

**Daily light mode** (`fpl_engine.py --daily`, added Phase 3A): one bootstrap call (~5s), refreshes `teams`/`players_master` and appends today's per-player row (price, ownership, transfers in/out, status/news/chance-of-playing, form) to `player_daily`. No history crawl, no fixtures. Same season-complete early exit.

### Phase 2 — `fpl_user_engine.py` (user + rivals)

Six-step pipeline called from `main()`:

1. `load_tracked_leagues(supabase)` — read config table; exit cleanly if empty
2. `fetch_bootstrap()` + `determine_season` + `determine_current_gw` — derive season label and current GW (falls back to `is_next` if between GWs); exit early if the season is complete (all GWs finished)
3. `fetch_and_write_my_squads(leagues, gw, season, supabase)` — for each unique `my_fpl_team_id`, GET picks + /history/, upsert `user_team_snapshots`
4. `write_league_standings(leagues, supabase)` — paginate `/leagues-classic/.../standings/`, exclude self, then **delete + re-insert** each league's `league_rivals` rows (so rivals who leave a league don't linger)
5. `load_unique_rival_ids` + `fetch_rival_squads(rival_ids, gw, season)` — dedupe rivals across leagues, GET picks per rival with jittered sleep, gracefully skip 404/stale (pre-deadline) responses
6. `write_rival_squads(rows, supabase)` — batch upsert in chunks of 200

Summary log line at end: `Phase 2 run complete: N leagues, N rivals, N squad snapshots, N pre-deadline skips, Ns`. Total runtime ~5–30s for typical league sizes.

## Local setup

Detailed in [README.md](README.md), but the short version:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# Apply supabase/migrations/*.sql in numeric order in Supabase SQL Editor
cp .env.example .env  # fill in SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
.venv/bin/python fpl_engine.py
```

Always run the engines via `.venv/bin/python` — the system Python has been wiped/replaced before (July 2026), which killed the global installs the pipelines relied on. Cron points at the venv for this reason.

`.env` is gitignored. `SUPABASE_SERVICE_ROLE_KEY` is the new-format `sb_secret_...` key from Settings → API Keys → Secret keys. **Not** the publishable key.

## Deployment

**Running on local macOS launchd LaunchAgents** (migrated from cron in July 2026 — launchd fires a missed job on wake from sleep; cron just skips it). The user prefers local scheduling for personal tools (see global memory). The README still documents Railway as an alternative if reliability requires it. Plists live in `launchd/` in the repo; installed copies in `~/Library/LaunchAgents/`.

- **`com.fplsniper.daily`:** every day 9am WIB — `fpl_engine.py --daily` (captures post-price-change state; FPL price changes land ~7:30am WIB)
- **`com.fplsniper.fetch`:** Friday 5pm WIB — `fpl_engine.py` (weekly full run)
- **`com.fplsniper.user`:** Friday 5:30pm + Saturday 10am WIB — `fpl_user_engine.py`
- **Logs:** `~/Library/Logs/fplsniper/cron.log` — both engines log to the same file. **Must live outside the repo:** this project sits in a Google-Drive-synced `~/Documents`, and launchd's spawn fails with `EX_CONFIG (78)` when it tries to open a `StandardOut/ErrPath` redirect file there (Drive dehydrates/TCC-protects it) — which silently killed *every* scheduled run, not just logging (fixed July 2026, see decision #12). Keep all launchd `StandardOut/ErrPath` values pointed at `~/Library/Logs/`, never `~/Documents`.
- **View:** `launchctl list | grep fplsniper` for agents, `tail ~/Library/Logs/fplsniper/cron.log` for runs, or query `pipeline_runs` in Supabase (one row per run, any outcome)
- **Alerting:** healthchecks.io dead-man switch — engines ping `HEALTHCHECK_URL_*` from `.env` on every run; a missing ping triggers an email. This (not launchd) is what catches a shut-down Mac or a wiped venv.
- **After editing a plist:** re-copy to `~/Library/LaunchAgents/` and `launchctl bootout` + `bootstrap` it (commands in README).
- **Pre-deadline rival picks:** the Friday 5:30pm run usually fires before the GW deadline, so rival picks return 404 or stale. The Saturday 10am run is the canonical capture; Friday is a safety net.

## Key decisions worth knowing

These departed from the brief and aren't obvious from reading the code alone.

**1. `supabase` pinned to 2.30.0, not 2.9.1.**
The brief said "supabase-py v2+". 2.9.1 was the obvious pin at the time but it rejects the new `sb_secret_*` API key format Supabase rolled out in late 2025 — throws "Invalid API key" before making any HTTP call. 2.30.0 accepts both old JWT keys and new format keys; no API changes.

**2. DGW aggregation inside `fetch_player_history`.**
The brief said the API returns "one row per gameweek the player has played". It actually returns **one row per fixture**. Double gameweeks (when a team plays twice in one GW due to cup reschedules) produce two history rows with identical `(player_id, gw)`, which violates the PK on upsert. The `_aggregate_double_gameweeks` helper sums stats across same-GW fixtures (minutes, goals, xG, etc.) and keeps first for `price` (it doesn't change within a GW). This is the semantically correct "what did the player do in GW28 in total" answer.

**3. Active-player filter uses in-memory bootstrap data, not Supabase round-trip.**
The brief said "for each player in `players_master` where `minutes > 0 OR cost_change_event != 0`". `cost_change_event` isn't in the `players_master` schema — it only exists in the bootstrap API response. So the filter runs on the in-memory `elements` list inside `fetch_player_history(data)`. Avoids an unnecessary Supabase query.

**4. Runtime checks for `tackles` and `clearances_blocks_interceptions`.**
Per the brief, both for `cbit` calculation and as defensive hygiene. The FPL API has historically renamed/dropped these fields; defaulting to 0 if missing prevents the run from breaking on schema drift.

**5. RLS deliberately off for `teams`, `players_master`, `player_history`.**
The schema enables RLS only on user-related tables. FPL data is public anyway (the source API is public), and Phase 3+ will likely want anon read access for the conversational app. If Supabase Studio warns about this when applying the migration, click "Run without RLS" — that's intentional.

**6. Phase 2 migration is numbered `0004`, not `0003` as the brief specified.**
The Phase 2 brief said `0003_phase2_user_and_rivals.sql`, but `0003_add_fixtures.sql` already existed in the repo (added between the Phase 1 and Phase 2 briefs). Renumbering to 0004 keeps migrations monotonic; same content. README and CLAUDE.md reference the actual filename.

**7. Phase 2 rival rows include `entry_history` from the picks endpoint only.**
The brief said to fetch picks + /history/ for both me and rivals. For rivals, the picks endpoint already returns the necessary `entry_history` fields (event_transfers, event_transfers_cost, points), so we skip the extra /history/ call — halves the HTTP requests during the rival loop. My own squad still uses both endpoints because we need the financial fields (bank, team_value, overall_rank) which live in the dedicated /history/ payload's per-GW rows.

**8. Phase 2 "current GW" anchors on `rival_team_snapshots`, not bootstrap-static.**
All four SQL queries use `max(gw) from rival_team_snapshots` as their reference GW, not the live FPL "current" GW. Reason: if the latest cron run hit pre-deadline skips, rival data lags by a GW. Anchoring on the rivals table makes the comparison always meaningful — falls back to the most recent GW where the data actually exists.

**9. Phase 2's pre-deadline skip detection checks two signals.**
Some pre-deadline rivals return `404` from the picks endpoint, others return last GW's data (stale) with `entry_history.event != current_gw`. Both are skipped; the count surfaces in the summary line. This is the documented FPL caching quirk — the brief explicitly calls it out.

**10. Season rollover: `season` column + identity archives (migration 0005).**
FPL re-issues player IDs, team IDs (1–20) and fixture IDs every season. Migration 0005 added a `season` column (text, `'2025/26'` format, derived from GW1's deadline year) to `player_history`, `fixtures`, `user_team_snapshots`, `rival_team_snapshots`, rebuilt each PK to include it, and both engines stamp it on every row. Because next season's ingestion overwrites `players_master`/`teams` with re-issued IDs, `fpl_engine.py` archives the final snapshots into `players_season_archive`/`teams_season_archive` at season end (all GWs finished), then exits early on subsequent off-season runs until the new API goes live. Historical-season joins to `players_master`/`teams` are **wrong by design** — join the archive tables instead. All curated queries filter to the latest season (Phase 1 queries anchor on `max(season) from fixtures`, Phase 2 queries on the latest `(season, gw)` in `rival_team_snapshots`), so they never blend seasons and switch over automatically.

**11. Phase 3A hardening: instrumented runs + launchd + daily light mode (July 2026).**
Motivated by a real incident: the July 2026 system-Python wipe deleted `.venv/`, and four scheduled cron runs failed/vanished with zero alerting (harmless only because the season had ended). Both engines now (a) assert the expected schema at startup and exit loudly naming the missing migration, (b) insert a row into `pipeline_runs` for every run including early exits, and (c) ping healthchecks.io if `HEALTHCHECK_URL_*` is set — absence of a ping is the alert. Scheduling moved from cron to launchd (`launchd/` plists) because launchd fires missed jobs on wake. The daily `--daily` mode exists because price changes and injury news move daily but the old cadence only looked on Fridays. `pipeline_runs` is also what Phase 3B's agent freshness check will read.

**12. launchd log paths must live outside `~/Documents` (Google Drive) — July 2026.**
The repo lives in a Google-Drive-synced `~/Documents`. The plists originally redirected `StandardOut/ErrPath` to the in-repo `logs/cron.log`. When Google Drive dehydrated that file (it hadn't been written since the season ended) / TCC protection kicked in, **launchd could no longer open it and aborted the spawn with `EX_CONFIG (78)` before the engine ran at all** — so every scheduled run silently stopped executing (only `pipeline_runs` from earlier hydrated-file runs remained; the log froze). The tell: manual runs from an interactive shell worked (shell has Documents access + hydrates the file), launchd runs didn't; the engine has no `sys.exit(78)` — 78 came from launchd itself. Fix: all three plists now point `StandardOut/ErrPath` at `~/Library/Logs/fplsniper/cron.log` (local, non-Drive, non-TCC). This restored both logging **and** the schedule. Rule: never point a launchd redirect (or any file a background agent must open) inside `~/Documents`/`~/Desktop`/`~/Downloads`. The `.venv` is not Drive-synced, so the Python program itself still spawns fine.

**13. Stats Explorer views anchor on the latest *finished-fixture* season and resolve identity from the archives (migration 0011, Phase 3C) — the season-rollover trap made real.**
The 0010 explorer views hit decision #10 head-on at the first live rollover. Once the 2026/27 API opened, `fixtures` gained 380 unplayed 2026/27 rows and `players_master`/`teams` were overwritten with re-issued 2026/27 IDs, while `player_history`/`team_history` were still 2025/26. Result: team views anchored on `max(season) from fixtures` = 2026/27 → 0 finished games → all-zero metrics; player views summed 2025/26 history but joined it to the 2026/27 `players_master` by id → **every name mis-attributed** (Haaland's 27-goal season, old id 430, showed as whoever holds new id 430); `form`/`ownership`/`ict` were the 2026/27 pre-season snapshot (form 0 for ~740). Migration 0011 rewrites all four views to: (a) anchor on `max(season) from fixtures where finished = true` (2025/26 now, auto-advances to 2026/27 at GW1); (b) resolve player/team identity from `players_season_archive`/`teams_season_archive` when the anchor season is archived (completed), else from live `players_master`/`teams`; (c) sum every counting/expected stat from `player_history` for the anchor season (never from the live snapshot), recomputing team xG/xA/xGC through the archive player→team map rather than the `team_history` view (which is itself mis-keyed for a past season). Live-only fields (form/ownership/ict/status, team strength) are NULL → "—" for a completed season and populate automatically once the current season has played games. **Still latently mis-keyed for a past season (not yet fixed): `team_history` and `player_season_stats` views, and `player_daily` id lookups** — so the explorer's tap-to-expand sparklines (which read `player_daily`/`player_season_stats` by the archive id) show the wrong live player until 2026/27 GW1; Charts/Transfers read `player_season_stats` too. Fixing those is the same archive-resolver pattern, deferred.

## Files

```
.
├── CLAUDE.md                              # this file
├── README.md                              # human-facing setup + deploy guide
├── FPL_Sniper_Phase1_ClaudeCode_Brief.md  # Phase 1 brief (source of truth)
├── FPL_Sniper_Phase2_ClaudeCode_Brief.md  # Phase 2 brief (source of truth)
├── fpl_engine.py                          # Phase 1 ingestion script (global FPL data)
├── fpl_user_engine.py                     # Phase 2 ingestion script (user + rivals)
├── requirements.txt                       # pinned deps (shared)
├── .env.example                           # env var template (shared)
├── .env                                   # local-only, gitignored
├── .gitignore
├── logs/                                  # gitignored; legacy in-repo log dir (launchd now logs to ~/Library/Logs/fplsniper/, see decision #12)
├── launchd/                               # LaunchAgent plists (scheduling)
├── web/                                   # Phase 3B PWA — React + Vite + TS (see below)
│   ├── src/tabs/                          # ThisWeek / Transfers / Rivals / Charts
│   ├── src/components/                    # Login, Shell, FreshnessBadge, OfflineBanner, Sparkline, ToastContext
│   ├── src/hooks/                         # useAuth, useSupabaseQuery
│   ├── src/lib/                           # supabaseClient, season
│   ├── .env.local                         # gitignored; VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
│   └── package.json                       # npm run dev / build / preview
├── sql/
│   └── queries/                           # curated analytics queries (Phase 1 + 2)
└── supabase/
    └── migrations/
        ├── 0001_initial_schema.sql        # base schema
        ├── 0002_add_xgc_to_history.sql    # per-GW xgc
        ├── 0003_add_fixtures.sql          # fixtures table
        ├── 0004_phase2_user_and_rivals.sql  # user + rivals tables
        ├── 0005_season_rollover.sql       # season column + identity archives
        ├── 0006_player_availability_fields.sql  # status/news/transfer-momentum on players_master
        ├── 0007_player_daily_and_pipeline_runs.sql  # daily time series + run log
        ├── 0008_pwa_foundation.sql        # Phase 3B — RLS lockdown, curated views, gameweeks, is_me
        ├── 0009_projection_views_player_id.sql  # Phase 3B — projection views
        ├── 0010_stats_explorer_views.sql   # Phase 3C — player/team × season/last5 stats views
        └── 0011_stats_explorer_season_fix.sql  # Phase 3C — anchor on finished-fixture season + archive identity
```

(Plus `.venv/` — gitignored project venv the engines run through; `web/node_modules/` + `web/dist/` — gitignored; and `docs/` — phase-planning context for Claude Chat.)

## The PWA (`web/`)

Phase 3B frontend: a React 19 + Vite + TypeScript installable PWA, $0/month, reads Supabase directly with the **anon key** (never the service role key) through RLS-locked curated views. Magic-link auth (`Login.tsx` → `useAuth.tsx`); the signed-in user is matched to their data via the `is_me` flag / `gameweeks` + curated views from migration 0008. Five tabs in `src/tabs/`: **This week**, **Transfers**, **Rivals** (war room), **Stats** (explorer — filterable/sortable player & team tables from the `*_explorer_*` views), **Chart maker** (bubble chart). A `FreshnessBadge` reads `pipeline_runs` so the UI shows how stale the data is; `OfflineBanner` handles offline. Run locally with `cd web && npm run dev` (Vite on :5173, localhost-only — add `-- --host` for phone/PWA testing). The engines and the PWA are decoupled: the PWA only reads what the engines write, so **never** change ingestion to satisfy a UI need without updating the curated views (0008/0009) that sit between them.

## Schema cheat sheet

- **`teams`** — 20 rows, one per Premier League club + strength ratings
- **`players_master`** — current snapshot, one row per player (~840 by mid-season), includes derived fields (`price`, `points_per_90`, `price_per_point`, `cbit`). `xgc` here is season cumulative. Since migration 0006 also carries availability (`status`, `news`, `chance_of_playing_next_round`) and transfer momentum (`transfers_in_event`/`out_event`, `cost_change_event` in £m).
- **`player_daily`** — Phase 3A. One row per `(season, player_id, as_of_date)`: price, ownership, transfer momentum, availability, form. Written by the daily light run; the price-trend/news time series the weekly cadence can't see.
- **`pipeline_runs`** — Phase 3A. One row per engine run (any mode, any outcome): engine, season, gw, rows_written, duration, status, detail. Silence here means "the run never happened". Phase 3B's freshness check reads this.
- **`player_history`** — per-GW time series, PK `(season, player_id, gw)`. Stats are PER gameweek, not cumulative. Includes `xgc` per GW (added in migration 0002).
- **`team_history`** — view aggregating `player_history` to team level per (season, GW). `team_xgc` is `MAX(xgc)` across team's players (sum would overcount since xgc scales with minutes — see migration 0002 for rationale).
- **`fixtures`** — every fixture per season (past + future), PK `(season, id)`. Includes FDR (`home_difficulty`/`away_difficulty`), kickoff time, scores (null until `finished=true`). Added in migration 0003 for matchup projection queries.
- **`players_season_archive` / `teams_season_archive`** — who each re-issuable FPL ID referred to in a given season. Written automatically at season end; join these (not `players_master`/`teams`) for historical-season names. Added in migration 0005.
- **`tracked_leagues`** — Phase 2 config table. Manually populated. One row per league I want to follow; columns include `my_fpl_team_id` so the script knows whose perspective to capture.
- **`user_team_snapshots`** — Phase 2. My squad per GW. PK `(season, fpl_team_id, gw)`. Includes captain/vice/chip/bench/transfers/ranks/bank/team_value.
- **`league_rivals`** — Phase 2. Mini-league standings, replaced (delete + insert) each run so leavers don't linger. PK `(league_id, rival_fpl_team_id)`.
- **`rival_team_snapshots`** — Phase 2. Rivals' squads per GW. PK `(season, rival_fpl_team_id, gw)`. Same shape as `user_team_snapshots` minus personal-finance fields.
- **user/conversation tables** — empty in Phases 1–2; Phase 3+. Note: Phase 2 deliberately uses its own tables instead of these because the existing scaffold FKs to `auth.users` and Phase 2 has no login.
- **`player_explorer_season` / `player_explorer_last5`** — Phase 3C views. One row per player with the full metric set (goals/assists/xG/xA/xGI/xGC/CS/CBIT/BPS/ICT/points_per_90/points_per_million/…), season totals or last-5-GW form. Read by the Stats tab.
- **`team_explorer_season` / `team_explorer_last5`** — Phase 3C views. One row per club: W/D/L, GF/GA/GD, points, clean sheets (from finished `fixtures`), xG/xA/xGC (from `team_history`), strength ratings.

## Migrations

- **0001** — initial schema. Apply once via Supabase SQL Editor.
- **0002** — adds per-GW `xgc` to `player_history`; recreates `team_history` view with `team_xgc` (MAX, not SUM). Re-run `fpl_engine.py` after applying to backfill the new column.
- **0003** — adds `fixtures` table. Re-run `fpl_engine.py` after applying to populate.
- **0004** — Phase 2. Adds `tracked_leagues`, `user_team_snapshots`, `league_rivals`, `rival_team_snapshots`. Apply, then insert at least one row into `tracked_leagues`, then run `fpl_user_engine.py`. (Brief specified `0003_phase2_user_and_rivals.sql` but `0003` was taken — see decision #6.)
- **0005** — season rollover. Adds `season` to the four time-series tables (backfilled as `'2025/26'`), rebuilds their PKs, recreates `team_history` with season, and creates + seeds `players_season_archive`/`teams_season_archive`. **Must be applied before the first 2026/27 engine run** — the engines write a `season` column from this migration onward and fail against an un-migrated database.
- **0006** — Phase 3A. Adds availability + transfer-momentum columns to `players_master`. Idempotent (`add column if not exists`).
- **0007** — Phase 3A. Creates `player_daily` + `pipeline_runs`. Both engines' startup schema assert requires 0006 + 0007 — they exit loudly naming the missing migration until it's applied.
- **0008** — Phase 3B (PWA foundation). RLS security lockdown, `gameweeks` table, `is_me` matching, and the curated read-only views the PWA queries. This is what makes anon-key reads from the browser safe.
- **0009** — Phase 3B. Projection views keyed on `player_id`. The PWA reads these; the engines don't.
- **0010** — Phase 3C. Four `security_invoker` views (`player_explorer_season/last5`, `team_explorer_season/last5`) powering the Stats tab. Read-only; no engine changes. Apply via SQL Editor. **Superseded by 0011** at the season boundary — apply 0011 too.
- **0011** — Phase 3C. Rewrites the four explorer views to anchor on the latest *finished-fixture* season and resolve identity from the season archives (see decision #13). Fixes the all-zero team tab, mis-attributed names, and pre-season `form = 0` seen at the 2025/26→2026/27 rollover. Idempotent (`drop view if exists` + recreate). Apply via SQL Editor.

## Conventions

- Sync only (no async, no threading) — brief mandates this
- All logging via Python `logging` module at INFO level — no `print()` calls in committed code
- Type hints + one-line docstrings on every function
- Per-player loop wrapped in `try/except Exception` so one bad player doesn't kill the run
- Upserts (not inserts) so re-runs update in place
- "Code readable by someone who is not a Python expert — favour clarity over cleverness"

## When working on this project

- For Phase 1 changes: stay focused on the global ingestion pipeline (`fpl_engine.py` and the data tables it writes). Don't pre-emptively touch the user/conversation tables — those are Phase 3+ scope.
- For Phase 2 changes: stay in `fpl_user_engine.py` and the four Phase 2 tables. Do not modify `fpl_engine.py` or Phase 1 tables — the two engines are intentionally separate.
- For PWA (Phase 3B) changes: stay in `web/`. The frontend reads Supabase via the **anon key** through the RLS-locked curated views from migrations 0008/0009 — never wire it to the service-role key, and if it needs a new shape of data, add/adjust a curated view in a new migration rather than loosening RLS or having the browser hit base tables. Don't change the engines to satisfy a UI need without going through the views.
- For new phases: ask the user for the next brief before starting. Each phase has its own brief.
- For schema changes: never modify a migration file after it's been applied. Create a new migration file (next sequential number) and add it.
- For deployment changes: scheduling is launchd (`launchd/` plists in the repo, installed to `~/Library/LaunchAgents/`, labels `com.fplsniper.*`). Edit the repo copy, re-copy, and `launchctl bootout` + `bootstrap`. The crontab no longer has FPL entries — don't touch what's there (Transfez Market Monitoring).
