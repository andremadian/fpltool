export interface Gameweek {
  season: string
  gw: number
  deadline_time: string
  finished: boolean
  is_current: boolean
  is_next: boolean
}

export interface PipelineRun {
  id: number
  engine: string
  season: string | null
  gw: number | null
  rows_written: number
  duration_seconds: number | null
  status: 'success' | 'failed' | 'skipped_offseason' | 'skipped_no_config'
  detail: string | null
  ran_at: string
}

interface ProjectionRowBase {
  player_id: number
  web_name: string
  position: string
  price: number
  fpl_form: number | null
  form_recent: number | null
  form_3gw: number | null
  form_delta: number | null
  upcoming_gw: number
  kickoff_time: string
  venue: 'H' | 'A'
  player_team: string
  opponent: string
  fdr: number
  projection_score: number
}

export interface AttackersProjectionRow extends ProjectionRowBase {
  xgi_per_game: number
  opp_xgc_per_game: number
}

export interface DefendersProjectionRow extends ProjectionRowBase {
  cbit_per_game: number
  own_xgc_per_game: number
  opp_xg_per_game: number
}

export type ProjectionRow = AttackersProjectionRow | DefendersProjectionRow

export interface PlayerDaily {
  season: string
  player_id: number
  as_of_date: string
  price: number | null
  ownership: number | null
  transfers_in_event: number
  transfers_out_event: number
  cost_change_event: number
  status: string | null
  news: string | null
  chance_of_playing_next_round: number | null
  form: number | null
  total_points: number
  captured_at: string
}

export interface PlayerSeasonStats {
  season: string
  player_id: number
  web_name: string
  team_id: number
  position: string
  price: number
  ownership: number
  xg: number | null
  xa: number | null
  xgi: number | null
  xgc: number | null
  form: number | null
  status: string | null
  chance_of_playing_next_round: number | null
  goals: number
  assists: number
  goal_involvements: number
  minutes: number
  total_points: number
  bps: number
  cbit: number
}

export interface PlayersMasterAlertRow {
  id: number
  web_name: string
  position: string
  price: number
  status: string | null
  news: string | null
  chance_of_playing_next_round: number | null
  cost_change_event: number
  ownership: number
  form: number | null
}

export interface UserTeamSnapshot {
  season: string
  fpl_team_id: number
  gw: number
  player_ids: number[]
  captain_id: number | null
  vice_captain_id: number | null
  chip_used: string | null
  bench_order: number[] | null
  transfers_made: number
  transfer_cost: number
  event_points: number | null
  event_rank: number | null
  overall_rank: number | null
  bank: number | null
  team_value: number | null
  refreshed_at: string
}
