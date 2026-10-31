import { useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { useSupabaseQuery } from '../hooks/useSupabaseQuery'
import type { PipelineRun } from '../types/db'

const ENGINES = ['fpl_engine', 'fpl_engine --daily', 'fpl_user_engine', 'fpl_brief_engine'] as const
const DAILY_ENGINE = 'fpl_engine --daily'
const FRESH_WINDOW_MS = 36 * 60 * 60 * 1000
// A daily run that either ingested (`success`) or correctly idled for the
// off-season (`skipped_offseason`) both prove the pipeline is alive — which
// is what loophole #8's badge guards against (a *dead* pipeline). Only a
// `failed` or absent/stale daily run should read amber.
const HEALTHY_DAILY_STATUSES = new Set(['success', 'skipped_offseason'])

function latestPerEngine(rows: PipelineRun[]): Map<string, PipelineRun> {
  const map = new Map<string, PipelineRun>()
  // rows arrive ordered ran_at desc, so the first row seen per engine is the latest.
  for (const row of rows) {
    if (!map.has(row.engine)) map.set(row.engine, row)
  }
  return map
}

export function FreshnessBadge() {
  const [expanded, setExpanded] = useState(false)
  const state = useSupabaseQuery<PipelineRun>(
    () =>
      supabase.from('pipeline_runs').select('*').order('ran_at', { ascending: false }).limit(20),
    [],
  )

  if (state.status === 'loading') {
    return <div className="freshness-badge freshness-loading">checking freshness…</div>
  }
  if (state.status === 'error' || state.status === 'empty') {
    return <div className="freshness-badge freshness-amber">no pipeline runs recorded</div>
  }

  const latest = latestPerEngine(state.data)
  const latestDaily = latest.get(DAILY_ENGINE)
  const isFresh =
    !!latestDaily && Date.now() - new Date(latestDaily.ran_at).getTime() <= FRESH_WINDOW_MS
  const isGreen = isFresh && HEALTHY_DAILY_STATUSES.has(latestDaily.status)

  let label: string
  if (!latestDaily) {
    label = 'no daily run recorded'
  } else if (latestDaily.status === 'skipped_offseason') {
    label = `off-season · ${new Date(latestDaily.ran_at).toLocaleString()}`
  } else {
    label = new Date(latestDaily.ran_at).toLocaleString()
  }

  return (
    <div className="freshness-container">
      <button
        type="button"
        className={`freshness-badge ${isGreen ? 'freshness-green' : 'freshness-amber'}`}
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="freshness-dot" aria-hidden="true" />
        {label}
      </button>
      {expanded && (
        <div className="freshness-panel">
          {ENGINES.map((engine) => {
            const row = latest.get(engine)
            return (
              <div key={engine} className="freshness-row">
                <span>{engine}</span>
                <span>
                  {row ? `${row.status} · ${new Date(row.ran_at).toLocaleString()}` : 'never run'}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
