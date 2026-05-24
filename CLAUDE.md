# CLAUDE.md — Project context for Claude Code

Read this first when working in this project. Detailed setup is in [README.md](README.md). The canonical source-of-truth for what each phase was supposed to build is the corresponding brief: [Phase 1](FPL_Sniper_Phase1_ClaudeCode_Brief.md), [Phase 2](FPL_Sniper_Phase2_ClaudeCode_Brief.md).

## What this project is

**FPL Sniper** — a conversational-first Fantasy Premier League companion app, built in 5 phases. Phase 1 (this directory) is the **data ingestion pipeline** only. No frontend, no auth.

The script fetches FPL data daily and writes it to Supabase Postgres. The user queries the data via Supabase Studio as a personal research tool while the conversational app is built in later phases.

| Phase | Status | Scope |
|-------|--------|-------|
| 1. Global data ingestion | ✅ shipped | `fpl_engine.py` + Supabase schema |
| 2. User + rivals ingestion | ✅ shipped | `fpl_user_engine.py` + 4 new tables + 4 analytics SQL queries |
| 3. Conversational layer | — | Populates `users`, `conversations`, `messages` tables |
| 4–5. (not yet briefed) | — | — |

The `users`, `user_rivals`, `conversations`, `messages`, `user_profile` tables exist in the schema **but stay empty in Phases 1–2** — they're scaffolded for Phase 3+. Phase 2 deliberately uses its own tables (`user_team_snapshots`, `league_rivals`, etc.) that don't depend on Supabase Auth.

## How the pipelines work

The two engines run on separate cron schedules and write to disjoint sets of tables. They share `.env` and the same Supabase client pattern but are otherwise independent.

### Phase 1 — `fpl_engine.py` (global FPL data)

1. `fetch_bootstrap()` — GET `bootstrap-static`, returns ~840-player snapshot + 20 teams + gameweek data
2. `write_snapshot(data, supabase)` — cleans with pandas, upserts `teams` and `players_master`
3. `fetch_player_history(data)` — filters to active players (`minutes > 0 OR cost_change_event != 0`), loops `element-summary/{id}` with jittered sleep, returns flat list of GW history rows
4. `write_history(rows, supabase)` — batches upserts to `player_history` in chunks of 500

Full end-to-end runtime: ~2.5 minutes. Idempotent — re-running just updates existing rows.

### Phase 2 — `fpl_user_engine.py` (user + rivals)

Six-step pipeline called from `main()`:

1. `load_tracked_leagues(supabase)` — read config table; exit cleanly if empty
2. `fetch_bootstrap()` + `determine_current_gw(bootstrap)` — find current GW (falls back to `is_next` if between GWs)
3. `fetch_and_write_my_squads(leagues, gw, supabase)` — for each unique `my_fpl_team_id`, GET picks + /history/, upsert `user_team_snapshots`
4. `write_league_standings(leagues, supabase)` — paginate `/leagues-classic/.../standings/`, exclude self, upsert `league_rivals`
5. `load_unique_rival_ids` + `fetch_rival_squads(rival_ids, gw)` — dedupe rivals across leagues, GET picks per rival with jittered sleep, gracefully skip 404/stale (pre-deadline) responses
6. `write_rival_squads(rows, supabase)` — batch upsert in chunks of 200

Summary log line at end: `Phase 2 run complete: N leagues, N rivals, N squad snapshots, N pre-deadline skips, Ns`. Total runtime ~5–30s for typical league sizes.

## Local setup

Detailed in [README.md](README.md), but the short version:

```bash
pip install -r requirements.txt
# Apply supabase/migrations/0001_initial_schema.sql in Supabase SQL Editor
cp .env.example .env  # fill in SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
python3 fpl_engine.py
```

`.env` is gitignored. `SUPABASE_SERVICE_ROLE_KEY` is the new-format `sb_secret_...` key from Settings → API Keys → Secret keys. **Not** the publishable key.

## Deployment

**Running on local macOS cron**, not Railway. The user prefers local cron for personal tools (see global memory). The README still documents Railway as an alternative if reliability requires it.

- **Phase 1 schedule:** Friday 5pm WIB (`0 17 * * 5`), tag `# fpl-sniper-fetch`
- **Phase 2 schedule:** Friday 5:30pm WIB (`30 17 * * 5`) + Saturday 10am WIB (`0 10 * * 6`), tag `# fpl-sniper-user`
- **Logs:** `logs/cron.log` (gitignored via `*.log`) — both engines log to the same file
- **View:** `crontab -l | grep fpl-sniper` to see entries, `tail logs/cron.log` to inspect runs
- **Caveat:** Mac must be awake at scheduled time. If reliability matters, upgrade to `launchd` LaunchAgent.
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
├── logs/                                  # gitignored; both engines log here
├── sql/
│   └── queries/                           # curated analytics queries (Phase 1 + 2)
└── supabase/
    └── migrations/
        ├── 0001_initial_schema.sql        # base schema
        ├── 0002_add_xgc_to_history.sql    # per-GW xgc
        ├── 0003_add_fixtures.sql          # fixtures table
        └── 0004_phase2_user_and_rivals.sql  # user + rivals tables
```

## Schema cheat sheet

- **`teams`** — 20 rows, one per Premier League club + strength ratings
- **`players_master`** — current snapshot, one row per player (~840 by mid-season), includes derived fields (`price`, `points_per_90`, `price_per_point`, `cbit`). `xgc` here is season cumulative.
- **`player_history`** — per-GW time series, PK `(player_id, gw)`. Stats are PER gameweek, not cumulative. Includes `xgc` per GW (added in migration 0002).
- **`team_history`** — view aggregating `player_history` to team level per GW. `team_xgc` is `MAX(xgc)` across team's players (sum would overcount since xgc scales with minutes — see migration 0002 for rationale).
- **`fixtures`** — every fixture in the current FPL season (past + future). Includes FDR (`home_difficulty`/`away_difficulty`), kickoff time, scores (null until `finished=true`). Added in migration 0003 for matchup projection queries.
- **`tracked_leagues`** — Phase 2 config table. Manually populated. One row per league I want to follow; columns include `my_fpl_team_id` so the script knows whose perspective to capture.
- **`user_team_snapshots`** — Phase 2. My squad per GW. PK `(fpl_team_id, gw)`. Includes captain/vice/chip/bench/transfers/ranks/bank/team_value.
- **`league_rivals`** — Phase 2. Mini-league standings refreshed each run. PK `(league_id, rival_fpl_team_id)`.
- **`rival_team_snapshots`** — Phase 2. Rivals' squads per GW. PK `(rival_fpl_team_id, gw)`. Same shape as `user_team_snapshots` minus personal-finance fields.
- **user/conversation tables** — empty in Phases 1–2; Phase 3+. Note: Phase 2 deliberately uses its own tables instead of these because the existing scaffold FKs to `auth.users` and Phase 2 has no login.

## Migrations

- **0001** — initial schema. Apply once via Supabase SQL Editor.
- **0002** — adds per-GW `xgc` to `player_history`; recreates `team_history` view with `team_xgc` (MAX, not SUM). Re-run `fpl_engine.py` after applying to backfill the new column.
- **0003** — adds `fixtures` table. Re-run `fpl_engine.py` after applying to populate.
- **0004** — Phase 2. Adds `tracked_leagues`, `user_team_snapshots`, `league_rivals`, `rival_team_snapshots`. Apply, then insert at least one row into `tracked_leagues`, then run `fpl_user_engine.py`. (Brief specified `0003_phase2_user_and_rivals.sql` but `0003` was taken — see decision #6.)

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
- For new phases: ask the user for the next brief before starting. Each phase has its own brief.
- For schema changes: never modify a migration file after it's been applied. Create a new migration file (next sequential number) and add it.
- For deployment changes: cron entries are in `crontab -l`, tagged `# fpl-sniper-fetch` (Phase 1) and `# fpl-sniper-user` (Phase 2). Don't touch other entries (Transfez Market Monitoring uses the same crontab).
