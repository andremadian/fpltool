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
