# Stats Explorer (Phase 3C) — Design

**Date:** 2026-07-25
**Status:** Approved, ready for implementation plan
**Scope:** Add a fifth PWA tab that lets the user browse the players & teams
database through a friendly, filterable, sortable table UI.

## Goal

Give FPL Sniper a "Stats Explorer" tab: a spreadsheet-like surface over the
current-season player and team data already in Supabase, with a rich metric
set and per-metric filtering — the raw research surface Supabase Studio
provides, but usable from the phone PWA.

This is Phase 3C — an expansion of the shipped Phase 3B PWA, before Phase 4.

## User-approved decisions

Captured during brainstorming (2026-07-25):

1. **Filter depth:** per-metric range filters. On top of name search +
   position + team dropdowns, every numeric metric gets a min/max control.
2. **Time window:** Season totals **and** a Last-5-gameweeks toggle — every
   metric switches between the two windows.
3. **Mobile columns:** sticky name column + horizontal scroll for the metric
   columns (installable mobile PWA is the primary surface).
4. **points_per_90** kept as the meaningful normalization (not a literal
   near-zero points-per-minute); **points_per_million** added as the value
   metric FPL managers actually use.
5. **Player row tap → expand** the existing price/ownership 30-day sparkline
   detail (reused from the Transfers tab). Teams have no expand.

## Architecture

### Approach: fetch-whole-view + client-side filter/sort

One fetch per (entity, window) via the existing `useSupabaseQuery` hook, then
all searching, range-filtering and sorting happen live in memory. ~840 player
rows × ~25 columns is trivial in-browser and gives instant filter feedback
with zero round-trips. This matches how `Transfers` and `Charts` already fetch
an entire curated view and process it in-memory.

Rejected alternatives:
- **Push filters to Supabase (`.gte`/`.lte` query params):** adds a network
  round-trip on every slider tweak for no benefit at this row count.
- **One mega-view with season + last-5 columns side by side:** wide rows,
  awkward column names, toggling would just hide columns. Parallel view pairs
  are cleaner and keep each view's select list readable.

The engines and base tables are **not** touched. Per the CLAUDE.md contract,
the PWA reads only through RLS-locked curated views with the anon key; new
data shapes come from a new migration, never from loosening RLS or hitting
base tables from the browser.

## Data layer — migration `0010_stats_explorer_views.sql`

Four new views. Every view is created `with (security_invoker = on)` and gets
`grant select ... to authenticated`, following the loophole #19 convention
established in migration 0008 (new views run as the querying user; RLS on the
base tables — which 0008 enabled with an owner-read policy on all public
tables — resolves for the signed-in owner). **No new tables**, so no new RLS
policy is required. All four self-anchor on the current season
(`max(season) from fixtures` / `player_history`), consistent with decision #10.

### `player_explorer_season` / `player_explorer_last5`

One row per player. Columns (both windows share the shape except where noted):

| Column | Source (season) | Source (last-5) |
|--------|-----------------|-----------------|
| `player_id` | `players_master.id` | same |
| `web_name` | `players_master` | same |
| `team` (short) | `teams.short_name` | same |
| `position` | `players_master` | same |
| `price` | `players_master` | same |
| `status` | `players_master` | same |
| `ownership` | `players_master` | same |
| `minutes` | Σ `player_history.minutes` | Σ over last-5 GWs |
| `total_points` | Σ `player_history.total_points` | Σ over last-5 |
| `points_per_90` | `players_master.points_per_90` | `pts*90/mins` computed |
| `points_per_million` | `total_points / price` | `total_points / price` |
| `goals` | Σ `player_history.goals` | Σ over last-5 |
| `assists` | Σ `player_history.assists` | Σ over last-5 |
| `goal_involvements` | Σ (goals+assists) | Σ over last-5 |
| `xg` | `players_master.xg` | Σ `player_history.xg` last-5 |
| `xa` | `players_master.xa` | Σ `player_history.xa` last-5 |
| `xgi` | `players_master.xgi` | Σ `player_history.xgi` last-5 |
| `xgc` | `players_master.xgc` | Σ `player_history.xgc` last-5 |
| `clean_sheets` | Σ `player_history.clean_sheets` | Σ over last-5 |
| `cbit` | Σ `player_history.cbit` | Σ over last-5 |
| `bps` | Σ `player_history.bps` | Σ over last-5 |
| `ict_index` | `players_master.ict_index` | **null** (not per-GW) |
| `form` | `players_master.form` | `players_master.form` |

Notes:
- Season view mirrors the existing `player_season_stats` view: counting stats
  summed from `player_history`, rate/expected stats read from
  `players_master` (the FPL API's own season figures — avoids DGW
  double-count nuance).
- Last-5 = the 5 most recent GWs where `minutes > 0`, using the same
  `row_number() over (partition by player_id order by gw desc)` recency logic
  as the projection views (migrations 0008/0009).
- `player_history` has **no** per-player goals-conceded column, so goals
  conceded is a team-level metric only; players surface `clean_sheets`.
- `ict_index` exists only as a season cumulative in `players_master`, so it is
  null in the last-5 view (the UI renders "—").

### `team_explorer_season` / `team_explorer_last5`

One row per club. Columns:

| Column | Source |
|--------|--------|
| `team_id` | `teams.id` |
| `short_name`, `name` | `teams` |
| `matches_played` | count of finished `fixtures` involving the team |
| `wins`, `draws`, `losses` | derived from finished `fixtures` scores |
| `points` | `wins*3 + draws` |
| `goals_for` | Σ goals the team scored (home+away perspectives) |
| `goals_against` | Σ goals conceded |
| `goal_difference` | `goals_for - goals_against` |
| `clean_sheets` | count of finished fixtures with 0 conceded |
| `total_xg` | Σ `team_history.total_xg` |
| `total_xa` | Σ `team_history.total_xa` |
| `xgc` | Σ `team_history.team_xgc` |
| `strength_home`, `strength_away` | `teams.strength_overall_home/away` |

Notes:
- W/D/L, GF/GA/GD, clean sheets, matches come from **finished `fixtures`**:
  a CTE unions each fixture's home perspective (scored `home_score`, conceded
  `away_score`) with its away perspective, then aggregates per team.
- xG/xA/xGC come from `team_history` (which aggregates `player_history` to
  team level per GW; `team_xgc` is `MAX(xgc)` across the squad by design —
  see migration 0002 rationale — so summing it across GWs is the team's
  season expected-goals-conceded proxy).
- Last-5 = the last 5 finished fixtures per team (both the fixtures CTE and
  the team_history aggregation windowed to those GWs).

## Frontend — `web/src/tabs/StatsExplorer.tsx`

New tab wired into `Shell.tsx`; nav grows from 4 to 5 tabs, in this order:
This week / Transfers / Rivals / Stats / Charts (Stats sits before Charts).

### Layout

- **Sub-tab bar:** `Players | Teams` (same component pattern as the Transfers
  attackers/defenders sub-tab).
- **Window toggle:** `Season | Last 5` segmented control. Switching refetches
  the corresponding view.
- **Collapsible Filters drawer:**
  - name search (text input, case-insensitive substring)
  - position dropdown (players only): All / GKP / DEF / MID / FWD
  - team dropdown: All teams + each club
  - **per-metric min/max number inputs** for every numeric column in the
    active column set. Live-applied. Collapsed by default on mobile.
  - a "Clear filters" reset.
- **Table:**
  - sticky first column (player/team name) via CSS `position: sticky`;
    metric columns scroll horizontally inside an `overflow-x: auto` wrapper.
  - click any column header to sort; toggles asc/desc; shows a sort-direction
    indicator. Default sort: `total_points` desc.
  - numeric cells right-aligned; null renders as "—".
- **Player row tap → expand:** reuses the `Sparkline` component + a
  `player_daily` query (price + ownership, last 30 days), same as the
  `PlayerDetail` in `Transfers.tsx`. Extract/share that detail rather than
  duplicating it if clean to do so. Teams do not expand.

### Column configuration (single source of truth)

A declarative array drives both the table headers and the range-filter list:

```ts
interface ColumnDef {
  key: string          // matches the view column
  label: string        // header text
  unit?: string        // e.g. '£m', '%'
  entity: 'player' | 'team'
  windows: ('season' | 'last5')[]  // which windows expose it
  numeric: boolean     // numeric → gets a range filter + is sortable numerically
  higherIsBetter?: boolean  // reserved for future good/bad coloring
}
```

Adding a metric later is a one-line change. `ict_index` lists only `['season']`
so it disappears from the last-5 view and its filter.

### State & data flow

- Component state: `entity` ('player'|'team'), `window` ('season'|'last5'),
  `search`, `positionFilter`, `teamFilter`, `ranges: Record<key,{min,max}>`,
  `sort: {key, dir}`, `expandedId`.
- `useSupabaseQuery` fetches the view named
  `${entity}_explorer_${window}` — dependency array `[entity, window]`.
- A `useMemo` derives the visible rows: filter (search + dropdowns + ranges)
  then sort. Recomputes on any filter/sort change; the fetch does not.
- New TypeScript interfaces `PlayerExplorerRow` and `TeamExplorerRow` in
  `web/src/types/db.ts`.

### Styling

Extend `web/src/App.css`: `.stats-explorer` container, sticky-column table
styles, the filters drawer, the segmented window toggle. Match the existing
dark theme and the spacing/typography of the other tabs.

## Error / edge handling

- Loading / error / empty are handled by the existing `useSupabaseQuery`
  states. Empty state copy: "stats unlock after GW1." (pre-season the views
  return no rows, same as the projection views).
- Last-5 for a player with fewer than 5 played GWs simply aggregates what
  exists (no minimum-games gate — this is exploration, not a shortlist).
- Null metrics (e.g. `ict_index` in last-5, expected stats before they
  populate) render as "—" and sort to the bottom.

## Testing / verification

`web/` has no JS test harness today (no test runner configured). Verification
is therefore:

1. **`cd web && npm run build`** — TypeScript + Vite build passes (this is the
   real type-check gate).
2. **Browser-preview walkthrough** with the preview tools: load the tab →
   toggle Players/Teams → toggle Season/Last-5 → apply a range filter → sort a
   column → expand a player row → confirm no console/network errors →
   screenshot.
3. **Migration sanity:** the four views return rows against the current
   season's data (spot-check row counts and a couple of computed columns).

This is stated explicitly rather than claiming unit coverage that does not
exist in this project.

## Documentation updates

- `CLAUDE.md`: add the four views to the schema cheat sheet, add `0010` to the
  migrations list, update the PWA section (4 → 5 tabs, name the Stats tab),
  add a Phase 3C row to the phase table.
- `docs/TODOS.md`: mark Phase 3C shipped / update backlog.

## Out of scope (YAGNI)

- Saved/named filter presets.
- User-selectable column visibility (deferred; sticky + horizontal scroll
  covers the mobile need).
- Cross-season / historical exploration (current season only, per decision
  #10). Archive tables are not queried.
- Any change to the ingestion engines or existing views.
- Exporting/CSV.
