# CLAUDE.md — Project context for Claude Code

Read this first when working in this project. Detailed setup is in [README.md](README.md). The canonical source-of-truth for what Phase 1 was supposed to build is [FPL_Sniper_Phase1_ClaudeCode_Brief.md](FPL_Sniper_Phase1_ClaudeCode_Brief.md).

## What this project is

**FPL Sniper** — a conversational-first Fantasy Premier League companion app, built in 5 phases. Phase 1 (this directory) is the **data ingestion pipeline** only. No frontend, no auth.

The script fetches FPL data daily and writes it to Supabase Postgres. The user queries the data via Supabase Studio as a personal research tool while the conversational app is built in later phases.

| Phase | Status | Scope |
|-------|--------|-------|
| 1. Data ingestion | ✅ shipped | Python script + Supabase schema |
| 2. (not yet briefed) | — | — |
| 3. Conversational layer | — | Populates `users`, `conversations`, `messages` tables |
| 4–5. (not yet briefed) | — | — |

The `users`, `user_rivals`, `conversations`, `messages`, `user_profile` tables exist in the schema **but stay empty in Phase 1** — they're scaffolded for Phase 3+.

## How the pipeline works

`fpl_engine.py` has four functions called from `main()`:

1. `fetch_bootstrap()` — GET `bootstrap-static`, returns ~840-player snapshot + 20 teams + gameweek data
2. `write_snapshot(data, supabase)` — cleans with pandas, upserts `teams` and `players_master`
3. `fetch_player_history(data)` — filters to active players (`minutes > 0 OR cost_change_event != 0`), loops `element-summary/{id}` with jittered sleep, returns flat list of GW history rows
4. `write_history(rows, supabase)` — batches upserts to `player_history` in chunks of 500

Full end-to-end runtime: ~2.5 minutes. Idempotent — re-running just updates existing rows.

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

- **Schedule:** Every Friday 5pm Jakarta time (`0 17 * * 5` in local timezone)
- **Cron tag:** `# fpl-sniper-fetch`
- **Logs:** `logs/cron.log` (gitignored via `*.log`)
- **View:** `crontab -l | grep fpl-sniper` to see the entry, `tail logs/cron.log` to inspect runs
- **Caveat:** Mac must be awake at scheduled time. If reliability matters, upgrade to `launchd` LaunchAgent.

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

## Files

```
.
├── CLAUDE.md                              # this file
├── README.md                              # human-facing setup + deploy guide
├── FPL_Sniper_Phase1_ClaudeCode_Brief.md  # original brief (source of truth)
├── fpl_engine.py                          # ingestion script (4 functions + helpers)
├── requirements.txt                       # pinned deps
├── .env.example                           # env var template
├── .env                                   # local-only, gitignored
├── .gitignore
├── logs/                                  # gitignored; cron output lands here
└── supabase/
    └── migrations/
        └── 0001_initial_schema.sql        # the canonical schema
```

## Schema cheat sheet

- **`teams`** — 20 rows, one per Premier League club + strength ratings
- **`players_master`** — current snapshot, one row per player (~840 by mid-season), includes derived fields (`price`, `points_per_90`, `price_per_point`, `cbit`). `xgc` here is season cumulative.
- **`player_history`** — per-GW time series, PK `(player_id, gw)`. Stats are PER gameweek, not cumulative. Includes `xgc` per GW (added in migration 0002).
- **`team_history`** — view aggregating `player_history` to team level per GW. `team_xgc` is `MAX(xgc)` across team's players (sum would overcount since xgc scales with minutes — see migration 0002 for rationale).
- **`fixtures`** — every fixture in the current FPL season (past + future). Includes FDR (`home_difficulty`/`away_difficulty`), kickoff time, scores (null until `finished=true`). Added in migration 0003 for matchup projection queries.
- **user/conversation tables** — empty in Phase 1; Phase 3+

## Migrations

- **0001** — initial schema. Apply once via Supabase SQL Editor.
- **0002** — adds per-GW `xgc` to `player_history`; recreates `team_history` view with `team_xgc` (MAX, not SUM). Re-run `fpl_engine.py` after applying to backfill the new column.
- **0003** — adds `fixtures` table. Re-run `fpl_engine.py` after applying to populate.

## Conventions

- Sync only (no async, no threading) — brief mandates this
- All logging via Python `logging` module at INFO level — no `print()` calls in committed code
- Type hints + one-line docstrings on every function
- Per-player loop wrapped in `try/except Exception` so one bad player doesn't kill the run
- Upserts (not inserts) so re-runs update in place
- "Code readable by someone who is not a Python expert — favour clarity over cleverness"

## When working on this project

- For Phase 1 changes: stay focused on the ingestion pipeline. Don't pre-emptively touch the user/conversation tables — those are Phase 3+ scope.
- For new phases: ask the user for the next brief before starting. Each phase has its own brief.
- For schema changes: never modify `0001_initial_schema.sql` after it's been applied. Create a new migration file (`0002_...`) and add it.
- For deployment changes: local cron entry is in `crontab -l`, tagged `# fpl-sniper-fetch`. Don't touch other entries (Transfez Market Monitoring uses the same crontab).
