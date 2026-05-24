# FPL Sniper — Phase 1 (Data Ingestion)

A daily Python script that fetches Fantasy Premier League data and writes it to Supabase Postgres. Phase 1 of 5 — no frontend yet. You query the data via Supabase Studio.

## Files

```
.
├── fpl_engine.py                          # the ingestion script
├── requirements.txt                       # Python dependencies
├── .env.example                           # template for local env vars
├── .gitignore
├── README.md
└── supabase/
    └── migrations/
        └── 0001_initial_schema.sql        # database schema
```

## What it does

Each run, the script:

1. Fetches the FPL `bootstrap-static` snapshot (teams, players, gameweeks)
2. Cleans the data with pandas and **upserts** teams + players into the snapshot tables
3. For every player with minutes played or a price change, fetches per-gameweek `element-summary` history
4. Aggregates double-gameweek fixtures (when a player plays twice in one GW) and batch-upserts all history rows

The full run takes ~2–3 minutes and is idempotent — re-running just updates rows.

---

## Local setup

### Prerequisites

- Python 3.11+
- A Supabase project (free tier is fine)

### 1. Clone and install

```bash
git clone <your-repo-url>
cd "Personal FPL Tool"
pip install -r requirements.txt
```

### 2. Apply the database schema

In your Supabase dashboard:
1. Open **SQL Editor**
2. Paste the entire contents of `supabase/migrations/0001_initial_schema.sql`
3. Click **Run**

You should see "Success. No rows returned." This is correct — `CREATE TABLE` statements don't return data. If Supabase shows a Row Level Security warning, click **"Run without RLS"** — the data tables (`teams`, `players_master`, `player_history`) are intentionally public-readable; RLS is only applied to user-related tables.

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Then edit `.env`:

- `SUPABASE_URL` — Settings → **Data API** → Project URL (looks like `https://<ref>.supabase.co`)
- `SUPABASE_SERVICE_ROLE_KEY` — Settings → **API Keys** → **Secret key** (`sb_secret_...`). ⚠️ **Not** the publishable key.

`.env` is gitignored — it will not be committed.

### 4. Run

```bash
python fpl_engine.py
```

Expected output: log lines for upserting teams (20), players (~840), history (~18,000+ rows). After it finishes, check Supabase Table Editor — all three FPL tables should be populated.

---

## Deploy to Railway (daily cron)

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
- **`player_history`** — per-gameweek time series (one row per `(player_id, gw)`, ~18k rows by end of season)
- **`team_history`** — view aggregating `player_history` to the team level
- **`users`, `user_rivals`, `conversations`, `messages`, `user_profile`** — empty in Phase 1; used by the conversational app in Phase 3+

See the brief or the migration file for full column definitions.

---

# Phase 2 — User & Rivals Ingestion

Additive layer on top of Phase 1. Captures **my own FPL squad** and the **squads of my rivals** across multiple mini-leagues per gameweek, then provides SQL queries to compare. Like Phase 1, this is a data-only phase — no chat, no LLM, no auth.

## What it adds

- **`fpl_user_engine.py`** — separate script that fetches user + rivals data and upserts into Supabase. Six-step pipeline: load config → my squad → league standings → rival squads → batch upsert → summary log.
- **Migration `0004_phase2_user_and_rivals.sql`** — adds four new tables: `tracked_leagues`, `user_team_snapshots`, `league_rivals`, `rival_team_snapshots`.
- **Four curated SQL queries** under `sql/queries/` for "me vs rivals" analysis.
- **Two new cron entries** — runs Friday 5:30pm + Saturday 10am WIB.

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
python3 fpl_user_engine.py
```

Expected: under 5 minutes for ~5 leagues × ~15 rivals/league. Re-running just updates rows (idempotent).

Look for the summary line at the end:
```
Phase 2 run complete: N leagues, N rivals, N squad snapshots, N pre-deadline skips, Ns
```

### 4. Cron — two runs per week

Append to your existing crontab (`crontab -e`). The Phase 1 entry (Friday 5pm) stays unchanged:

```cron
# fpl-sniper-user (Phase 2)
30 17 * * 5 /path/to/python /path/to/fpl_user_engine.py >> /path/to/logs/cron.log 2>&1
0  10 * * 6 /path/to/python /path/to/fpl_user_engine.py >> /path/to/logs/cron.log 2>&1
```

- **Friday 5:30pm WIB** — 30 minutes after Phase 1 finishes, so global data is fresh.
- **Saturday 10am WIB** — captures rival squads after the typical Saturday-morning UK deadline. This is the canonical capture; Friday is a safety net.

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
- **`user_team_snapshots`** — your squad per GW. PK `(fpl_team_id, gw)`. Includes captain, vice, chip, bench order, transfers, ranks, bank, team value.
- **`league_rivals`** — standings per league, refreshed each run. PK `(league_id, rival_fpl_team_id)`.
- **`rival_team_snapshots`** — rivals' squads per GW. PK `(rival_fpl_team_id, gw)`. Same shape as `user_team_snapshots` minus personal-finance fields.

See `supabase/migrations/0004_phase2_user_and_rivals.sql` for full column definitions.

