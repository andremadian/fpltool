# Stats Explorer (Phase 3C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth PWA tab, "Stats", that browses the current-season players & teams database as a filterable, sortable, mobile-friendly table.

**Architecture:** Four new `security_invoker` Supabase views (migration 0010) expose season and last-5-GW player/team stats. The React tab fetches one whole view per (entity, window) via the existing `useSupabaseQuery` hook, then does all searching, per-metric range filtering, and sorting client-side. A declarative column-config array drives both the table headers and the range-filter list. No engine or base-table changes.

**Tech Stack:** PostgreSQL views (Supabase), React 19 + TypeScript + Vite, `@supabase/supabase-js` (anon key), plain CSS. No JS test runner exists in `web/` — verification is `npm run build` (the real type-check gate) plus a browser-preview walkthrough.

**Spec:** [docs/superpowers/specs/2026-07-25-stats-explorer-design.md](../specs/2026-07-25-stats-explorer-design.md)

**Conventions carried from CLAUDE.md:** every new view is created `with (security_invoker = on)` and gets an explicit `grant select ... to authenticated` (loophole #19). No new tables, so no new RLS policy. Views self-anchor on the current season. Commit after each task.

---

## File structure

| File | Responsibility | Task |
|------|----------------|------|
| `supabase/migrations/0010_stats_explorer_views.sql` | **Create.** The 4 explorer views + grants. | 1 |
| `web/src/types/db.ts` | **Modify.** Add `PlayerExplorerRow`, `TeamExplorerRow`. | 2 |
| `web/src/tabs/statsExplorerColumns.ts` | **Create.** Column-config single source of truth + shared `Entity`/`StatsWindow` types. | 3 |
| `web/src/components/PlayerDetail.tsx` | **Create.** Shared expandable player detail (extracted from Transfers). | 4 |
| `web/src/tabs/Transfers.tsx` | **Modify.** Use the shared `PlayerDetail`; drop the local copy. | 4 |
| `web/src/tabs/StatsExplorer.tsx` | **Create.** The tab: toggles, fetch, filter drawer, table, expand. | 5 |
| `web/src/components/Shell.tsx` | **Modify.** Add the "Stats" tab (nav 4 → 5). | 5 |
| `web/src/App.css` | **Modify.** Stats-explorer styles (toolbar, drawer, sticky table). | 6 |
| `CLAUDE.md`, `docs/TODOS.md` | **Modify.** Document Phase 3C. | 8 |

---

## Task 1: Migration 0010 — the four explorer views

**Files:**
- Create: `supabase/migrations/0010_stats_explorer_views.sql`

- [ ] **Step 1: Write the migration file**

Create `supabase/migrations/0010_stats_explorer_views.sql` with exactly:

```sql
-- Migration 0010 — Stats Explorer views (Phase 3C)
-- Four read-only curated views powering the PWA "Stats" tab: season and
-- last-5-GW windows for players and teams. Follows the loophole #19
-- convention (CLAUDE.md): security_invoker = on + explicit grant to
-- authenticated. No new tables, so no new RLS policy. All views self-anchor
-- on the current season (decision #10). The engines do not read these.

-- 1) PLAYER — SEASON TOTALS. Counting stats summed from player_history;
--    rate/expected stats read from players_master (the API's own season
--    figures), mirroring the existing player_season_stats view. Inner join
--    to history so the view is empty pre-GW1 (drives the "unlock after GW1"
--    empty state) and 0-minute players don't flood the table.
create or replace view player_explorer_season
with (security_invoker = on) as
with cs as (select max(season) as season from player_history),
agg as (
  select ph.player_id,
         sum(ph.minutes)            as minutes,
         sum(ph.total_points)       as total_points,
         sum(ph.goals)              as goals,
         sum(ph.assists)            as assists,
         sum(ph.goals + ph.assists) as goal_involvements,
         sum(ph.clean_sheets)       as clean_sheets,
         sum(ph.cbit)               as cbit,
         sum(ph.bps)                as bps
  from player_history ph
  where ph.season = (select season from cs)
  group by ph.player_id
)
select
  pm.id                                                       as player_id,
  pm.web_name,
  t.short_name                                                as team,
  pm.position,
  pm.price,
  pm.status,
  pm.ownership,
  a.minutes,
  a.total_points,
  pm.points_per_90,
  case when pm.price > 0
       then round(a.total_points::numeric / pm.price, 2)
  end                                                         as points_per_million,
  a.goals,
  a.assists,
  a.goal_involvements,
  pm.xg,
  pm.xa,
  pm.xgi,
  pm.xgc,
  a.clean_sheets,
  a.cbit,
  a.bps,
  pm.ict_index,
  pm.form
from agg a
join players_master pm on pm.id = a.player_id
join teams t on t.id = pm.team_id;

-- 2) PLAYER — LAST 5 GWs (minutes > 0), same recency logic as the projection
--    views. ict_index has no per-GW source, so it is null here.
create or replace view player_explorer_last5
with (security_invoker = on) as
with cs as (select max(season) as season from player_history),
ranked as (
  select ph.*,
         row_number() over (partition by ph.player_id order by ph.gw desc) as rn
  from player_history ph
  where ph.minutes > 0
    and ph.season = (select season from cs)
),
agg as (
  select player_id,
         sum(minutes)            as minutes,
         sum(total_points)       as total_points,
         sum(goals)              as goals,
         sum(assists)            as assists,
         sum(goals + assists)    as goal_involvements,
         sum(clean_sheets)       as clean_sheets,
         sum(cbit)               as cbit,
         sum(bps)                as bps,
         sum(xg)                 as xg,
         sum(xa)                 as xa,
         sum(xgi)                as xgi,
         sum(xgc)                as xgc
  from ranked
  where rn <= 5
  group by player_id
)
select
  pm.id                                                       as player_id,
  pm.web_name,
  t.short_name                                                as team,
  pm.position,
  pm.price,
  pm.status,
  pm.ownership,
  a.minutes,
  a.total_points,
  case when a.minutes > 0
       then round(a.total_points::numeric * 90 / a.minutes, 2)
  end                                                         as points_per_90,
  case when pm.price > 0
       then round(a.total_points::numeric / pm.price, 2)
  end                                                         as points_per_million,
  a.goals,
  a.assists,
  a.goal_involvements,
  a.xg::numeric(6,2)                                          as xg,
  a.xa::numeric(6,2)                                          as xa,
  a.xgi::numeric(6,2)                                         as xgi,
  a.xgc::numeric(6,2)                                         as xgc,
  a.clean_sheets,
  a.cbit,
  a.bps,
  null::numeric                                               as ict_index,
  pm.form
from agg a
join players_master pm on pm.id = a.player_id
join teams t on t.id = pm.team_id;

-- 3) TEAM — SEASON. W/D/L, GF/GA/GD, clean sheets from finished fixtures
--    (home + away perspectives unioned); xG/xA/xGC from team_history. Left
--    join teams so all 20 clubs always show (a club with 0 finished matches
--    is still a valid row).
create or replace view team_explorer_season
with (security_invoker = on) as
with cs as (select max(season) as season from fixtures),
results as (
  select f.home_team_id as team_id, f.gw, f.home_score as gf, f.away_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from cs)
  union all
  select f.away_team_id as team_id, f.gw, f.away_score as gf, f.home_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from cs)
),
team_results as (
  select team_id,
         count(*)                        as matches_played,
         count(*) filter (where gf > ga) as wins,
         count(*) filter (where gf = ga) as draws,
         count(*) filter (where gf < ga) as losses,
         sum(gf)                         as goals_for,
         sum(ga)                         as goals_against,
         count(*) filter (where ga = 0)  as clean_sheets
  from results
  group by team_id
),
team_xg as (
  select team_id,
         sum(total_xg)  as total_xg,
         sum(total_xa)  as total_xa,
         sum(team_xgc)  as xgc
  from team_history
  where season = (select season from cs)
  group by team_id
)
select
  t.id                                                as team_id,
  t.short_name,
  t.name,
  coalesce(tr.matches_played, 0)                      as matches_played,
  coalesce(tr.wins, 0)                                as wins,
  coalesce(tr.draws, 0)                               as draws,
  coalesce(tr.losses, 0)                              as losses,
  coalesce(tr.wins, 0) * 3 + coalesce(tr.draws, 0)    as points,
  coalesce(tr.goals_for, 0)                           as goals_for,
  coalesce(tr.goals_against, 0)                       as goals_against,
  coalesce(tr.goals_for, 0) - coalesce(tr.goals_against, 0) as goal_difference,
  coalesce(tr.clean_sheets, 0)                        as clean_sheets,
  tx.total_xg::numeric(6,2)                           as total_xg,
  tx.total_xa::numeric(6,2)                           as total_xa,
  tx.xgc::numeric(6,2)                                as xgc,
  t.strength_overall_home                             as strength_home,
  t.strength_overall_away                             as strength_away
from teams t
left join team_results tr on tr.team_id = t.id
left join team_xg tx on tx.team_id = t.id;

-- 4) TEAM — LAST 5 finished fixtures per team (+ last-5 GWs of team_history).
--    Exposes strength_home/away too (UI hides them in the last-5 window) so a
--    single TS interface covers both team views.
create or replace view team_explorer_last5
with (security_invoker = on) as
with cs as (select max(season) as season from fixtures),
results as (
  select f.home_team_id as team_id, f.gw, f.home_score as gf, f.away_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from cs)
  union all
  select f.away_team_id as team_id, f.gw, f.away_score as gf, f.home_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from cs)
),
ranked as (
  select r.*, row_number() over (partition by team_id order by gw desc) as rn
  from results r
),
last5 as (
  select * from ranked where rn <= 5
),
team_results as (
  select team_id,
         count(*)                        as matches_played,
         count(*) filter (where gf > ga) as wins,
         count(*) filter (where gf = ga) as draws,
         count(*) filter (where gf < ga) as losses,
         sum(gf)                         as goals_for,
         sum(ga)                         as goals_against,
         count(*) filter (where ga = 0)  as clean_sheets
  from last5
  group by team_id
),
th_ranked as (
  select th.*, row_number() over (partition by team_id order by gw desc) as rn
  from team_history th
  where th.season = (select season from cs)
),
team_xg as (
  select team_id,
         sum(total_xg)  as total_xg,
         sum(total_xa)  as total_xa,
         sum(team_xgc)  as xgc
  from th_ranked
  where rn <= 5
  group by team_id
)
select
  t.id                                                as team_id,
  t.short_name,
  t.name,
  coalesce(tr.matches_played, 0)                      as matches_played,
  coalesce(tr.wins, 0)                                as wins,
  coalesce(tr.draws, 0)                               as draws,
  coalesce(tr.losses, 0)                              as losses,
  coalesce(tr.wins, 0) * 3 + coalesce(tr.draws, 0)    as points,
  coalesce(tr.goals_for, 0)                           as goals_for,
  coalesce(tr.goals_against, 0)                       as goals_against,
  coalesce(tr.goals_for, 0) - coalesce(tr.goals_against, 0) as goal_difference,
  coalesce(tr.clean_sheets, 0)                        as clean_sheets,
  tx.total_xg::numeric(6,2)                           as total_xg,
  tx.total_xa::numeric(6,2)                           as total_xa,
  tx.xgc::numeric(6,2)                                as xgc,
  t.strength_overall_home                             as strength_home,
  t.strength_overall_away                             as strength_away
from teams t
left join team_results tr on tr.team_id = t.id
left join team_xg tx on tx.team_id = t.id;

-- 5) GRANTS — authenticated reads (anon stays revoked from 0008).
grant select on player_explorer_season to authenticated;
grant select on player_explorer_last5  to authenticated;
grant select on team_explorer_season   to authenticated;
grant select on team_explorer_last5    to authenticated;
```

- [ ] **Step 2: Apply the migration**

Open Supabase → SQL Editor, paste the file's contents, Run. (This project applies migrations manually via the SQL Editor — there is no CLI migration runner wired up.) Expect "Success. No rows returned."

- [ ] **Step 3: Verify the views return sane data**

In the SQL Editor run:

```sql
select count(*) as players, sum(goals) as total_goals from player_explorer_season;
select count(*) as teams,   max(points) as top_points  from team_explorer_season;
select web_name, minutes, total_points, points_per_90 from player_explorer_last5 order by total_points desc limit 3;
```

Expected (current 2025/26 data, season complete): `players` > 400 and `total_goals` > 0; `teams` = 20 and `top_points` in a plausible 80–99 range; the last-5 rows return real names with `points_per_90` populated. If pre-GW1 of a new season, `player_explorer_season` may be empty (0 rows) — that is correct and drives the empty state.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/0010_stats_explorer_views.sql
git commit -m "Phase 3C — migration 0010: stats explorer views (player/team × season/last5)"
```

---

## Task 2: TypeScript row types

**Files:**
- Modify: `web/src/types/db.ts` (append at end of file)

- [ ] **Step 1: Append the two interfaces**

Add to the end of `web/src/types/db.ts`:

```ts
export interface PlayerExplorerRow {
  player_id: number
  web_name: string
  team: string
  position: string
  price: number
  status: string | null
  ownership: number | null
  minutes: number
  total_points: number
  points_per_90: number | null
  points_per_million: number | null
  goals: number
  assists: number
  goal_involvements: number
  xg: number | null
  xa: number | null
  xgi: number | null
  xgc: number | null
  clean_sheets: number
  cbit: number
  bps: number
  ict_index: number | null
  form: number | null
}

export interface TeamExplorerRow {
  team_id: number
  short_name: string
  name: string
  matches_played: number
  wins: number
  draws: number
  losses: number
  points: number
  goals_for: number
  goals_against: number
  goal_difference: number
  clean_sheets: number
  total_xg: number | null
  total_xa: number | null
  xgc: number | null
  strength_home: number | null
  strength_away: number | null
}
```

- [ ] **Step 2: Verify build**

Run: `cd web && npm run build`
Expected: PASS (no type errors; the new exported interfaces are unused so far, which is fine — exports are not flagged).

- [ ] **Step 3: Commit**

```bash
git add web/src/types/db.ts
git commit -m "Phase 3C — explorer row types"
```

---

## Task 3: Column-config module

**Files:**
- Create: `web/src/tabs/statsExplorerColumns.ts`

- [ ] **Step 1: Create the module**

Create `web/src/tabs/statsExplorerColumns.ts` with exactly:

```ts
// Single source of truth for the Stats Explorer table. Each ColumnDef drives
// both a table header and (when numeric) a min/max range filter. `windows`
// controls which time windows expose the column (e.g. ict_index is season-only
// because it has no per-GW source; team strength is season-only by choice).

export type Entity = 'player' | 'team'
export type StatsWindow = 'season' | 'last5'

export interface ColumnDef {
  key: string
  label: string
  unit?: string
  entity: Entity
  windows: StatsWindow[]
  numeric: boolean
  higherIsBetter?: boolean // reserved for future good/bad cell coloring
}

const BOTH: StatsWindow[] = ['season', 'last5']

// NOTE: index 0 of each array is the sticky "name" column.
export const PLAYER_COLUMNS: ColumnDef[] = [
  { key: 'web_name',           label: 'Player', entity: 'player', windows: BOTH, numeric: false },
  { key: 'team',               label: 'Team',   entity: 'player', windows: BOTH, numeric: false },
  { key: 'position',           label: 'Pos',    entity: 'player', windows: BOTH, numeric: false },
  { key: 'status',             label: 'Avail',  entity: 'player', windows: BOTH, numeric: false },
  { key: 'price',              label: 'Price',  unit: '', entity: 'player', windows: BOTH, numeric: true, higherIsBetter: false },
  { key: 'ownership',          label: 'Own%',   entity: 'player', windows: BOTH, numeric: true },
  { key: 'total_points',       label: 'Pts',    entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'points_per_90',      label: 'Pts/90', entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'points_per_million', label: 'Pts/£m', entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'minutes',            label: 'Mins',   entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'goals',              label: 'G',      entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'assists',            label: 'A',      entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'goal_involvements',  label: 'G+A',    entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'xg',                 label: 'xG',     entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'xa',                 label: 'xA',     entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'xgi',                label: 'xGI',    entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'xgc',                label: 'xGC',    entity: 'player', windows: BOTH, numeric: true, higherIsBetter: false },
  { key: 'clean_sheets',       label: 'CS',     entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'cbit',               label: 'CBIT',   entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'bps',                label: 'BPS',    entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'ict_index',          label: 'ICT',    entity: 'player', windows: ['season'], numeric: true, higherIsBetter: true },
  { key: 'form',               label: 'Form',   entity: 'player', windows: BOTH, numeric: true, higherIsBetter: true },
]

export const TEAM_COLUMNS: ColumnDef[] = [
  { key: 'short_name',      label: 'Team', entity: 'team', windows: BOTH, numeric: false },
  { key: 'matches_played',  label: 'MP',   entity: 'team', windows: BOTH, numeric: true },
  { key: 'wins',            label: 'W',    entity: 'team', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'draws',           label: 'D',    entity: 'team', windows: BOTH, numeric: true },
  { key: 'losses',          label: 'L',    entity: 'team', windows: BOTH, numeric: true, higherIsBetter: false },
  { key: 'points',          label: 'Pts',  entity: 'team', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'goals_for',       label: 'GF',   entity: 'team', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'goals_against',   label: 'GA',   entity: 'team', windows: BOTH, numeric: true, higherIsBetter: false },
  { key: 'goal_difference', label: 'GD',   entity: 'team', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'clean_sheets',    label: 'CS',   entity: 'team', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'total_xg',        label: 'xG',   entity: 'team', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'total_xa',        label: 'xA',   entity: 'team', windows: BOTH, numeric: true, higherIsBetter: true },
  { key: 'xgc',             label: 'xGC',  entity: 'team', windows: BOTH, numeric: true, higherIsBetter: false },
  { key: 'strength_home',   label: 'Str H', entity: 'team', windows: ['season'], numeric: true },
  { key: 'strength_away',   label: 'Str A', entity: 'team', windows: ['season'], numeric: true },
]
```

- [ ] **Step 2: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/tabs/statsExplorerColumns.ts
git commit -m "Phase 3C — stats explorer column config"
```

---

## Task 4: Extract shared `PlayerDetail`

The Transfers tab has a private `PlayerDetail` (price/ownership sparklines + season stats). The Stats tab reuses it, so extract it into a shared component (DRY).

**Files:**
- Create: `web/src/components/PlayerDetail.tsx`
- Modify: `web/src/tabs/Transfers.tsx`

- [ ] **Step 1: Create the shared component**

Create `web/src/components/PlayerDetail.tsx` with exactly:

```tsx
import { supabase } from '../lib/supabaseClient'
import { useSupabaseQuery } from '../hooks/useSupabaseQuery'
import { Sparkline } from './Sparkline'
import type { PlayerDaily, PlayerSeasonStats } from '../types/db'

/** Expandable per-player detail: 30-day price/ownership sparklines + season
 *  counting stats. Shared by the Transfers and Stats Explorer tabs. */
export function PlayerDetail({ playerId }: { playerId: number }) {
  const dailyState = useSupabaseQuery<PlayerDaily>(
    () =>
      supabase
        .from('player_daily')
        .select('*')
        .eq('player_id', playerId)
        .order('as_of_date', { ascending: false })
        .limit(30),
    [playerId],
  )
  const statsState = useSupabaseQuery<PlayerSeasonStats>(
    () => supabase.from('player_season_stats').select('*').eq('player_id', playerId),
    [playerId],
  )

  return (
    <div className="player-detail">
      {dailyState.status === 'loading' && <p>loading price/ownership history…</p>}
      {dailyState.status === 'error' && <p>couldn't load price/ownership history.</p>}
      {dailyState.status === 'empty' && <p>no daily history yet.</p>}
      {dailyState.status === 'data' && (
        <div className="sparkline-row">
          <div>
            <span className="sparkline-label">price (30d)</span>
            <Sparkline values={[...dailyState.data].reverse().map((d) => d.price ?? 0)} />
          </div>
          <div>
            <span className="sparkline-label">ownership (30d)</span>
            <Sparkline values={[...dailyState.data].reverse().map((d) => d.ownership ?? 0)} />
          </div>
        </div>
      )}

      {statsState.status === 'data' && (
        <dl className="season-stats">
          <dt>Goals</dt>
          <dd>{statsState.data[0].goals}</dd>
          <dt>Assists</dt>
          <dd>{statsState.data[0].assists}</dd>
          <dt>Minutes</dt>
          <dd>{statsState.data[0].minutes}</dd>
          <dt>Total points</dt>
          <dd>{statsState.data[0].total_points}</dd>
        </dl>
      )}
      {statsState.status === 'empty' && <p>no season stats yet.</p>}
    </div>
  )
}
```

- [ ] **Step 2: Rewrite `Transfers.tsx` to use the shared component**

Replace the entire contents of `web/src/tabs/Transfers.tsx` with:

```tsx
import { useMemo, useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { useSupabaseQuery } from '../hooks/useSupabaseQuery'
import { PlayerDetail } from '../components/PlayerDetail'
import type { ProjectionRow } from '../types/db'

type PositionTab = 'attackers' | 'defenders'

interface FixtureEntry {
  gw: number
  opponent: string
  venue: 'H' | 'A'
  fdr: number
  kickoff_time: string
}

interface GroupedProjection {
  player_id: number
  web_name: string
  position: string
  price: number
  totalScore: number
  fixtures: FixtureEntry[]
}

function groupByPlayer(rows: ProjectionRow[]): GroupedProjection[] {
  const byPlayer = new Map<number, GroupedProjection>()
  for (const row of rows) {
    const existing = byPlayer.get(row.player_id)
    const fixture: FixtureEntry = {
      gw: row.upcoming_gw,
      opponent: row.opponent,
      venue: row.venue,
      fdr: row.fdr,
      kickoff_time: row.kickoff_time,
    }
    if (existing) {
      existing.totalScore += row.projection_score
      existing.fixtures.push(fixture)
    } else {
      byPlayer.set(row.player_id, {
        player_id: row.player_id,
        web_name: row.web_name,
        position: row.position,
        price: row.price,
        totalScore: row.projection_score,
        fixtures: [fixture],
      })
    }
  }
  return [...byPlayer.values()].sort((a, b) => b.totalScore - a.totalScore)
}

export function Transfers() {
  const [subTab, setSubTab] = useState<PositionTab>('attackers')
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const viewName = subTab === 'attackers' ? 'attackers_projection' : 'defenders_projection'
  const state = useSupabaseQuery<ProjectionRow>(
    () => supabase.from(viewName).select('*'),
    [viewName],
  )

  const ranked = useMemo(
    () => (state.status === 'data' ? groupByPlayer(state.data) : []),
    [state],
  )

  return (
    <div className="tab-content">
      <div className="sub-tab-bar">
        <button
          type="button"
          className={subTab === 'attackers' ? 'tab-active' : ''}
          onClick={() => setSubTab('attackers')}
        >
          Attackers
        </button>
        <button
          type="button"
          className={subTab === 'defenders' ? 'tab-active' : ''}
          onClick={() => setSubTab('defenders')}
        >
          Defenders
        </button>
      </div>

      {state.status === 'loading' && <p>loading projections…</p>}
      {state.status === 'error' && <p>couldn't load projections.</p>}
      {state.status === 'empty' && (
        <p className="empty-state">projections unlock after GW1.</p>
      )}

      {state.status === 'data' && (
        <ul className="projection-list">
          {ranked.map((p) => (
            <li key={p.player_id}>
              <button
                type="button"
                className="projection-row"
                onClick={() => setExpandedId(expandedId === p.player_id ? null : p.player_id)}
              >
                <span className="player-name">
                  {p.web_name} ({p.position}) £{p.price}m
                </span>
                <span className="score">{p.totalScore.toFixed(2)}</span>
                <span className="fixtures">
                  {p.fixtures
                    .map((f) => `GW${f.gw} ${f.venue === 'H' ? 'vs' : '@'} ${f.opponent} (FDR ${f.fdr})`)
                    .join(', ')}
                </span>
              </button>
              {expandedId === p.player_id && <PlayerDetail playerId={p.player_id} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

(This is identical to the current file except: the local `PlayerDetail` function is removed, the `Sparkline` / `PlayerDaily` / `PlayerSeasonStats` imports are dropped, and `PlayerDetail` is imported from `../components/PlayerDetail`.)

- [ ] **Step 3: Verify build**

Run: `cd web && npm run build`
Expected: PASS, no unused-import errors.

- [ ] **Step 4: Verify Transfers still works in the browser**

Start the preview (`preview_start` with the dev-server config, or `cd web && npm run dev`), open the app, sign in, open the **Transfers** tab, tap a player row → the price/ownership sparklines + season stats still expand. (Pre-season the list may be empty — in that case just confirm no console error and the empty state shows.)

- [ ] **Step 5: Commit**

```bash
git add web/src/components/PlayerDetail.tsx web/src/tabs/Transfers.tsx
git commit -m "Phase 3C — extract shared PlayerDetail from Transfers"
```

---

## Task 5: StatsExplorer tab + wire into Shell

**Files:**
- Create: `web/src/tabs/StatsExplorer.tsx`
- Modify: `web/src/components/Shell.tsx`

- [ ] **Step 1: Create the tab component**

Create `web/src/tabs/StatsExplorer.tsx` with exactly:

```tsx
import { Fragment, useMemo, useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { useSupabaseQuery } from '../hooks/useSupabaseQuery'
import { PlayerDetail } from '../components/PlayerDetail'
import {
  PLAYER_COLUMNS,
  TEAM_COLUMNS,
  type ColumnDef,
  type Entity,
  type StatsWindow,
} from './statsExplorerColumns'
import type { PlayerExplorerRow, TeamExplorerRow } from '../types/db'

type Row = Record<string, string | number | null>

interface SortState {
  key: string
  dir: 'asc' | 'desc'
}

interface RangeInput {
  min: string
  max: string
}

const POSITIONS = ['All', 'GKP', 'DEF', 'MID', 'FWD'] as const

const DEFAULT_SORT: Record<Entity, string> = {
  player: 'total_points',
  team: 'points',
}

function viewName(entity: Entity, window: StatsWindow): string {
  return `${entity}_explorer_${window}`
}

function nameKey(entity: Entity): string {
  return entity === 'player' ? 'web_name' : 'short_name'
}

function teamKey(entity: Entity): string {
  return entity === 'player' ? 'team' : 'short_name'
}

function rowId(entity: Entity, row: Row): number {
  return Number(entity === 'player' ? row.player_id : row.team_id)
}

function formatCell(value: string | number | null, col: ColumnDef): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    const text = Number.isInteger(value) ? String(value) : value.toFixed(2)
    return col.unit ? `${text}${col.unit}` : text
  }
  return String(value)
}

export function StatsExplorer() {
  const [entity, setEntity] = useState<Entity>('player')
  const [timeWindow, setTimeWindow] = useState<StatsWindow>('season')
  const [search, setSearch] = useState('')
  const [position, setPosition] = useState<(typeof POSITIONS)[number]>('All')
  const [team, setTeam] = useState('All')
  const [ranges, setRanges] = useState<Record<string, RangeInput>>({})
  const [sort, setSort] = useState<SortState>({ key: DEFAULT_SORT.player, dir: 'desc' })
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const view = viewName(entity, timeWindow)
  const state = useSupabaseQuery<PlayerExplorerRow | TeamExplorerRow>(
    () => supabase.from(view).select('*'),
    [view],
  )

  const columns = useMemo(
    () =>
      (entity === 'player' ? PLAYER_COLUMNS : TEAM_COLUMNS).filter((c) =>
        c.windows.includes(timeWindow),
      ),
    [entity, timeWindow],
  )

  const rows = useMemo(
    () => (state.status === 'data' ? (state.data as unknown as Row[]) : []),
    [state],
  )

  const teamOptions = useMemo(() => {
    const key = teamKey(entity)
    const set = new Set<string>()
    for (const r of rows) {
      const v = r[key]
      if (typeof v === 'string') set.add(v)
    }
    return ['All', ...[...set].sort()]
  }, [rows, entity])

  const visible = useMemo(() => {
    const nk = nameKey(entity)
    const tk = teamKey(entity)
    const q = search.trim().toLowerCase()
    const filtered = rows.filter((r) => {
      if (q && !String(r[nk] ?? '').toLowerCase().includes(q)) return false
      if (entity === 'player' && position !== 'All' && r.position !== position) return false
      if (team !== 'All' && r[tk] !== team) return false
      for (const [key, range] of Object.entries(ranges)) {
        const val = r[key]
        if (typeof val !== 'number') {
          if (range.min !== '' || range.max !== '') return false
          continue
        }
        if (range.min !== '' && val < Number(range.min)) return false
        if (range.max !== '' && val > Number(range.max)) return false
      }
      return true
    })
    const { key, dir } = sort
    const mul = dir === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      const av = a[key]
      const bv = b[key]
      if (av === null || av === undefined) return 1
      if (bv === null || bv === undefined) return -1
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * mul
      return String(av).localeCompare(String(bv)) * mul
    })
  }, [rows, entity, search, position, team, ranges, sort])

  function switchEntity(next: Entity) {
    setEntity(next)
    setSort({ key: DEFAULT_SORT[next], dir: 'desc' })
    setRanges({})
    setPosition('All')
    setTeam('All')
    setExpandedId(null)
  }

  function toggleSort(col: ColumnDef) {
    setSort((prev) =>
      prev.key === col.key
        ? { key: col.key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key: col.key, dir: col.numeric ? 'desc' : 'asc' },
    )
  }

  function setRange(key: string, bound: 'min' | 'max', value: string) {
    setRanges((prev) => ({
      ...prev,
      [key]: { min: '', max: '', ...prev[key], [bound]: value },
    }))
  }

  function clearFilters() {
    setSearch('')
    setPosition('All')
    setTeam('All')
    setRanges({})
  }

  return (
    <div className="tab-content stats-explorer">
      <div className="sub-tab-bar">
        <button
          type="button"
          className={entity === 'player' ? 'tab-active' : ''}
          onClick={() => switchEntity('player')}
        >
          Players
        </button>
        <button
          type="button"
          className={entity === 'team' ? 'tab-active' : ''}
          onClick={() => switchEntity('team')}
        >
          Teams
        </button>
      </div>

      <div className="stats-toolbar">
        <div className="segmented">
          <button
            type="button"
            className={timeWindow === 'season' ? 'seg-active' : ''}
            onClick={() => setTimeWindow('season')}
          >
            Season
          </button>
          <button
            type="button"
            className={timeWindow === 'last5' ? 'seg-active' : ''}
            onClick={() => setTimeWindow('last5')}
          >
            Last 5
          </button>
        </div>
        <button
          type="button"
          className="filters-toggle"
          onClick={() => setFiltersOpen((o) => !o)}
        >
          Filters {filtersOpen ? '▲' : '▼'}
        </button>
      </div>

      {filtersOpen && (
        <div className="filters-drawer">
          <input
            className="filter-search"
            type="text"
            placeholder="Search name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {entity === 'player' && (
            <label className="filter-select">
              Position
              <select
                value={position}
                onChange={(e) => setPosition(e.target.value as (typeof POSITIONS)[number])}
              >
                {POSITIONS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="filter-select">
            Team
            <select value={team} onChange={(e) => setTeam(e.target.value)}>
              {teamOptions.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <div className="range-grid">
            {columns
              .filter((c) => c.numeric)
              .map((c) => (
                <div className="range-row" key={c.key}>
                  <span className="range-label">{c.label}</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    placeholder="min"
                    value={ranges[c.key]?.min ?? ''}
                    onChange={(e) => setRange(c.key, 'min', e.target.value)}
                  />
                  <input
                    type="number"
                    inputMode="decimal"
                    placeholder="max"
                    value={ranges[c.key]?.max ?? ''}
                    onChange={(e) => setRange(c.key, 'max', e.target.value)}
                  />
                </div>
              ))}
          </div>
          <button type="button" className="clear-filters" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
      )}

      {state.status === 'loading' && <p>loading stats…</p>}
      {state.status === 'error' && <p>couldn't load stats.</p>}
      {state.status === 'empty' && <p className="empty-state">stats unlock after GW1.</p>}

      {state.status === 'data' && (
        <>
          <p className="stats-count">
            {visible.length} {entity === 'player' ? 'players' : 'teams'}
          </p>
          <div className="stats-table-wrap">
            <table className="stats-table">
              <thead>
                <tr>
                  {columns.map((c, i) => (
                    <th
                      key={c.key}
                      className={i === 0 ? 'sticky-col' : ''}
                      onClick={() => toggleSort(c)}
                    >
                      {c.label}
                      {sort.key === c.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => {
                  const id = rowId(entity, r)
                  const isExpanded = entity === 'player' && expandedId === id
                  return (
                    <Fragment key={id}>
                      <tr
                        className={entity === 'player' ? 'clickable-row' : ''}
                        onClick={() => {
                          if (entity === 'player') setExpandedId(isExpanded ? null : id)
                        }}
                      >
                        {columns.map((c, i) => (
                          <td
                            key={c.key}
                            className={`${i === 0 ? 'sticky-col' : ''} ${c.numeric ? 'num' : ''}`}
                          >
                            {formatCell(r[c.key], c)}
                          </td>
                        ))}
                      </tr>
                      {isExpanded && (
                        <tr className="detail-row">
                          <td colSpan={columns.length}>
                            <PlayerDetail playerId={id} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Wire the tab into `Shell.tsx`**

In `web/src/components/Shell.tsx`, add the import after the `Rivals` import:

```tsx
import { StatsExplorer } from '../tabs/StatsExplorer'
```

Change the `TABS` array to (adds `stats` between `rivals` and `charts`):

```tsx
const TABS = [
  { id: 'this-week', label: 'This week' },
  { id: 'transfers', label: 'Transfers' },
  { id: 'rivals', label: 'Rivals' },
  { id: 'stats', label: 'Stats' },
  { id: 'charts', label: 'Charts' },
] as const
```

Add the render line in `<main>` after the `rivals` line:

```tsx
        {activeTab === 'stats' && <StatsExplorer />}
```

- [ ] **Step 3: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/tabs/StatsExplorer.tsx web/src/components/Shell.tsx
git commit -m "Phase 3C — Stats Explorer tab (players/teams, season/last5, sort, expand)"
```

---

## Task 6: Styling

**Files:**
- Modify: `web/src/App.css` (append at end)

- [ ] **Step 1: Append the styles**

Add to the end of `web/src/App.css`:

```css
/* ---------- Stats Explorer ---------- */
.stats-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.segmented {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.segmented button {
  padding: 6px 14px;
  background: none;
  border: none;
  color: var(--text);
  font-size: 14px;
}

.segmented button.seg-active {
  background: var(--accent-bg);
  color: var(--accent);
  font-weight: 600;
}

.filters-toggle {
  margin-left: auto;
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: none;
  color: var(--text);
  font-size: 14px;
}

.filters-drawer {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  margin-bottom: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--social-bg);
}

.filters-drawer .filter-search,
.filters-drawer select {
  font-size: 16px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-h);
}

.filter-select {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--text);
}

.range-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 6px;
}

.range-row {
  display: grid;
  grid-template-columns: 1fr 72px 72px;
  align-items: center;
  gap: 8px;
}

.range-row .range-label {
  font-size: 13px;
  color: var(--text);
}

.range-row input {
  font-size: 14px;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-h);
  width: 100%;
  box-sizing: border-box;
}

.clear-filters {
  align-self: flex-start;
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: none;
  color: var(--text);
  font-size: 13px;
}

.stats-count {
  font-size: 13px;
  color: var(--text);
  margin: 0 0 8px;
}

.stats-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  border: 1px solid var(--border);
  border-radius: 8px;
}

.stats-table {
  border-collapse: collapse;
  font-size: 13px;
  white-space: nowrap;
}

.stats-table th,
.stats-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}

.stats-table th {
  position: sticky;
  top: 0;
  background: var(--code-bg);
  color: var(--text-h);
  cursor: pointer;
  user-select: none;
}

.stats-table th:not(.sticky-col),
.stats-table td.num {
  text-align: right;
}

.stats-table .sticky-col {
  position: sticky;
  left: 0;
  z-index: 1;
  background: var(--bg);
  text-align: left;
  font-weight: 600;
  color: var(--text-h);
}

.stats-table thead .sticky-col {
  z-index: 2;
  background: var(--code-bg);
}

.stats-table .clickable-row {
  cursor: pointer;
}

.stats-table .clickable-row:hover .sticky-col {
  background: var(--accent-bg);
}

.stats-table .detail-row td {
  background: var(--social-bg);
  white-space: normal;
}
```

- [ ] **Step 2: Verify build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/App.css
git commit -m "Phase 3C — Stats Explorer styles"
```

---

## Task 7: Browser verification pass

No code changes — this is the manual acceptance gate (there is no automated UI test harness in this project).

**Files:** none.

- [ ] **Step 1: Launch the preview**

Start the dev server via the preview tool (or `cd web && npm run dev -- --host`) and open the app. Sign in with the magic-link/OTP flow (owner email `andremadian@gmail.com`).

- [ ] **Step 2: Walk through the acceptance checklist**

Open the **Stats** tab and confirm:

1. **Players / Teams** sub-tabs switch the table (players show Pos/price/xG…; teams show W/D/L/GF/GA…).
2. **Season / Last 5** toggle re-fetches: in Last-5, the players table drops the `ICT` column; teams drop `Str H`/`Str A`.
3. **Sort:** clicking a header sorts; clicking again flips asc/desc; the ▲/▼ indicator tracks it. Default players sort = Pts desc; teams = Pts desc.
4. **Sticky name + horizontal scroll:** scroll the table sideways on a narrow viewport (resize to 375px) — the name column stays pinned, metric columns scroll under it.
5. **Filters drawer:** open it; type a name → table narrows live; pick a position (players) and a team → narrows; set e.g. `xGI min = 3` → only players at/above 3 remain; **Clear filters** resets everything.
6. **Player expand:** tap a player row → the price/ownership sparklines + season stats expand below (same detail as Transfers). Teams rows do not expand.
7. **Empty/edge:** if the current data is pre-GW1, confirm the "stats unlock after GW1." empty state shows for players (teams may still list all 20 clubs with zeros — expected).

- [ ] **Step 3: Confirm no console / network errors**

Use the preview tools to read console messages and network requests: no red errors, the `*_explorer_*` view requests return 200. Capture a screenshot of the populated table for the record.

- [ ] **Step 4: Fix-forward if needed**

If any check fails, diagnose against the source, edit the relevant file, re-run `cd web && npm run build`, and re-verify from Step 1. Commit any fix with a descriptive message.

---

## Task 8: Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/TODOS.md`

- [ ] **Step 1: Update `CLAUDE.md`**

Make these edits:

1. **Phase table** — add a row after the Phase 3B row:

```markdown
| 3C. Stats Explorer | ✅ shipped (Jul 2026) | 5th PWA tab: filterable/sortable players & teams tables (season + last-5), migration 0010 (4 explorer views). Reads Supabase via anon key. |
```

2. **Migrations list** (both the fenced tree and the "## Migrations" section) — add:

```markdown
        └── 0010_stats_explorer_views.sql   # Phase 3C — player/team × season/last5 stats views
```

and in the "## Migrations" prose section:

```markdown
- **0010** — Phase 3C. Four `security_invoker` views (`player_explorer_season/last5`, `team_explorer_season/last5`) powering the Stats tab. Read-only, current-season-anchored; no engine changes. Apply via SQL Editor.
```

3. **PWA section** — change "Four tabs" to "Five tabs" and add the Stats tab to the list:

```markdown
Five tabs in `src/tabs/`: **This week**, **Transfers**, **Rivals** (war room), **Stats** (explorer — filterable/sortable player & team tables from the `*_explorer_*` views), **Chart maker** (bubble chart).
```

4. **Schema cheat sheet** — add:

```markdown
- **`player_explorer_season` / `player_explorer_last5`** — Phase 3C views. One row per player with the full metric set (goals/assists/xG/xA/xGI/xGC/CS/CBIT/BPS/ICT/points_per_90/points_per_million/…), season totals or last-5-GW form. Read by the Stats tab.
- **`team_explorer_season` / `team_explorer_last5`** — Phase 3C views. One row per club: W/D/L, GF/GA/GD, points, clean sheets (from finished `fixtures`), xG/xA/xGC (from `team_history`), strength ratings.
```

- [ ] **Step 2: Update `docs/TODOS.md`**

Add a "Phase 3C" completed entry after the Phase 3B session list:

```markdown
## Phase 3C — Stats Explorer (shipped 2026-07-25)

- [x] **Stats Explorer tab** — 5th PWA tab. Migration 0010 adds four `security_invoker` views (`player_explorer_season/last5`, `team_explorer_season/last5`). Filterable (name search + position/team dropdowns + per-metric min/max ranges), sortable, season/last-5 toggle, sticky-name horizontal-scroll table, player-row expand (shared `PlayerDetail`). Spec: [superpowers/specs/2026-07-25-stats-explorer-design.md](superpowers/specs/2026-07-25-stats-explorer-design.md); plan: [superpowers/plans/2026-07-25-stats-explorer.md](superpowers/plans/2026-07-25-stats-explorer.md).
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/TODOS.md
git commit -m "Phase 3C — docs: Stats Explorer in CLAUDE.md + TODOS"
```

---

## Self-review notes (for the implementer)

- **View/interface/column drift:** the three column-name contracts must stay in lockstep — the SQL `select ... as <name>` (Task 1), the TS interface fields (Task 2), and the `ColumnDef.key`s (Task 3). If you rename a column, change all three.
- **`points_per_90` source differs by window:** season reads `players_master.points_per_90`; last-5 computes `pts*90/mins`. Both expose the same column name, so one interface covers both — intended.
- **`ict_index` / `strength_*` are season-only in the UI** (`windows: ['season']`) even though the last-5 views still expose the columns. Don't remove them from the last-5 views — the shared interface expects them.
- **Numeric parsing:** PostgREST returns SQL `numeric` as JSON numbers, so `typeof val === 'number'` holds for filtering/sorting. If a column ever comes back as a string, the range filter would silently drop it — spot-check during Task 7.
- **Migration is applied by hand** (SQL Editor); the agent cannot run it. Task 1 Step 3's verification queries are how you confirm it took.
