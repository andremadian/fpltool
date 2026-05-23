# FPL Sniper — Phase 1 Build Brief

Paste this whole document into a new Claude Code session.

---

## What you're building

The data ingestion pipeline for **FPL Sniper**, a conversational-first Fantasy Premier League companion app. This is Phase 1 of 5 — a Python script that fetches FPL data daily and writes it to Supabase Postgres. No frontend yet. The goal is for me to be able to query the data via Supabase Studio as a standalone personal research tool, with the schema also ready for the conversational app I'll build in later phases.

## Deliverables

Produce these files in a clean project structure:

1. `supabase/migrations/0001_initial_schema.sql` — the full schema below, unmodified
2. `fpl_engine.py` — the daily ingestion script
3. `requirements.txt` — Python dependencies, pinned to compatible versions
4. `.env.example` — placeholder environment variables
5. `README.md` — setup, local run, and Railway deployment instructions
6. `.gitignore` — standard Python ignore + `.env`

No other files. Keep the project small and inspectable.

## Tech constraints

- **Python 3.11+**
- **Libraries:** `supabase` (supabase-py v2+), `pandas`, `requests`, `python-dotenv`
- **Synchronous only** — no async, no threading. Keep it simple.
- **Service-role key for Supabase**, loaded from environment, never hardcoded
- **Target deployment:** Railway free tier with cron schedule

## The schema

Use this exact SQL as the migration file. Do not modify column names, drop tables, or add tables. The user/conversation tables stay empty until Phase 3; do not populate them.

```sql
-- ============================================
-- FPL DATA TABLES (populated by Python script)
-- ============================================

create table teams (
  id int primary key,
  name text not null,
  short_name text not null,
  strength_overall_home int,
  strength_overall_away int
);

create table players_master (
  id int primary key,
  web_name text not null,
  team_id int references teams(id),
  position text not null,         -- GKP, DEF, MID, FWD
  price numeric(3,1) not null,
  total_points int default 0,
  ownership numeric(4,1) default 0,
  points_per_90 numeric(5,2),
  price_per_point numeric(5,2),
  cbit int default 0,
  xg numeric(5,2),
  xa numeric(5,2),
  xgi numeric(5,2),
  xgc numeric(5,2),
  ict_index numeric(6,2),
  form numeric(4,2),
  minutes int default 0,
  updated_at timestamptz default now()
);

create index on players_master (position);
create index on players_master (team_id);
create index on players_master (price);

create table player_history (
  player_id int references players_master(id),
  gw int not null,
  minutes int default 0,
  total_points int default 0,
  goals int default 0,
  assists int default 0,
  clean_sheets int default 0,
  xg numeric(5,2),
  xa numeric(5,2),
  xgi numeric(5,2),
  bps int default 0,
  cbit int default 0,
  price numeric(3,1),
  primary key (player_id, gw)
);

create index on player_history (gw);

create view team_history as
select
  pm.team_id,
  t.name as team_name,
  ph.gw,
  sum(ph.goals) as total_goals,
  sum(ph.xg) as total_xg,
  sum(ph.xa) as total_xa,
  sum(ph.clean_sheets) as cs_count
from player_history ph
join players_master pm on pm.id = ph.player_id
join teams t on t.id = pm.team_id
group by pm.team_id, t.name, ph.gw;

-- ============================================
-- USER & CONVERSATION TABLES (populated in Phase 3+, empty for now)
-- ============================================

create table users (
  id uuid primary key references auth.users(id) on delete cascade,
  fpl_team_id int,
  display_name text,
  created_at timestamptz default now()
);

create table user_rivals (
  user_id uuid references users(id) on delete cascade,
  league_id int not null,
  rival_fpl_team_id int not null,
  rival_name text,
  rival_squad jsonb,
  refreshed_at timestamptz default now(),
  primary key (user_id, league_id, rival_fpl_team_id)
);

create table conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  title text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid references conversations(id) on delete cascade,
  role text not null,
  content text not null,
  tool_calls jsonb,
  created_at timestamptz default now()
);

create index on messages (conversation_id, created_at);

create table user_profile (
  user_id uuid primary key references users(id) on delete cascade,
  summary text,
  updated_at timestamptz default now()
);

alter table users enable row level security;
alter table user_rivals enable row level security;
alter table conversations enable row level security;
alter table messages enable row level security;
alter table user_profile enable row level security;

create policy "users see own row" on users for all using (auth.uid() = id);
create policy "users see own rivals" on user_rivals for all using (auth.uid() = user_id);
create policy "users see own conversations" on conversations for all using (auth.uid() = user_id);
create policy "users see own messages" on messages for all using (
  conversation_id in (select id from conversations where user_id = auth.uid())
);
create policy "users see own profile" on user_profile for all using (auth.uid() = user_id);
```

## The Python script — `fpl_engine.py` spec

Four-step pipeline. Each step is a separate function called by `main()`.

### Step 1 — Fetch bootstrap-static

GET `https://fantasy.premierleague.com/api/bootstrap-static/`. Parse JSON. Returns ~2MB containing:
- `teams` — 20 Premier League clubs
- `elements` — ~650 players with all current stats
- `events` — gameweeks (used to determine current GW)

### Step 2 — Clean and write the snapshot tables

Use pandas to:

- **Teams:** extract `id`, `name`, `short_name`, `strength_overall_home`, `strength_overall_away`. Upsert into `teams` keyed on `id`.
- **Players:** drop unused columns from `elements` (kit codes, photo, news fields, transfer counts, etc.). Keep only what the schema needs.
- **Derived fields:**
  - `price = cost / 10`
  - `cbit = clearances_blocks_interceptions + tackles` IF the `tackles` field exists in the player record, ELSE just `clearances_blocks_interceptions`. Check field existence at runtime — do not assume.
  - `points_per_90 = (total_points * 90) / minutes` if minutes > 0 else None
  - `price_per_point = price / total_points` if total_points > 0 else None
  - `position` mapped from `element_type`: 1→GKP, 2→DEF, 3→MID, 4→FWD
  - `team_id` is the player's `team` field
  - `web_name` is the player's `web_name` field
  - `ownership` is the player's `selected_by_percent` field cast to numeric
  - `form` cast to numeric (it's a string in the API)
- Upsert into `players_master` keyed on `id`. **Upsert, not insert** — re-running the script must update existing rows, not create duplicates.

### Step 3 — Loop element-summary for history

For each player in `players_master` where `minutes > 0 OR cost_change_event != 0` (skip the rest to save time):

- GET `https://fantasy.premierleague.com/api/element-summary/{player_id}/`
- Parse the response's `history` array — one row per gameweek the player has played
- For each row, build a record matching the `player_history` schema. Fields map directly except:
  - `gw` ← `round`
  - `price` ← `value / 10`
  - `cbit` ← same logic as Step 2 (tackles field check)
- Sleep `random.uniform(0.1, 0.15)` between calls (jittered to avoid pattern-matching by the FPL API)
- Log progress every 50 players using Python's `logging` module at INFO level
- Wrap each player's loop iteration in try/except — if one player fails, log the error and continue. Do not let one bad player kill the whole run.

### Step 4 — Batch upsert player_history

Collect all history rows from Step 3 into a list. Upsert into `player_history` in batches of ~500 rows, keyed on `(player_id, gw)`. Log the total rows written.

## Environment variables

The script reads these from environment. Locally via `python-dotenv`; on Railway via dashboard env vars.

- `SUPABASE_URL` — project URL from Supabase dashboard (e.g., `https://abcdefgh.supabase.co`)
- `SUPABASE_SERVICE_ROLE_KEY` — the service-role key, **never** the anon key

`.env.example` contains these as placeholders. `.env` itself is in `.gitignore`.

## Quality bar

- All four steps are separate functions called by `main()`
- Functions are type-hinted and have a one-line docstring each
- Logging uses Python's `logging` module at INFO level, configured at the top of the script. No `print()` calls.
- Errors in the per-player loop are caught and logged; one bad player does not kill the run
- The script completes in under 15 minutes on Railway's free tier (~450 active players × ~130ms sleep + processing + Supabase round-trips)
- Code is readable by someone who is not a Python expert — favour clarity over cleverness

## What you don't need to build

- No web frontend
- No auth
- No tests (will add in a later phase)
- No CI/CD beyond Railway's GitHub integration
- Don't write to the user/conversation tables — they exist in the schema but stay empty until Phase 3
- Don't add observability tooling (Sentry, etc.) — Railway logs are enough for now

## Railway deployment instructions for the README

Explain to me, the user (assume I've never used Railway before):

1. How to push the repo to GitHub
2. How to create a Railway project from the GitHub repo
3. How to set the two environment variables in Railway's dashboard
4. How to configure a cron schedule of `0 3 * * *` (3am UTC daily, after FPL's nightly update)
5. How to view logs to verify the daily run succeeded
6. How to manually trigger a run from Railway's UI for testing

Keep the README under 200 lines. No marketing fluff, just steps.

## Done criteria

The brief succeeds if I can, with no follow-up questions to you:

1. Clone the repo
2. Create a Supabase project, paste the migration SQL into their SQL Editor, run it
3. Set my env vars locally in a `.env` file
4. Run `python fpl_engine.py` and see ~650 players in Supabase's Table Editor within 15 minutes
5. Deploy to Railway, set the cron, and verify the next day that data updated automatically

If any of those five steps requires me to ask you a follow-up question or write any code myself, the brief failed.

## Order of operations

Build in this order so I can verify as I go:

1. The schema migration file first
2. Then `requirements.txt`, `.env.example`, `.gitignore`
3. Then `fpl_engine.py` with Step 1 (just the fetch and a `print(len(data['elements']))` sanity check)
4. Then add Step 2 (the snapshot write)
5. Then add Step 3 + Step 4 (the history loop)
6. Finally the README

Tell me when each step is done so I can run the partial script locally and confirm before you add the next step.

---

**Start by acknowledging this brief and confirming your understanding, then build the schema file first.**
