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

export interface TrackedLeague {
  league_id: number
  league_name: string | null
  my_fpl_team_id: number
  notes: string | null
  added_at: string
}

export interface LeagueRival {
  league_id: number
  rival_fpl_team_id: number
  rival_name: string | null
  rival_player_name: string | null
  total_points: number | null
  league_rank: number | null
  last_rank: number | null
  refreshed_at: string
  is_me: boolean
}

export interface RivalCaptainConsensus {
  season: string
  gw: number
  captain_player_name: string
  captain_team: string
  n_rivals_captaining: number
  pct_of_rivals_captaining: number | null
  captain_points_scored: number
}

export interface MySquadVsRival {
  player_name: string
  team_short_name: string
  position: string
  price: number
  i_own: boolean
  rivals_owning_count: number
  total_rivals: number
  rival_ownership_pct: number | null
  total_points: number
  form: number | null
}

export interface LeagueTemplateVsGlobal {
  player_name: string
  team_short_name: string
  position: string
  price: number
  rival_ownership_pct: number | null
  global_ownership_pct: number
  template_delta: number | null
  form: number | null
  total_points: number
}

export interface RivalTransfer {
  player_name: string
  team_short_name: string
  transfers_in_count: number
  transfers_out_count: number
  net_transfers: number
  n_rivals_owning_now: number
  pct_rival_ownership: number | null
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
