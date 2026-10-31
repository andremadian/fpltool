import { supabase } from '../lib/supabaseClient'
import { useSupabaseQuery } from '../hooks/useSupabaseQuery'
import type { BriefPayload } from './types'

interface WeeklyBriefRow {
  payload: BriefPayload
  generated_at: string
}

export interface BriefState {
  status: 'loading' | 'error' | 'empty' | 'ready'
  brief?: BriefPayload
  generatedAt?: string
}

/** The most recent weekly brief the engine wrote. */
export function useBrief(): BriefState {
  const state = useSupabaseQuery<WeeklyBriefRow>(
    () =>
      supabase
        .from('weekly_brief')
        .select('payload, generated_at')
        .order('generated_at', { ascending: false })
        .limit(1),
    [],
  )

  if (state.status === 'data') {
    const row = state.data[0]
    return { status: 'ready', brief: row.payload, generatedAt: row.generated_at }
  }
  return { status: state.status }
}
