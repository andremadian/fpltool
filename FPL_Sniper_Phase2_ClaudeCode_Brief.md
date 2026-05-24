# FPL Sniper — Phase 2 Build Brief

Paste this whole document into a new Claude Code session.

---

## What you're building

The **user and rival data ingestion pipeline** for FPL Sniper, building on Phase 1's ingestion engine. Phase 1 ingests global FPL data (all ~840 players, all 380 fixtures). Phase 2 ingests **my own FPL team's squad per gameweek** and **the squads of my rivals across multiple mini-leagues**, then adds SQL queries that let me answer "what does my squad look like compared to my rivals?" directly in Supabase Studio.

This is a data-only phase. No chat, no frontend, no LLM. Same paradigm as Phase 1: Python script writes to Supabase, SQL queries surface the analysis. Phase 3 will be the conversational layer on top.

## Existing context (Phase 1 — already shipped)

The Phase 1 repo (`github.com/andremadian/fpltool`) has:

- `fpl_engine.py` — daily Python script that ingests global FPL data
- `supabase/migrations/0001_initial_schema.sql` — original schema
- `supabase/migrations/0002_*.sql` — added `xgc` column to `player_history`
- `sql/queries/` — four curated analytics queries
- Cron: `0 17 * * 5` (Friday 5pm WIB), logs to `logs/cron.log`
- Tables populated: `teams`, `players_master`, `player_history`, `fixtures`
- Tables scaffolded but empty: `users`, `user_rivals`, `conversations`, `messages`, `user_profile`

Phase 2 is **additive**. Do not modify `fpl_engine.py` or any Phase 1 file. Create new files alongside them.

## Deliverables

Produce these files in the existing repo:

1. `supabase/migrations/0003_phase2_user_and_rivals.sql` — schema additions
2. `fpl_user_engine.py` — the user + rivals ingestion script
3. `sql/queries/my_squad_vs_rivals.sql`
4. `sql/queries/rival_captain_consensus.sql`
5. `sql/queries/rival_transfers_in_out.sql`
6. `sql/queries/league_template_vs_global.sql`
7. Append a Phase 2 section to the existing `README.md` (do not rewrite it)
8. Append a Phase 2 section to `CLAUDE.md` if it documents any deviation from this brief

No other files. Match Phase 1's project style.

## Tech constraints

- **Python 3.14** (same as Phase 1)
- **Reuse Phase 1's dependencies** — `supabase-py 2.30.0+`, `pandas`, `requests`, `python-dotenv`. Do not add new libraries unless strictly necessary.
- **Synchronous only**
- **Service-role key from environment** — reuse the same `.env` as Phase 1
- **Local cron deployment** (same paradigm as Phase 1) — Railway not in play

## The schema additions

Apply as a new migration file. Do not modify existing tables.

```sql
-- ============================================
-- PHASE 2 — USER & RIVALS DATA INGESTION
-- ============================================

-- Configuration: which leagues do I want to track?
-- Populated manually (insert rows for each league I want to follow).
-- The Python script reads from this table on each run.
create table tracked_leagues (
  league_id int primary key,
  league_name text,
  my_fpl_team_id int not null,         -- redundant per row but simpler than a separate "me" config
  notes text,
  added_at timestamptz default now()
);

-- My squad, snapshotted per gameweek.
-- One row per (my_fpl_team_id, gw).
create table user_team_snapshots (
  fpl_team_id int not null,
  gw int not null,
  player_ids int[] not null,           -- the 15 player IDs
  captain_id int,
  vice_captain_id int,
  chip_used text,                       -- 'wildcard', 'freehit', 'bboost', '3xc', or null
  bench_order int[],                    -- player_ids in bench order (positions 12,13,14,15)
  transfers_made int default 0,
  transfer_cost int default 0,          -- points deducted for hits
  event_points int,                     -- points scored that GW
  event_rank int,                       -- GW rank
  overall_rank int,                     -- overall rank after that GW
  bank numeric(3,1),                    -- money in the bank
  team_value numeric(4,1),              -- total team value
  refreshed_at timestamptz default now(),
  primary key (fpl_team_id, gw)
);

create index on user_team_snapshots (gw);

-- Mini-league standings, refreshed per run.
-- One row per (league_id, rival_fpl_team_id).
create table league_rivals (
  league_id int references tracked_leagues(league_id) on delete cascade,
  rival_fpl_team_id int not null,
  rival_name text,
  rival_player_name text,               -- the manager's real name (from FPL API)
  total_points int,
  league_rank int,
  last_rank int,                        -- previous GW's league rank (for movement)
  refreshed_at timestamptz default now(),
  primary key (league_id, rival_fpl_team_id)
);

create index on league_rivals (rival_fpl_team_id);

-- Rivals' squads per gameweek.
-- One row per (rival_fpl_team_id, gw). Same shape as user_team_snapshots.
create table rival_team_snapshots (
  rival_fpl_team_id int not null,
  gw int not null,
  player_ids int[] not null,
  captain_id int,
  vice_captain_id int,
  chip_used text,
  bench_order int[],
  transfers_made int default 0,
  transfer_cost int default 0,
  event_points int,
  refreshed_at timestamptz default now(),
  primary key (rival_fpl_team_id, gw)
);

create index on rival_team_snapshots (gw);
create index on rival_team_snapshots (rival_fpl_team_id, gw);
```

**Notes on the design:**

- `tracked_leagues` is a config table because you have >3 leagues. You insert rows manually via Supabase Studio SQL editor. No env vars for league IDs.
- `my_fpl_team_id` is stored per league row, not in `.env`, so the script can support tracking other people's perspectives in the future (e.g. "what would my friend's view look like?"). For now, all rows have the same `my_fpl_team_id`.
- We do **not** populate the existing `users` / `user_rivals` Phase-3 scaffold tables. Those wait for auth. Phase 2 uses its own tables that don't require Supabase Auth.
- `chip_used` is nullable text rather than an enum so future chip types (FPL adds new ones occasionally) don't require a migration.
- Forward-only ingestion: the script writes the current GW's data only. No backfill of historical GWs. If you want backfill later, it's a one-line loop change.

## The Python script — `fpl_user_engine.py` spec

Six-step pipeline. Each step is a separate function called by `main()`.

### Step 0 — Load config

Read all rows from `tracked_leagues`. If empty, log a warning and exit cleanly (don't error — you may not have added leagues yet). Determine `current_gw` from the existing `events` data accessible via bootstrap-static. Reuse the same logic as Phase 1 if it's already abstracted; otherwise re-fetch bootstrap-static (it's only 2MB).

### Step 1 — Fetch and write my squad

For each unique `my_fpl_team_id` in `tracked_leagues`:

- GET `https://fantasy.premierleague.com/api/entry/{team_id}/event/{current_gw}/picks/`
- GET `https://fantasy.premierleague.com/api/entry/{team_id}/history/` (for transfer count, hits, bank, team value)
- Build a row matching `user_team_snapshots` schema
- Upsert into `user_team_snapshots` keyed on `(fpl_team_id, gw)`

The picks endpoint returns:
- `picks` array (15 entries) with `element` (player_id), `position` (1-15, where 12-15 is bench), `is_captain`, `is_vice_captain`, `multiplier`
- `entry_history` with `event_transfers`, `event_transfers_cost`, `points`, `rank`, `overall_rank`, `bank`, `value`
- `active_chip` (string or null)

Map these into the schema. `player_ids` is the 11 starters in pitch order followed by 4 bench in `position` order. `bench_order` is just the last 4 (positions 12-15).

### Step 2 — Fetch league standings

For each `league_id` in `tracked_leagues`:

- GET `https://fantasy.premierleague.com/api/leagues-classic/{league_id}/standings/?page_standings=1`
- The response includes `standings.results` (up to 50 per page) and `standings.has_next`
- Paginate via `?page_standings=2`, etc., until `has_next` is false
- For each rival: extract `entry` (team_id), `entry_name`, `player_name`, `total`, `rank`, `last_rank`
- **Exclude my own team** from the rival list (filter where `entry == my_fpl_team_id`)
- Upsert into `league_rivals` keyed on `(league_id, rival_fpl_team_id)`

### Step 3 — Fetch rival squads

Build the set of unique `rival_fpl_team_id` values from `league_rivals` (deduplicated across leagues — the same person may be in multiple of your leagues).

For each unique rival:

- GET `/entry/{rival_id}/event/{current_gw}/picks/`
- Build a row matching `rival_team_snapshots`
- **Important caveat — pre-deadline behavior:** before the GW deadline, this endpoint returns 404 or stale (last GW's) data depending on FPL's caching. Handle both:
  - If 404 → log "rival X squad not yet finalized for GW Y, skipping" and continue
  - If the response's `event` field doesn't match `current_gw` → same handling
- Sleep `random.uniform(0.1, 0.15)` between requests (same jitter pattern as Phase 1)
- Log progress every 25 rivals
- Wrap each rival in try/except; one bad rival should not kill the run

### Step 4 — Batch upsert rival_team_snapshots

Collect all rival snapshots from Step 3 into a list. Upsert into `rival_team_snapshots` in batches of ~200 rows, keyed on `(rival_fpl_team_id, gw)`. Log the total rows written.

### Step 5 — Summary log

Log a single-line summary at INFO level:
```
Phase 2 run complete: {n_leagues} leagues, {n_rivals} rivals, {n_squads_written} squad snapshots, {n_skipped} pre-deadline skips, {duration}s
```

## Environment variables

Reuse Phase 1's `.env`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

No new env vars. `my_fpl_team_id` and `league_id` live in the `tracked_leagues` table.

## Quality bar

- Same standards as Phase 1: type-hinted, one-line docstrings, `logging` module (no `print`), idempotent upserts, errors in per-rival loop are caught and logged
- Script completes in under 5 minutes for ~5 leagues × ~15 rivals/league = ~75 unique rivals (most overlap)
- Code readable by someone who is not a Python expert

## Cron — two runs per week

Append to local crontab. Match Phase 1's tag convention.

```
# fpl-sniper-fetch (Phase 1) — already exists
0 17 * * 5 /path/to/python /path/to/fpl_engine.py >> /path/to/logs/cron.log 2>&1

# fpl-sniper-user (Phase 2)
30 17 * * 5 /path/to/python /path/to/fpl_user_engine.py >> /path/to/logs/cron.log 2>&1
0 10 * * 6  /path/to/python /path/to/fpl_user_engine.py >> /path/to/logs/cron.log 2>&1
```

- Friday 5:30pm WIB — 30 minutes after Phase 1 finishes, so global data is fresh when user data is written
- Saturday 10am WIB — captures rival squads after the typical Saturday-morning UK deadline (most weeks). For DGWs with earlier deadlines, you may add an ad-hoc run.

**Document in the README that:** if the script runs before the GW deadline, rival squads will be missing for that GW (the endpoint returns last GW's data or 404). The Saturday run is the canonical capture; the Friday run is a safety net in case Saturday's cron fails.

## The four curated SQL queries

### `sql/queries/my_squad_vs_rivals.sql`

Purpose: For the current GW, show each player in my squad alongside the % of my rivals (across all tracked leagues) who also own them. Differentials are at the top, template picks at the bottom.

Required columns: `player_name`, `team_short_name`, `position`, `price`, `i_own` (always true — keep for symmetry), `rivals_owning_count`, `total_rivals`, `rival_ownership_pct`, `total_points`, `form`.

Sort by `rival_ownership_pct` ascending.

### `sql/queries/rival_captain_consensus.sql`

Purpose: For the most recent GW with rival data, show which players were captained by how many rivals. Returns the captain distribution.

Required columns: `gw`, `captain_player_name`, `captain_team`, `n_rivals_captaining`, `pct_of_rivals_captaining`, `captain_points_scored` (joined from player_history.total_points × 2).

Sort by `n_rivals_captaining` descending.

### `sql/queries/rival_transfers_in_out.sql`

Purpose: For the most recent GW, show which players had the most rivals transferring them in or out. Compares each rival's squad to their previous-GW squad.

Required columns: `player_name`, `team_short_name`, `transfers_in_count`, `transfers_out_count`, `net_transfers`, `n_rivals_owning_now`, `pct_rival_ownership`.

Sort by `abs(net_transfers)` descending.

**Note:** This query requires at least two GWs of `rival_team_snapshots` data. For the first run after Phase 2 ships, this query returns empty. Document this in the README.

### `sql/queries/league_template_vs_global.sql`

Purpose: Find players who are heavily owned by my rivals but not globally — the "mini-league template" that differs from the FPL hivemind.

Required columns: `player_name`, `team_short_name`, `position`, `price`, `rival_ownership_pct`, `global_ownership_pct` (from `players_master.ownership`), `template_delta` (rival_pct − global_pct), `form`, `total_points`.

Filter: `rival_ownership_pct >= 50 AND global_ownership_pct < 30`.
Sort by `template_delta` descending.

## What you don't need to build

- No frontend, no chat, no LLM
- No auth (Phase 3)
- No tests
- No notifications, no digests
- No external data sources (FBref, Understat, injury feeds)
- No modifications to Phase 1 files

## Done criteria

Phase 2 succeeds if, with no follow-up questions:

1. I apply migration `0003_phase2_user_and_rivals.sql` via Supabase SQL Editor
2. I `INSERT` ~5 rows into `tracked_leagues` for my actual leagues via Supabase Studio
3. I run `python fpl_user_engine.py` and see populated rows in `user_team_snapshots`, `league_rivals`, and `rival_team_snapshots` within 5 minutes
4. I run each of the four SQL queries in Supabase SQL Editor and get sensible results (after the GW deadline has passed at least once)
5. I add the two new cron entries and the data updates automatically twice weekly

If any step requires me to ask a follow-up or write code myself, the brief failed.

## Order of operations

Build in this order so I can verify as I go:

1. The migration file first — apply it and confirm tables exist
2. The `tracked_leagues` insert pattern documented (a `sql/seed_leagues_example.sql` is optional and helpful)
3. `fpl_user_engine.py` with Step 0 + Step 1 only (my squad ingestion)
4. Add Step 2 (league standings)
5. Add Steps 3 + 4 (rival squads)
6. The four SQL queries
7. README + CLAUDE.md updates last

Tell me when each step is done so I can run the partial script locally and confirm before you add the next step.

---

**Start by acknowledging this brief and confirming your understanding, then build the migration file first.**
