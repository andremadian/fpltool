import { useMemo, useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { useSupabaseQuery } from '../hooks/useSupabaseQuery'
import { Sparkline } from '../components/Sparkline'
import type { PlayerDaily, PlayerSeasonStats, ProjectionRow } from '../types/db'

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

function PlayerDetail({ playerId }: { playerId: number }) {
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
