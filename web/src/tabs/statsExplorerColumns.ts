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
