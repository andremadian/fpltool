import { useMemo, useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { useSupabaseQuery } from '../hooks/useSupabaseQuery'
import type {
  LeagueRival,
  LeagueTemplateVsGlobal,
  MySquadVsRival,
  RivalCaptainConsensus,
  RivalTransfer,
  TrackedLeague,
} from '../types/db'

/**
 * Standings for one league — my `is_me` row included, gap-to-leader read
 * from the stored league totals (no client-side reconstruction, loophole #16).
 */
function Standings({ leagueId }: { leagueId: number }) {
  const state = useSupabaseQuery<LeagueRival>(
    () =>
      supabase
        .from('league_rivals')
        .select('*')
        .eq('league_id', leagueId)
        .order('league_rank', { ascending: true }),
    [leagueId],
  )

  if (state.status === 'loading') return <section className="card">loading standings…</section>
  if (state.status === 'error') return <section className="card">couldn't load standings.</section>
  if (state.status === 'empty') {
    return (
      <section className="card empty-state">
        rival squads appear after the first post-deadline capture (Saturday 10am).
      </section>
    )
  }

  const leaderPoints = Math.max(...state.data.map((r) => r.total_points ?? 0))

  return (
    <section className="card">
      <h2>Standings</h2>
      <ol className="standings-list">
        {state.data.map((r) => {
          const gap = leaderPoints - (r.total_points ?? 0)
          return (
            <li key={r.rival_fpl_team_id} className={r.is_me ? 'standings-me' : ''}>
              <span className="standings-rank">{r.league_rank ?? '–'}</span>
              <span className="standings-name">
                {r.rival_player_name ?? r.rival_name ?? `team ${r.rival_fpl_team_id}`}
                {r.is_me ? ' (you)' : ''}
              </span>
              <span className="standings-points">{r.total_points ?? 0}</span>
              <span className="standings-gap">{gap > 0 ? `-${gap}` : 'leader'}</span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function CaptainConsensus() {
  const state = useSupabaseQuery<RivalCaptainConsensus>(
    () =>
      supabase
        .from('rival_captain_consensus')
        .select('*')
        .order('n_rivals_captaining', { ascending: false }),
    [],
  )

  return (
    <section className="card">
      <h2>Captain consensus</h2>
      {state.status === 'loading' && <p>loading…</p>}
      {state.status === 'error' && <p>couldn't load captain consensus.</p>}
      {state.status === 'empty' && (
        <p className="empty-state">no rival captains captured yet.</p>
      )}
      {state.status === 'data' && (
        <ul className="rival-list">
          {state.data.slice(0, 8).map((c) => (
            <li key={c.captain_player_name}>
              <span className="player-name">
                {c.captain_player_name} ({c.captain_team})
              </span>
              <span className="rival-meta">
                {c.n_rivals_captaining} rivals · {(c.pct_of_rivals_captaining ?? 0).toFixed(1)}% ·{' '}
                {c.captain_points_scored} pts
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Differentials() {
  const state = useSupabaseQuery<MySquadVsRival>(
    () =>
      supabase
        .from('my_squad_vs_rivals')
        .select('*')
        .order('rival_ownership_pct', { ascending: true, nullsFirst: true }),
    [],
  )

  return (
    <section className="card">
      <h2>My differentials</h2>
      <p className="note">your squad, least-owned by rivals first</p>
      {state.status === 'loading' && <p>loading…</p>}
      {state.status === 'error' && <p>couldn't load differentials.</p>}
      {state.status === 'empty' && (
        <p className="empty-state">no squad or rival snapshot yet.</p>
      )}
      {state.status === 'data' && (
        <ul className="rival-list">
          {state.data.map((p) => (
            <li key={p.player_name}>
              <span className="player-name">
                {p.player_name} ({p.team_short_name})
              </span>
              <span className="rival-meta">
                {(p.rival_ownership_pct ?? 0).toFixed(1)}% of rivals own · £{p.price}m
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function LeagueTemplate() {
  const state = useSupabaseQuery<LeagueTemplateVsGlobal>(
    () =>
      supabase
        .from('league_template_vs_global')
        .select('*')
        .order('template_delta', { ascending: false, nullsFirst: false }),
    [],
  )

  return (
    <section className="card">
      <h2>Mini-league template</h2>
      <p className="note">heavily owned by rivals, rare globally</p>
      {state.status === 'loading' && <p>loading…</p>}
      {state.status === 'error' && <p>couldn't load template picks.</p>}
      {state.status === 'empty' && (
        <p className="empty-state">no rival-favoured differentials right now.</p>
      )}
      {state.status === 'data' && (
        <ul className="rival-list">
          {state.data.map((p) => (
            <li key={p.player_name}>
              <span className="player-name">
                {p.player_name} ({p.team_short_name})
              </span>
              <span className="rival-meta">
                rivals {(p.rival_ownership_pct ?? 0).toFixed(1)}% vs global{' '}
                {p.global_ownership_pct.toFixed(1)}% (+{(p.template_delta ?? 0).toFixed(1)})
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function RivalTransfers() {
  const state = useSupabaseQuery<RivalTransfer>(
    () =>
      supabase
        .from('rival_transfers_in_out')
        .select('*')
        .order('net_transfers', { ascending: false }),
    [],
  )

  return (
    <section className="card">
      <h2>Rival transfers</h2>
      {state.status === 'loading' && <p>loading…</p>}
      {state.status === 'error' && <p>couldn't load transfers.</p>}
      {state.status === 'empty' && (
        <p className="empty-state">
          transfers need two captured gameweeks — check back after the next deadline.
        </p>
      )}
      {state.status === 'data' && (
        <ul className="rival-list">
          {state.data.slice(0, 10).map((p) => (
            <li key={p.player_name}>
              <span className="player-name">
                {p.player_name} ({p.team_short_name})
              </span>
              <span className="rival-meta">
                <span className={p.net_transfers >= 0 ? 'net-in' : 'net-out'}>
                  {p.net_transfers > 0 ? '+' : ''}
                  {p.net_transfers} net
                </span>{' '}
                (in {p.transfers_in_count} / out {p.transfers_out_count})
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function Rivals() {
  const leaguesState = useSupabaseQuery<TrackedLeague>(
    () => supabase.from('tracked_leagues').select('*').order('league_id', { ascending: true }),
    [],
  )
  const [selectedLeague, setSelectedLeague] = useState<number | null>(null)

  const leagues = useMemo(
    () => (leaguesState.status === 'data' ? leaguesState.data : []),
    [leaguesState],
  )
  const activeLeague = leagues.length === 0 ? null : (selectedLeague ?? leagues[0].league_id)
  const multiLeague = leagues.length > 1

  return (
    <div className="tab-content">
      {leaguesState.status === 'loading' && <section className="card">loading leagues…</section>}
      {leaguesState.status === 'empty' && (
        <section className="card empty-state">
          no tracked leagues yet — add one to <code>tracked_leagues</code> to see rivals.
        </section>
      )}

      {activeLeague !== null && (
        <>
          {multiLeague && (
            <div className="league-selector">
              <label htmlFor="league-select">League</label>
              <select
                id="league-select"
                value={activeLeague}
                onChange={(e) => setSelectedLeague(Number(e.target.value))}
              >
                {leagues.map((l) => (
                  <option key={l.league_id} value={l.league_id}>
                    {l.league_name ?? `league ${l.league_id}`}
                  </option>
                ))}
              </select>
            </div>
          )}

          <Standings leagueId={activeLeague} />

          {multiLeague && (
            <p className="note scope-note">
              consensus, differentials & transfers below span <strong>all tracked leagues</strong>{' '}
              (rival squads are deduped across leagues at ingest).
            </p>
          )}

          <CaptainConsensus />
          <Differentials />
          <LeagueTemplate />
          <RivalTransfers />
        </>
      )}
    </div>
  )
}
