# CLAUDE.md — Project context for Claude Code

Read this first when working in this project. Detailed setup is in [README.md](README.md). The canonical source-of-truth for what each phase was supposed to build is the corresponding brief: [Phase 1](FPL_Sniper_Phase1_ClaudeCode_Brief.md), [Phase 2](FPL_Sniper_Phase2_ClaudeCode_Brief.md), [Phase 3B — PWA](FPL_Sniper_Phase3B_PWA_Brief.md) (the [agent brief](FPL_Sniper_Phase3B_ClaudeCode_Brief.md) is deferred). The ordered backlog is [docs/TODOS.md](docs/TODOS.md).

## What this project is

**FPL Sniper** — a conversational-first Fantasy Premier League companion app, built in 5 phases. It now has two halves: the **data ingestion pipeline** (three Python engines → Supabase, Phases 1–3A + 3D) and the **PWA frontend** (`web/`, a React installable app, now a one-screen weekly brief, Phase 3D).

The engines fetch FPL data on a schedule and write it to Supabase Postgres; the PWA reads the latest `weekly_brief` row back through anon-key + RLS behind magic-link auth. (Supabase Studio is still available as a raw-SQL research surface.)

| Phase | Status | Scope |
|-------|--------|-------|
| 1. Global data ingestion | ✅ shipped | `fpl_engine.py` + Supabase schema |
| 2. User + rivals ingestion | ✅ shipped | `fpl_user_engine.py` + 4 new tables + 4 analytics SQL queries |
| 3A. Pre-season hardening | ✅ shipped (Jul 2026) | daily light run, `player_daily` + `pipeline_runs`, launchd, dead-man alerting, schema assert |
| 3B. Personal edge PWA | ✅ shipped (Jul 2026) | [PWA brief](FPL_Sniper_Phase3B_PWA_Brief.md): `web/` React+Vite 4-tab installable app (This week / Transfers / Rivals / Chart maker), magic-link auth, migrations 0008 (RLS security lockdown + curated views + `gameweeks`) + 0009 (projection views). Reads Supabase via anon key. $0/month. |
| 3C. Stats Explorer | ✅ shipped (Jul 2026) | 5th PWA tab: filterable/sortable players & teams tables (season + last-5), migration 0010 (4 explorer views). Reads Supabase via anon key. |
| 3D. Weekly brief | ✅ shipped (Oct 2026) | `fpl_brief_engine.py` + `brief/` package + migration 0014 + `web/src/brief/`: one-screen PWA (five cards: Transfers, Best XI, Captain, You vs rivals, Chips) fed by one precomputed `weekly_brief` row per run. Replaces the five-tab PWA. Spec: [docs/superpowers/specs/2026-10-31-weekly-brief-design.md](docs/superpowers/specs/2026-10-31-weekly-brief-design.md). |
| — AI chat agent | ⏸ deferred (Jul 2026) | [Agent brief](FPL_Sniper_Phase3B_ClaudeCode_Brief.md) kept for revival as a PWA chat tab if fixed views prove insufficient |
| 4+. Sniper Brief, league surface | — | roadmap in [docs/EXPANSION_PLAN.md](docs/EXPANSION_PLAN.md) |

Strategic direction (ratified July 2026): **option A — personal edge tool, built league-product-compatible.** Full market review + roadmap in [docs/EXPANSION_PLAN.md](docs/EXPANSION_PLAN.md).

The `users`, `user_rivals`, `conversations`, `messages`, `user_profile` tables exist in the schema **but stay empty in Phases 1–2** — they're scaffolded for Phase 3+. Phase 2 deliberately uses its own tables (`user_team_snapshots`, `league_rivals`, etc.) that don't depend on Supabase Auth.

## How the pipelines work

The three engines run on separate launchd schedules and write to disjoint sets of tables (the brief engine writes only `weekly_brief`). They share `.env` and the same Supabase client pattern but are otherwise independent (ops helpers like `assert_schema`/`log_pipeline_run`/`ping_healthcheck` are deliberately duplicated in each, same as `fetch_bootstrap`). All engines: assert the expected schema at startup (fail loudly naming the missing migration), record every run in `pipeline_runs`, and ping a healthchecks.io URL if configured.

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

### Phase 3D — `fpl_brief_engine.py` (weekly brief)

Third engine, same ops conventions (`wait_for_supabase`, `assert_schema` requiring 0014, `pipeline_runs` row on every run, `HEALTHCHECK_URL_BRIEF` ping). Modules live in `brief/` (`data`, `fpl_api`, `model`, `window`, `squad`, `optimise`, `rivals`, `chips`, `payload`, …); tests in `tests/` (`.venv/bin/python -m pytest`).

1. Read this season's `player_history`/`player_daily` from Supabase and the live bootstrap, fixtures, my picks/history/transfers and rivals' picks from the FPL API; target GW = first GW whose deadline is in the future
2. Project every player over a 5-GW window (decayed form, fixture strength from opponent xG/xGC, minutes security, set pieces — model constants in `brief/model.py`, set-piece takers in `brief/set_pieces.py`)
3. Decide rival mode (Defend/Chase), then solve 15 scenarios (FT 1–5 x hits 0/4/8) with a scipy `milp`, plus Free Hit / Wildcard / Bench Boost / Triple Captain evaluations
4. Insert one row into `weekly_brief` (`payload` jsonb holds all scenarios, chips, rival comparison and the inputs used so a wrong answer can be traced)

`--dry-run` computes the payload, logs the summary and writes JSON to `~/Library/Logs/fplsniper/brief-dryrun.json` without touching the DB. Known limit: the public API can't see transfers queued for the upcoming GW, so the brief assumes none were made since the last deadline.

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
- **`com.fplsniper.fetch`:** Friday 5pm WIB — `fpl_engine.py` (weekly full run). Fires ~7.5h *before* the GW deadline, so it refreshes fixtures/FDR for the upcoming GW but cannot see the coming weekend's results — that's `postgw`'s job (see decision #15).
- **`com.fplsniper.postgw`:** Tuesday 9am WIB — `fpl_engine.py` (full run, after the gameweek has actually finished). This is the run that lands `player_history` and finished `fixtures` for the GW just played, and therefore what the (now retired) Stats Explorer read; the brief engine reads it too.
- **`com.fplsniper.user`:** Friday 5:30pm + Saturday 10am WIB — `fpl_user_engine.py`
- **`com.fplsniper.brief`:** every day 9:30am + Saturday 10:30am WIB — `fpl_brief_engine.py` (after the 9:00 daily/postgw runs have refreshed Supabase; Saturday slot lands after the canonical rival capture)
- **`com.fplsniper.heartbeat`:** Thursday 8pm WIB — `health_check.py --notify` (report only, writes nothing)
- **`com.fplsniper.web`:** always on — the Vite dev server on a pinned `http://localhost:5173` (`RunAtLoad` + `KeepAlive`, so it starts at login and restarts if it dies). This is the bookmarkable local PWA until it moves to Vercel. Logs to `~/Library/Logs/fplsniper/web.log`, not `cron.log`. `--strictPort` is deliberate: without it Vite silently falls back to 5174 and the bookmark breaks.
- **Logs:** `~/Library/Logs/fplsniper/cron.log` — all three engines log to the same file. **Must live outside the repo:** this project sits in a Google-Drive-synced `~/Documents`, and launchd's spawn fails with `EX_CONFIG (78)` when it tries to open a `StandardOut/ErrPath` redirect file there (Drive dehydrates/TCC-protects it) — which silently killed *every* scheduled run, not just logging (fixed July 2026, see decision #12). Keep all launchd `StandardOut/ErrPath` values pointed at `~/Library/Logs/`, never `~/Documents`.
- **View:** `launchctl list | grep fplsniper` for agents, `tail ~/Library/Logs/fplsniper/cron.log` for runs, or query `pipeline_runs` in Supabase (one row per run, any outcome)
- **Weekly heartbeat:** `health_check.py` — read-only report over `pipeline_runs` + the time-series tables (season state, next deadline, runs-vs-expected per engine over 7 days, data staleness, current-vs-stale `players_master` split, `tracked_leagues` sanity). Exits 1 if any warning fires or the send fails. Run it any time with `.venv/bin/python health_check.py`; `--notify` also pushes it to Telegram (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env`). Scheduled Thursday 8pm WIB deliberately — the evening before a typical Friday-morning deadline, so there's still time to fix a broken pipeline before it costs points. This covers "is the data sane"; healthchecks.io below covers "did the run happen at all".
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
The 0010 explorer views hit decision #10 head-on at the first live rollover. Once the 2026/27 API opened, `fixtures` gained 380 unplayed 2026/27 rows and `players_master`/`teams` were overwritten with re-issued 2026/27 IDs, while `player_history`/`team_history` were still 2025/26. Result: team views anchored on `max(season) from fixtures` = 2026/27 → 0 finished games → all-zero metrics; player views summed 2025/26 history but joined it to the 2026/27 `players_master` by id → **every name mis-attributed** (Haaland's 27-goal season, old id 430, showed as whoever holds new id 430); `form`/`ownership`/`ict` were the 2026/27 pre-season snapshot (form 0 for ~740). Migration 0011 rewrites all four views to: (a) anchor on `max(season) from fixtures where finished = true` (2025/26 now, auto-advances to 2026/27 at GW1); (b) resolve player/team identity from `players_season_archive`/`teams_season_archive` when the anchor season is archived (completed), else from live `players_master`/`teams`; (c) sum every counting/expected stat from `player_history` for the anchor season (never from the live snapshot), recomputing team xG/xA/xGC through the archive player→team map rather than the `team_history` view (which is itself mis-keyed for a past season). Live-only fields (form/ownership/ict/status, team strength) are NULL → "—" for a completed season and populate automatically once the current season has played games. Migration **0012** applies the identical archive-resolver to the `player_season_stats` view (read by the Chart maker and the row-expand), and `PlayerDetail` now scopes its `player_daily` sparklines to the viewed season (so a re-issued ID can't surface the wrong player's price/ownership — they read "no daily history yet" for a completed season, since `player_daily` only holds current-season rows). Remaining latently mis-keyed: the `team_history` view — but its only consumers (the projection views) query it for the *current* season, where the `player_history`→`players_master` join is valid, so it's correct in every actual use.

**14. `players_master` accumulates past seasons; `last_seen_season` marks them (migration 0013) — mark, don't delete.**
The other half of decision #10. `players_master` is upserted by `id` and nothing ever deletes from it, but FPL re-issues player IDs every season. At the 2025/26→2026/27 rollover it held **841 rows against a 570-player new season**: 271 were last season's leftovers still carrying 2025/26 price, `total_points` and `team_id` (id 624 "Bowen" 187 pts, id 694 "Mukiele" 151). Deleting them is not an option — `player_history.player_id` FKs onto `players_master(id)` and each leftover ID has a full season of history behind it (id 624 has 38 rows), so a delete is either blocked or, cascaded, destroys 2025/26 history. Hence a `last_seen_season` stamp written on every snapshot upsert, backfilled from the latest `player_daily` batch and then the identity archive.
**What was and wasn't actually broken:** only the two `*_projection` views enumerate players by club (`join players_master pm on pm.team_id = u.home_team_id`), and team IDs 1–20 are re-issued too, so a leftover row could attach to whichever club inherited its old `team_id`. But their final select inner-joins `player_recent`, built from *current-season* `player_history` — a leftover has none, so it was already dropped before reaching output. The real cost was an inflated intermediate join plus a latent trap for any future view that reads `players_master` without a history join (a "top scorers" query would have ranked Bowen's 187 points first). 0013 filters where the leak starts so the views stop depending on that downstream accident. The two `*_recent_form` views join `pm.id` against current-season history and were never exposed — left unfiltered deliberately, so a season boundary where the engine hasn't re-stamped yet degrades to stale-but-present rather than empty.

**15. The full run needs a *post*-gameweek slot; `assert_schema` must not blame migrations for network blips (Aug 2026).**
Two independent faults surfaced together at the first live gameweek of 2026/27. (a) **Cadence:** `player_history` and `fixtures` are written *only* by the full `fpl_engine.py` run, scheduled Friday 17:00 WIB = Friday 10:00 UTC — but the GW deadline is Friday 17:30 UTC. So the full run always fired ~7.5h before the gameweek it was supposed to capture. After GW1 (finished Mon 24 Aug) the DB held **zero 2026/27 `player_history` rows** and all 380 fixtures still `finished=false`, so the 0011 explorer views' `max(season) from fixtures where finished = true` anchor correctly resolved to **2025/26** and the Stats tab served last season. The views were starved, not broken — an easy misdiagnosis, since "shows last season" looks exactly like the decision #13 bug it isn't. Fix: added `com.fplsniper.postgw`, Tuesday 09:00 WIB, running the same full engine after Monday-night matches and bonus confirmation. Friday stays for pre-deadline FDR. Rule of thumb: **the daily run keeps prices/news current; only a post-gameweek full run makes the Stats tab current.**
(b) **Masked errors:** `assert_schema` caught bare `Exception` and relabelled *every* failure as "apply supabase/migrations/XXXX.sql". On 22 Aug an `httpx.RemoteProtocolError: Server disconnected` (launchd fires a missed job the instant the Mac wakes, before WiFi reassociates) was reported as "apply 0008_pwa_foundation.sql" — an already-applied migration — and killed the Saturday user run with no retry, permanently losing that GW's rival capture. Both engines now `wait_for_supabase()` first (6 attempts, 15s backoff, mirroring `health_check.py`) and `assert_schema` only claims a missing migration for SQLSTATE `42703`/`42P01`; anything else is reported as a connection problem. A missing-schema error during the probe short-circuits the retries so a genuinely un-migrated DB still fails fast with the precise migration name.

**16. The projection model lives in the repo as the weekly-brief engine (Oct 2026).**
The GW-ahead model used to live in a scratchpad and was lost and rebuilt three times (GW6, GW8, GW9) — each rebuild from memory notes, each slightly different. `fpl_brief_engine.py` + `brief/` is that model made permanent, with tests. Shape: reads Supabase plus the live FPL API, writes only `weekly_brief`, precomputes 15 scenarios (FT 1–5 x hits 0/4/8) so the PWA picks one client-side (instant, works offline). Choices that aren't obvious from the code:
- **Rival data is fetched live**, not read from `league_rivals`/`rival_team_snapshots` — those only refresh Fri/Sat, so Tue–Fri mode decisions would run on stale standings. League ID and my team ID still come from `tracked_leagues`. Fetched responses are stored only inside the payload; the user-engine tables are never touched.
- **Rival mode:** Defend or Chase; Chase targets the manager directly above me. A small ownership bonus enters the objective (`RIVAL_BONUS` 0.08), guarded so it only breaks near-ties: it may cost at most `NEAR_TIE_PTS` 2.0 raw points over the window, and captain candidates must be within `CAPTAIN_NEAR_TIE` 0.5 of the top captain basis. **Displayed numbers are always raw projections** — the bonus steers the choice, never the figures shown.
- **Last week's chips are normalised away:** when reading anyone's latest picks (rivals and me), a chip played last GW is ignored for squad shape, and Free Hit weeks are skipped in favour of the pre-Free-Hit squad — otherwise a Free Hit squad is mistaken for the real one.
- **Pre-season skip:** with no picks to read yet the run records `skipped_preseason` in `pipeline_runs` and writes nothing.
- **Flagged-minutes rule:** a GW with an availability flag (injury/doubt) is dropped from the minutes-security sample only when the player played 0 minutes that GW; a flagged player who still played keeps the GW, so a fit regular starter isn't projected to bench forever. If filtering empties the sample the unfiltered one is used.
- **Old curated views (0008–0013) stay in the DB unused**, and the old `sql/queries` files are left alone — dropping them isn't worth the risk, and the user edits those queries by hand.
- **The model is not backtested.** The constants come from the original scratchpad model's notes, not a fit to historical points; backtesting is in TODOS.

## Files

```
.
├── CLAUDE.md                              # this file
├── README.md                              # human-facing setup + deploy guide
├── FPL_Sniper_Phase1_ClaudeCode_Brief.md  # Phase 1 brief (source of truth)
├── FPL_Sniper_Phase2_ClaudeCode_Brief.md  # Phase 2 brief (source of truth)
├── fpl_engine.py                          # Phase 1 ingestion script (global FPL data)
├── fpl_user_engine.py                     # Phase 2 ingestion script (user + rivals)
├── fpl_brief_engine.py                    # Phase 3D weekly brief engine (projection + optimiser → weekly_brief)
├── health_check.py                        # read-only pipeline status report (weekly heartbeat)
├── requirements.txt                       # pinned deps (shared)
├── .env.example                           # env var template (shared)
├── .env                                   # local-only, gitignored
├── .gitignore
├── logs/                                  # gitignored; legacy in-repo log dir (launchd now logs to ~/Library/Logs/fplsniper/, see decision #12)
├── brief/                                 # weekly-brief modules (model, optimiser, rivals, chips, payload, FPL API)
├── tests/                                 # pytest suite for brief/ + engine (.venv/bin/python -m pytest)
├── launchd/                               # LaunchAgent plists (scheduling; daily/fetch/postgw/user/brief/heartbeat/web)
├── web/                                   # Phase 3B PWA — React + Vite + TS (see below)
│   ├── src/brief/                         # Brief screen, cards, useBrief, prefs (localStorage), types
│   ├── src/components/                    # Login, Shell, FreshnessBadge, OfflineBanner, ToastContext
│   ├── src/hooks/                         # useAuth, useSupabaseQuery
│   ├── src/lib/                           # supabaseClient, season (untracked — see docs/TODOS.md)
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
        ├── 0011_stats_explorer_season_fix.sql  # Phase 3C — anchor on finished-fixture season + archive identity
        ├── 0012_player_season_stats_season_fix.sql  # Phase 3C — same fix for player_season_stats (Charts + expand)
        ├── 0013_players_master_season_stamp.sql  # last_seen_season on players_master + projection view guard
        └── 0014_weekly_brief.sql          # weekly_brief output table (RLS owner-read)
```

(Plus `.venv/` — gitignored project venv the engines run through; `web/node_modules/` + `web/dist/` — gitignored; and `docs/` — phase-planning context for Claude Chat.)

## The PWA (`web/`)

A React 19 + Vite + TypeScript installable PWA, $0/month, reads Supabase directly with the **anon key** (never the service role key), magic-link auth (`Login.tsx` → `useAuth.tsx`). Since Phase 3D it is **one screen** (`src/brief/`), not five tabs: it reads the latest `weekly_brief` row and shows five cards — **Transfers**, **Best XI**, **Captain**, **You vs rivals**, **Chips**. Free-transfer and hit selectors pick one of the 15 precomputed scenarios client-side; the selection is remembered in `localStorage` (try/catch-wrapped, default FT 1 / no hits). `FreshnessBadge` reads `pipeline_runs` (now including the brief engine) and `OfflineBanner` handles offline. The old tabs (This week / Transfers / Rivals / Stats / Chart maker) and their views (0008–0013) are retired in the UI; the views remain in the DB unused (decision #16). It runs permanently on `http://localhost:5173` via the `com.fplsniper.web` LaunchAgent (see Deployment). For a one-off foreground run, `cd web && npm run dev` (localhost-only — add `-- --host` for phone testing, and stop the agent first or the port is taken). Because it's the **dev** server, the install prompt and service worker won't behave like production; that lands with Vercel. The engines and the PWA are decoupled: the PWA only reads what the engines write — a new data shape means changing the `weekly_brief` payload (and `web/src/brief/types.ts`) in a new migration/engine change, never loosening RLS or hitting base tables from the browser.

## Schema cheat sheet

- **`teams`** — 20 rows, one per Premier League club + strength ratings
- **`players_master`** — current snapshot, one row per player (~840 by mid-season), includes derived fields (`price`, `points_per_90`, `price_per_point`, `cbit`). `xgc` here is season cumulative. Since migration 0006 also carries availability (`status`, `news`, `chance_of_playing_next_round`) and transfer momentum (`transfers_in_event`/`out_event`, `cost_change_event` in £m). **Not purely current**: it's upserted by `id` and never deleted (`player_history` FKs onto it), so rows from earlier seasons linger under re-issued IDs — always filter on `last_seen_season` (migration 0013) to get "who plays now". See decision #14.
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
- **`weekly_brief`** — Phase 3D. One row per brief run: `season`, `gw`, `generated_at`, `mode` (defend/chase), `payload` jsonb (15 scenarios, chips, rival comparison, inputs used). Written by `fpl_brief_engine.py` with the service key; the PWA reads the latest row (RLS owner-read, no browser writes).
- **`player_explorer_season` / `player_explorer_last5`** — Phase 3C views. One row per player with the full metric set (goals/assists/xG/xA/xGI/xGC/CS/CBIT/BPS/ICT/points_per_90/points_per_million/…), season totals or last-5-GW form. Read by the retired Stats tab (UI removed in Phase 3D, see #16; views remain unused).
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
- **0009** — Phase 3B. Projection views keyed on `player_id`. Retired from the UI in Phase 3D (see #16); views remain in the DB unused.
- **0010** — Phase 3C. Four `security_invoker` views (`player_explorer_season/last5`, `team_explorer_season/last5`) powering the (now retired) Stats tab. Read-only; no engine changes. Apply via SQL Editor. **Superseded by 0011** at the season boundary — apply 0011 too.
- **0011** — Phase 3C. Rewrites the four explorer views to anchor on the latest *finished-fixture* season and resolve identity from the season archives (see decision #13). Fixes the all-zero team tab, mis-attributed names, and pre-season `form = 0` seen at the 2025/26→2026/27 rollover. Idempotent (`drop view if exists` + recreate). Apply via SQL Editor.
- **0012** — Phase 3C. Applies the same archive-resolver fix to the `player_season_stats` view (read by the since-retired Chart maker and player row-expand). Same idempotent drop+recreate. Apply via SQL Editor.
- **0013** — Adds `players_master.last_seen_season`, backfills it (from the latest `player_daily` batch, then the identity archive), and adds a season guard to the two `*_projection` views' club-enumeration join. **`fpl_engine.py`'s schema assert requires this** — the engine fails loudly until it's applied. Idempotent (`add column if not exists` + `create or replace view`). Apply via SQL Editor. See decision #14.
- **0014** — Phase 3D. Creates `weekly_brief` with RLS + the owner-read policy and revokes browser writes. **`fpl_brief_engine.py`'s schema assert requires this.** Idempotent. Apply via SQL Editor. See decision #16.

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
- For PWA changes: stay in `web/`. The frontend reads Supabase via the **anon key** only — never the service-role key — and only the `weekly_brief` row. A new data shape means changing `brief/payload.py` and `web/src/brief/types.ts` together; never loosen RLS or have the browser hit base tables. The retired 0008–0013 views are not a surface to build on.
- For weekly-brief changes: stay in `fpl_brief_engine.py`, `brief/` and `web/src/brief/`; keep `tests/` green (`.venv/bin/python -m pytest`). The engine writes only `weekly_brief` — don't have it write the user-engine tables.
- For new phases: ask the user for the next brief before starting. Each phase has its own brief.
- For schema changes: never modify a migration file after it's been applied. Create a new migration file (next sequential number) and add it.
- For deployment changes: scheduling is launchd (`launchd/` plists in the repo, installed to `~/Library/LaunchAgents/`, labels `com.fplsniper.*`). Edit the repo copy, re-copy, and `launchctl bootout` + `bootstrap`. The crontab no longer has FPL entries — don't touch what's there (Transfez Market Monitoring).
