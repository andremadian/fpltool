# FPL Sniper — Phase 3B Brief: Personal Edge PWA (Claude Code)

## What you're building

An installable progressive web app — the personal decision surface for FPL Sniper. Four screens over the data Phases 1–3A already collect: **This week** (deadline countdown, captain projections, alerts), **Transfers** (projection/form tables with price-trend sparklines), **Rivals** (league war room), and **Chart maker** (pick any two metrics for x/y, a third for bubble size). Locked behind Supabase magic-link auth for one user. **No AI, $0/month recurring.**

This replaces the conversational agent as Phase 3B (decision ratified July 2026 — see [docs/EXPANSION_PLAN.md](docs/EXPANSION_PLAN.md)). The agent brief ([FPL_Sniper_Phase3B_ClaudeCode_Brief.md](FPL_Sniper_Phase3B_ClaudeCode_Brief.md)) is **deferred, not deleted** — its design (read-only RPC, evals, grounding rule) gets reused if/when chat earns its API cost, likely as a tab inside this PWA.

## Loopholes identified and closed

These are baked into the deliverables below — listed here so none get silently dropped.

| # | Loophole | Closure |
|---|---|---|
| 1 | **The anon key grants writes.** RLS is off on all global + Phase 2 tables (deliberate in decision #5, safe while no key ever left the machine). A PWA ships the anon key in its JS bundle by definition → anyone reading the bundle could **upsert/delete your entire database** via PostgREST. | Migration 0008 lockdown: revoke ALL from `anon`, revoke writes from `authenticated`, enable RLS on **every** public table with a select-only, email-allowlisted policy. Engines are unaffected (service role bypasses RLS) — verified by a done criterion. |
| 2 | **Magic-link ≠ private.** Supabase signups are open by default: anyone could request a magic link for *their own* email and become `authenticated`. | Two independent layers: (a) disable public signups in Supabase Auth settings; (b) every RLS policy checks `auth.jwt()->>'email' = 'andremadian@itsjack.com'` — a rogue authenticated user still reads nothing. |
| 3 | **Views bypass RLS.** Postgres views default to owner privileges (`security_invoker = off`), silently skipping base-table policies. | All new views created `with (security_invoker = on)`; existing `team_history` altered likewise. |
| 4 | **No deadline data exists.** Nothing ingests GW deadlines — the countdown (the home screen's centerpiece) has no source. | Migration 0008 adds a `gameweeks` table; both engine modes upsert it from bootstrap `events` (`deadline_time`, `finished`, `is_current`, `is_next` — fields already in the payload). |
| 5 | **Curated SQL can't run from a browser.** PostgREST doesn't execute raw SQL files; re-implementing the projection joins client-side is slow and forks the logic. | The eight `sql/queries/*.sql` become **views** of the same names (migration 0008), single source of truth, selectable through the API. |
| 6 | **Goals+assists aren't stored per player-season** (chart maker's bubble size). `players_master` has xG/xA but not actual G+A; those are per-GW in `player_history`. | New `player_season_stats` view: per-(season, player) sums from `player_history` joined to `players_master` snapshot fields. |
| 7 | **Service-worker cache serves stale data** — a cached squad or price table silently violates the project's zero-silent-staleness rule. | SW caching policy: precache the app shell only; **network-only for `*.supabase.co`**; when offline, show an explicit offline banner, never cached data presented as live. |
| 8 | **Freshness invisible.** A pretty UI over a dead pipeline is worse than Supabase Studio. | Global freshness badge in the app header reads `pipeline_runs` (same rule as the agent design): green ≤ 36h since last successful daily run, amber otherwise, with the timestamp always shown. |
| 9 | **Pre-season/off-season = empty screens.** Rivals has no GW1 data until the first post-deadline capture; projections are empty before GW1. | Every tab specs an empty state (see per-tab specs) — built and verified in session 2–3, not left to chance. |
| 10 | **Supabase free tier pauses after ~7 idle days.** | Already mitigated: the daily launchd run touches the DB every day year-round (even `skipped_offseason` runs write `pipeline_runs`). Noted so nobody "optimizes" the daily run away. |
| 11 | **Public repo.** The PWA source lives in this public repo. | Nothing secret ships: the anon key + project URL are public-by-design *once loophole #1 is closed* (they grant nothing without a session). They live in Vercel env vars, not in git. Service-role key never appears anywhere near `web/`. |
| 12 | **Migration number collision.** The deferred agent brief also specified an "0008". | This brief owns **0008**. The agent brief carries a DEFERRED banner; its migration renumbers to next-in-sequence when revived. |
| 13 | **Vercel Hobby tier is non-commercial.** | Fine for option A (personal tool). Flagged as a Phase 5 gate item: league-scale product moves to a paid tier or Netlify/Cloudflare. |
| 14 | **`limit 30` inside the curated queries breaks squad filtering.** The projection queries end in `order by … limit 30`; as views, filtering to *my* players happens after the limit — a squad player outside the global top 30 silently vanishes from the captain card. | Views are created **without** `LIMIT` (and view `ORDER BY` isn't guaranteed through PostgREST anyway) — the client applies `.order()` + `.limit()` itself. The `.sql` files keep their limits for Studio use. |
| 15 | **Magic links don't reach an installed iOS PWA.** Tapping an emailed link opens Safari, whose storage is separate from the standalone app — the session lands in the wrong context. | Login screen supports **both**: magic link (browser use) and a 6-digit email OTP (`signInWithOtp`, then `verifyOtp`) — the code path works inside the installed app. Email template must include `{{ .Token }}`. |
| 16 | **"My row" in standings has no data source.** `write_league_standings` excludes self from `league_rivals`, and `user_team_snapshots` has no league rank/total; reconstructing from per-GW sums breaks on missed snapshots. | Migration adds `league_rivals.is_me boolean default false`; `fpl_user_engine.py` now **includes** my standings row flagged `is_me = true`. `load_unique_rival_ids` and the four rival views must exclude `is_me` rows (audit them in session 1). |
| 17 | **`player_season_stats` blends seasons.** From 2026/27 the view would emit one row per player per season, historical rows mis-joined to current names/prices. | The view anchors on `(select max(season) from player_history)` — current season only, same convention as every curated query (decision #10). |
| 18 | **Email-based RLS policy is the weaker option.** The email claim is mutable (email-change flows, case normalization) and unwrapped `auth.jwt()` may evaluate per row on 300k-row scans. | Policies pin `(select auth.uid()) = '<invited-user-uuid>'` — immutable, and the scalar subselect evaluates once per query. The UUID is copied from the dashboard after the invite (step 1) and substituted into the migration before running it. |
| 19 | **The lockdown is point-in-time.** A table added by migration 0009+ would get `authenticated` SELECT with no RLS/policy. | New convention recorded in CLAUDE.md: *every migration after 0008 must enable RLS + the owner-read policy on new tables, and create views with `security_invoker = on`.* Belt-and-braces: 0008 also revokes sequences/functions from `anon`. |

## Deliverables

```
web/                                   # the PWA — a Vite + React + TypeScript app
  src/                                 #   (its own package.json; node_modules gitignored)
  public/manifest.webmanifest          # name, icons, theme, standalone display
  ...                                  # service worker via vite-plugin-pwa
supabase/migrations/0008_pwa_foundation.sql   # lockdown + gameweeks + is_me + views (below)
fpl_engine.py                          # + write_gameweeks() in both modes
fpl_user_engine.py                     # + my standings row (is_me) in write_league_standings
launchd/                               # unchanged — no new agents needed
README.md / CLAUDE.md                  # updated sections (see Done criteria)
```

## Tech constraints

1. **Stack:** Vite + React + TypeScript + `supabase-js` v2, `vite-plugin-pwa` for manifest/SW. Charts in plain SVG components (no chart library at first — the chart maker is ~200 lines; add Chart.js later only if pan/zoom is wanted). No CSS framework required; keep it hand-rolled and small.
2. **Everything behind login.** No public routes except the login screen. `anon` role has zero table access; all reads happen as `authenticated`.
3. **Read-only client.** The PWA never writes to the database — no exceptions in Phase 3B. All writes remain the engines' job (service role).
4. **The engines' conventions still apply to `fpl_engine.py` changes:** sync, logging, type hints, defensive field access (`events` may drop/rename fields — default and warn).
5. **Mobile-first**: design at 390px, verify at desktop. Installability on iOS Safari (Add to Home Screen) and Android Chrome are both done criteria.
6. **Timezones:** all timestamps stored UTC; render in the device's local time (deadline countdown must be correct in WIB).

## Schema additions — migration 0008

```sql
-- Migration 0008 — PWA foundation (Phase 3B)
-- Read docs/EXPANSION_PLAN.md + the PWA brief's loophole table for rationale.

-- 1) GAMEWEEKS — deadline source for the countdown (loophole #4).
create table if not exists gameweeks (
  season text not null,
  gw int not null,
  deadline_time timestamptz not null,
  finished boolean default false,
  is_current boolean default false,
  is_next boolean default false,
  primary key (season, gw)
);

-- 2) MY STANDINGS ROW (loophole #16) — engine change pairs with this.
alter table league_rivals add column if not exists is_me boolean default false;

-- 3) PLAYER SEASON STATS — actual G+A etc. per player, CURRENT SEASON ONLY
--    (loopholes #6 + #17; anchors like every curated query, decision #10).
create or replace view player_season_stats
with (security_invoker = on) as
select
  h.season, h.player_id,
  pm.web_name, pm.team_id, pm.position, pm.price, pm.ownership,
  pm.xg, pm.xa, pm.xgi, pm.xgc, pm.form, pm.status,
  pm.chance_of_playing_next_round,
  sum(h.goals)        as goals,
  sum(h.assists)      as assists,
  sum(h.goals + h.assists) as goal_involvements,
  sum(h.minutes)      as minutes,
  sum(h.total_points) as total_points,
  sum(h.bps)          as bps,
  sum(h.cbit)         as cbit
from player_history h
join players_master pm on pm.id = h.player_id
where h.season = (select max(season) from player_history)
group by h.season, h.player_id, pm.web_name, pm.team_id, pm.position,
         pm.price, pm.ownership, pm.xg, pm.xa, pm.xgi, pm.xgc, pm.form,
         pm.status, pm.chance_of_playing_next_round;

-- 4) CURATED QUERIES AS VIEWS (loophole #5). One view per file in sql/queries/,
--    same name, each created:
--      create or replace view <name> with (security_invoker = on) as <query body>;
--    (attackers_projection, attackers_recent_form, defenders_projection,
--     defenders_recent_form, league_template_vs_global, my_squad_vs_rivals,
--     rival_captain_consensus, rival_transfers_in_out)
--    Transformations required (loophole #14 + #16):
--      * strip the trailing `ORDER BY ... LIMIT 30` — the client orders/limits;
--        the .sql files keep theirs for Studio use
--      * strip trailing semicolons/comments
--      * any reference to league_rivals gains `and not is_me` (audit all eight)
--    They self-anchor on the latest season/GW already (decisions #8/#10) —
--    no parameters to freeze.

alter view team_history set (security_invoker = on);   -- loophole #3

-- 5) LOCKDOWN (loopholes #1 + #2 + #18 + #19). Idempotent; service role is
--    unaffected (BYPASSRLS) so the engines keep working unchanged.
--    ⚠ Replace <INVITED-USER-UUID> with the UUID from dashboard step 1 BEFORE running.
revoke all on all tables in schema public from anon;
revoke all on all sequences in schema public from anon;
revoke all on all functions in schema public from anon;
revoke insert, update, delete, truncate, references, trigger
  on all tables in schema public from authenticated;
alter default privileges in schema public revoke all on tables from anon;
alter default privileges in schema public
  revoke insert, update, delete, truncate, references, trigger
  on tables from authenticated;

do $$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public'
  loop
    execute format('alter table public.%I enable row level security', t);
    begin
      execute format(
        'create policy "owner read" on public.%I for select to authenticated
         using ((select auth.uid()) = ''<INVITED-USER-UUID>''::uuid)', t);
    exception when duplicate_object then null;   -- re-runnable
    end;
  end loop;
end $$;
-- (select auth.uid()) — scalar subselect evaluates once per query, not per row
-- (loophole #18). The 0001 user-table policies remain; policies OR together.
```

**Companion dashboard steps (not SQL — do in Supabase Dashboard, session 1, in this order):**
1. Authentication → Users → **Invite user** `andremadian@itsjack.com`; **copy the created user's UUID** and substitute it into the migration's `<INVITED-USER-UUID>` before applying.
2. Authentication → Sign In / Up → **disable new sign-ups** and **disable anonymous sign-ins** (invited/existing users still log in).
3. Authentication → Email Templates → ensure the OTP template includes `{{ .Token }}` (the 6-digit code the installed-app login path needs — loophole #15).
4. Authentication → URL Configuration → Site URL = the production Vercel URL; add `http://localhost:5173` to the redirect allowlist **during development only — remove it in session 4**. Never use wildcard redirect entries (`https://*.vercel.app` allowlists every Vercel site on the internet); pin exact URLs, and don't rely on magic links from preview deployments.

## Engine changes

**`fpl_engine.py` — `write_gameweeks(data, season, supabase)`:** build rows from `data["events"]` — each row `{"season": season, "gw": e["id"], "deadline_time": e["deadline_time"], "finished": ..., "is_current": ..., "is_next": ...}` (the PK is `(season, gw)` — don't forget the season stamp), defensive `.get` with defaults + one warning if fields go missing; upsert to `gameweeks`. Call it in **both** the daily and weekly branches (after `write_snapshot`); the `skipped_offseason` path intentionally doesn't run it — during the off-season all rows are `finished = true`, which is exactly what the This-week off-season empty state renders (see tab spec). Add `("gameweeks", "deadline_time", "0008_pwa_foundation.sql")` to `SCHEMA_CHECKS`. Rows: ~38/season.

**`fpl_user_engine.py` — my standings row (loophole #16):** `write_league_standings` stops excluding self — my entry is inserted into `league_rivals` with `is_me = true` (rivals stay `false`). `load_unique_rival_ids` adds `where is_me = false` so my own squad is never fetched as a "rival". Same delete+re-insert pattern, so the flag stays consistent every run. Session 1 audits the four rival views for any `league_rivals` reference needing `and not is_me` (the migration comment repeats this).

## App spec — four tabs + shell

**Shell:** bottom tab bar (This week / Transfers / Rivals / Charts), header with app name + **freshness badge** (loophole #8: reads `pipeline_runs` — latest successful run per engine; green ≤ 36h since the daily run, amber otherwise; tapping it shows per-engine timestamps). Login screen = email field with **two paths** (loophole #15): "send magic link" (browser use) and "send code" → 6-digit OTP input (`signInWithOtp` + `verifyOtp` — the path that works inside the installed iOS app, whose storage is separate from Safari's). Session persisted by supabase-js. Routing: hash-based, **or** path-based with a `vercel.json` SPA rewrite to `/index.html` — pick one explicitly; without it, deep links and the magic-link redirect 404 on Vercel. Offline (SW detects no network): amber "offline — data hidden" banner, no cached data shown (loophole #7).

**1. This week (home)**
- Deadline card: next `gameweeks` row where `finished = false` ordered by deadline — live countdown, local timezone. Pre-deadline of GW1 works day one (loophole #4). **Off-season state** (no unfinished rows — ~2 months/year): "Season complete — the 20XX/YY schedule appears when FPL resets (~early July)."
- Captain list: fetch `attackers_projection` **client-ordered by `projection_score desc`** (the view has no LIMIT/ORDER guarantees — loophole #14), filter to player_ids in my latest `user_team_snapshots` row, take 5; falls back to unrestricted top 5 with a "no squad snapshot yet" note (empty state, loophole #9).
- Alerts: from `players_master` where player is in my squad and (`status is distinct from 'a'` or `abs(cost_change_event) > 0`) — `is distinct from`, not `!=`: a NULL status must alert, not silently pass (an alerts feature must fail loud); plus biggest overnight movers from `player_daily` (latest two dates diff). Empty state: "no alerts — quiet day."

**2. Transfers**
- Tabs within tab: Attackers / Defenders. Each renders its projection view as a ranked list (name, team, next fixtures, projection score, form delta arrow). The views emit **one row per (player, upcoming fixture)** — deliberate, for DGWs. The client groups by player: rank on the **sum** of projection_score across the player's upcoming fixtures (so a double gameweek correctly ranks higher), fixtures shown as a list in the row.
- Tapping a player expands a detail row: price + ownership sparklines from `player_daily` (last 30 days), season stats from `player_season_stats`.
- Empty state (pre-GW1: projections need history): "projections unlock after GW1 — here's last season's final form" is **out of scope**; just show the explanatory empty state.

**3. Rivals**
- Standings from `league_rivals` including my `is_me` row (loophole #16), gap-to-leader computed from stored league totals — no client-side reconstruction.
- Captain consensus (`rival_captain_consensus` view), differentials (`my_squad_vs_rivals`, `league_template_vs_global`), transfers in/out (`rival_transfers_in_out`). **Scoping honesty:** rival squads are deduped across leagues at ingest, so these widgets are **cross-league by design**; the league selector (if >1 tracked league) scopes the standings card only. Label the widgets "all tracked leagues" when more than one exists.
- Empty state: "rival squads appear after the first post-deadline capture (Saturday 10am)."

**4. Chart maker**
- Three selects — X axis, Y axis, Bubble size — over `player_season_stats` numeric columns (xg, xa, xgi, xgc, goals, assists, goal_involvements, total_points, minutes, price, ownership, form, cbit, bps). Defaults: x=xg, y=xa, size=goal_involvements.
- Filters: position (GKP/DEF/MID/FWD/all), min minutes slider (default 400 — hides the zero-blob), "highlight my squad" toggle.
- Bubbles: **area** ∝ size metric (radius = k·√v), colors `#1D9E75` (my squad) / `#378ADD` (rest) — this pair passes light+dark colorblind-safety validation; 2px surface-colored ring per bubble; direct labels on the top 5 by size metric; tap/hover tooltip with name + the three values; axes labeled with the chosen metric names; all displayed numbers rounded to 1 decimal.
- Empty state pre-GW1: "charts unlock once the season has data."

## Environment (Vercel project settings, not in git)

```
VITE_SUPABASE_URL=https://<ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<anon key>     # public-by-design once 0008 is applied
```

## Quality bar

- TypeScript strict; typed row interfaces for every view/table consumed.
- Each tab is a component with three states: loading / data / empty — no blank screens ever.
- Lighthouse PWA audit passes (installable, manifest, SW, icons).
- No console errors in a full click-through; supabase-js errors surface as a visible toast, not silence.
- Loophole verification script or checklist executed in session 1 (see done criteria 2–4).

## What you don't need to build

- Web Push / notifications — that's Phase 4 (template-based Sniper Brief page + push), on this same PWA.
- The AI chat tab — deferred agent brief; revisit after a season of PWA use.
- Historical-season charts (archive joins), multi-league switching UI polish beyond a simple select, dark-mode toggle (respect `prefers-color-scheme`, done).
- Accounts for anyone else — Phase 5 gate, with its own preconditions.
- Writes of any kind from the browser.

## Done criteria

1. Migration 0008 applied; **both engines** (incl. the `is_me` change in `fpl_user_engine.py`) still run clean end-to-end (schema asserts pass incl. `gameweeks`; `pipeline_runs` gets rows) — proves the lockdown didn't touch service-role writes.
2. **Anon lockdown verified (session 1, SQL/curl level):** with only the anon key (no session), a PostgREST `select` on `players_master` returns a permission error/empty, and an `insert`/`upsert` attempt on any table is rejected. Documented as a repeatable curl checklist in README (moved into `web/scripts/` once `web/` exists).
3. **Allowlist verified in two stages.** *Session 1 (SQL level):* in the SQL editor, impersonate — `set role authenticated; set request.jwt.claims = '{"sub":"<other-uuid>"}';` — and confirm zero rows from `players_master`; repeat with the invited UUID and confirm rows. *Session 3 (UI level):* logged in as the invited email, all four tabs load data; a second manually-created test user sees empty tabs.
4. Views verified: `attackers_projection` (as authenticated) matches the .sql file run in Studio **modulo the stripped LIMIT/ORDER**; `player_season_stats` G+A figures spot-checked against known players; all eight views audited for `league_rivals` references needing `not is_me`.
5. `gameweeks` populated for the current season after one engine run; the countdown shows the true next deadline in local time.
6. All four tabs render correct data **and** correct empty states (toggle by pointing at pre-season data or a scratch filter).
7. Chart maker: default view renders ~all outfield players with minutes ≥ 400; switching all three dropdowns re-renders correctly; my-squad highlight matches the latest snapshot; tooltip values match the DB.
8. Freshness badge: shows green with a fresh daily run; manually flip it (temporarily point at an old timestamp) to confirm amber path.
9. Installable: Add to Home Screen on iOS Safari and Android Chrome yields a standalone-window app; **login inside the installed iOS app succeeds via the OTP code path** (magic links land in Safari, not the app — loophole #15); SW serves the shell offline with the offline banner and no stale data.
10. Deployed on Vercel free tier at a stable URL; magic-link round trip works on the deployed origin; deep-link refresh doesn't 404 (SPA rewrite or hash routing); the `localhost` redirect entry is removed from the Supabase allowlist.
11. README gains a "Phase 3B — PWA" section (dev setup: `npm dev` in `web/`, env vars, Supabase auth config incl. OTP template, deploy); CLAUDE.md updated (phase table, `web/` in files tree, decision entry for the lockdown, note that decision #5's "RLS off" is superseded by 0008, **and the new-migration convention from loophole #19: every table after 0008 gets RLS + the owner-read policy; every view gets `security_invoker = on`**).

## Order of operations

1. **Session 1 — foundation & lockdown:** migration 0008 + dashboard auth steps + `write_gameweeks` + verify criteria 1–5. *Everything else depends on this; do not scaffold UI first.*
2. **Session 2 — shell + This week + Transfers:** Vite scaffold in `web/`, login flow, tab shell, freshness badge, tabs 1–2 with empty states (criteria parts of 6, 8).
3. **Session 3 — Rivals + Chart maker:** tabs 3–4 (criteria 6–7).
4. **Session 4 — PWA polish + deploy + docs:** manifest, SW policy, install tests, Vercel deploy, README/CLAUDE.md (criteria 9–11).

Each session ends with a commit. Do not start session N+1 with session N's criteria unverified.
