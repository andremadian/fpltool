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
