export interface PipelineRun {
  id: number
  engine: string
  season: string | null
  gw: number | null
  rows_written: number
  duration_seconds: number | null
  status: 'success' | 'failed' | 'skipped_offseason' | 'skipped_preseason' | 'skipped_no_config'
  detail: string | null
  ran_at: string
}
