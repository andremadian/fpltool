// Mirrors the version-1 payload built by `brief/payload.py`. Field names and
// nullability match it exactly; change both sides together.

export type Position = 'GKP' | 'DEF' | 'MID' | 'FWD'

export interface PlayerRef {
  id: number
  name: string
  team: string
  pos: Position
  price: number
}

export interface PlayerFlag {
  status: string
  chance: number | null
  news: string
}

export interface PlayerSlot extends PlayerRef {
  proj: number
  flag: PlayerFlag | null
}

export interface CaptainSlot extends PlayerSlot {
  reason: string
}

export interface Transfer {
  out: PlayerRef
  in: PlayerRef
  gain_window: number
  reason: string
}

export interface PrioritySell {
  player: PlayerRef
  reason: string
}

export type ChipCode = 'wildcard' | 'freehit' | 'bboost' | '3xc'

export interface ChipAdvice {
  chip: ChipCode
  gain_now: number
  best_gw: number
  gain_best: number
  play_now: boolean
  reason: string
}

export interface Scenario {
  transfers: Transfer[]
  hit_cost: number
  net_gain_window: number
  hit_note: string | null
  priority_sells: PrioritySell[]
  formation: string
  xi: PlayerSlot[]
  bench: PlayerSlot[]
  captain: CaptainSlot
  vice: PlayerSlot
  projected_points: number
  mode_changed_answer: boolean
  chips: ChipAdvice[]
}

export interface ModeTarget {
  entry_id: number
  team_name: string
  player_name: string
  rank: number
  total: number
}

export interface Mode {
  kind: 'defend' | 'chase'
  my_rank: number
  my_total: number
  /** Target total minus my total: negative when I lead. */
  gap: number
  target: ModeTarget | null
}

export interface RivalRow {
  entry_id: number
  team_name: string
  player_name: string
  rank: number
  total: number
  projected_points: number | null
  captain: string | null
  is_target: boolean
}

export interface BriefInputs {
  bank: number
  squad_ids: number[]
  selling: Record<string, number>
  flagged_ids: number[]
}

export interface BriefPayload {
  version: 1
  season: string
  gw: number
  generated_at: string
  window: number[]
  mode: Mode
  assumption: string
  rivals: RivalRow[]
  /** Keyed by `${ft}_${hits}`, e.g. '2_4'. */
  scenarios: Record<string, Scenario>
  inputs: BriefInputs
}
