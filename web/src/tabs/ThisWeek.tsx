import { useEffect, useMemo, useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { useSupabaseQuery } from '../hooks/useSupabaseQuery'
import { nextSeasonLabel } from '../lib/season'
import type { AttackersProjectionRow, Gameweek, PlayerDaily, PlayersMasterAlertRow, UserTeamSnapshot } from '../types/db'

function DeadlineCard() {
  const state = useSupabaseQuery<Gameweek>(
    () =>
      supabase
        .from('gameweeks')
        .select('*')
        .eq('finished', false)
        .order('deadline_time', { ascending: true })
        .limit(1),
    [],
  )
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  if (state.status === 'loading') {
    return <section className="card">loading deadline…</section>
  }
  if (state.status === 'error') {
    return <section className="card">couldn't load the deadline.</section>
  }
  if (state.status === 'empty') {
    return (
      <section className="card empty-state">
        Season complete — the {nextSeasonLabel()} schedule appears when FPL resets (~early July).
      </section>
    )
  }

  const gw = state.data[0]
  const deadline = new Date(gw.deadline_time).getTime()
  const remainingMs = Math.max(0, deadline - now)
  const days = Math.floor(remainingMs / (24 * 60 * 60 * 1000))
  const hours = Math.floor((remainingMs / (60 * 60 * 1000)) % 24)
  const minutes = Math.floor((remainingMs / (60 * 1000)) % 60)
  const seconds = Math.floor((remainingMs / 1000) % 60)

  return (
    <section className="card deadline-card">
      <h2>GW{gw.gw} deadline</h2>
      <p className="countdown">
        {days}d {hours}h {minutes}m {seconds}s
      </p>
      <p className="deadline-local">{new Date(gw.deadline_time).toLocaleString()}</p>
    </section>
  )
}

function useLatestSquad() {
  return useSupabaseQuery<UserTeamSnapshot>(
    () =>
      supabase
        .from('user_team_snapshots')
        .select('*')
        .order('season', { ascending: false })
        .order('gw', { ascending: false })
        .limit(1),
    [],
  )
}

interface RankedCaptain {
  player_id: number
  web_name: string
  player_team: string
  totalScore: number
  fixtures: number
}

function rankByPlayer(rows: AttackersProjectionRow[]): RankedCaptain[] {
  const byPlayer = new Map<number, RankedCaptain>()
  for (const row of rows) {
    const existing = byPlayer.get(row.player_id)
    if (existing) {
      existing.totalScore += row.projection_score
      existing.fixtures += 1
    } else {
      byPlayer.set(row.player_id, {
        player_id: row.player_id,
        web_name: row.web_name,
        player_team: row.player_team,
        totalScore: row.projection_score,
        fixtures: 1,
      })
    }
  }
  return [...byPlayer.values()].sort((a, b) => b.totalScore - a.totalScore)
}

function CaptainList() {
  const projectionState = useSupabaseQuery<AttackersProjectionRow>(
    () => supabase.from('attackers_projection').select('*'),
    [],
  )
  const squadState = useLatestSquad()

  if (projectionState.status === 'loading' || squadState.status === 'loading') {
    return <section className="card">loading captain picks…</section>
  }
  if (projectionState.status === 'error') {
    return <section className="card">couldn't load projections.</section>
  }
  if (projectionState.status === 'empty') {
    return (
      <section className="card empty-state">
        projections unlock after GW1 — here's the empty state until then.
      </section>
    )
  }

  const squadIds =
    squadState.status === 'data' ? new Set(squadState.data[0].player_ids) : null
  const ranked = rankByPlayer(projectionState.data)
  const scoped = squadIds ? ranked.filter((r) => squadIds.has(r.player_id)) : ranked
  const top5 = (scoped.length > 0 ? scoped : ranked).slice(0, 5)
  const usedFallback = squadIds !== null && scoped.length === 0

  return (
    <section className="card">
      <h2>Captain picks</h2>
      {squadState.status === 'empty' && (
        <p className="note">no squad snapshot yet — showing unrestricted top 5</p>
      )}
      {usedFallback && (
        <p className="note">none of your squad appear in the projection — showing unrestricted top 5</p>
      )}
      <ol className="captain-list">
        {top5.map((c) => (
          <li key={c.player_id}>
            {c.web_name} ({c.player_team}) — {c.totalScore.toFixed(2)}
            {c.fixtures > 1 ? ` (${c.fixtures} fixtures)` : ''}
          </li>
        ))}
      </ol>
    </section>
  )
}

function Alerts() {
  const squadState = useLatestSquad()
  const squadIds = squadState.status === 'data' ? squadState.data[0].player_ids : []

  const playersState = useSupabaseQuery<PlayersMasterAlertRow>(
    () =>
      squadIds.length > 0
        ? supabase.from('players_master').select('*').in('id', squadIds)
        : Promise.resolve({ data: [], error: null }),
    [squadIds.join(',')],
  )
  const dailyState = useSupabaseQuery<PlayerDaily>(
    () =>
      squadIds.length > 0
        ? supabase
            .from('player_daily')
            .select('*')
            .in('player_id', squadIds)
            .order('as_of_date', { ascending: false })
            .limit(squadIds.length * 2)
        : Promise.resolve({ data: [], error: null }),
    [squadIds.join(',')],
  )

  const statusAlerts = useMemo(() => {
    if (playersState.status !== 'data') return []
    return playersState.data.filter(
      (p) => p.status !== 'a' || Math.abs(p.cost_change_event) > 0,
    )
  }, [playersState])

  const movers = useMemo(() => {
    if (dailyState.status !== 'data') return []
    const byPlayer = new Map<number, PlayerDaily[]>()
    for (const row of dailyState.data) {
      const list = byPlayer.get(row.player_id) ?? []
      list.push(row)
      byPlayer.set(row.player_id, list)
    }
    const diffs: { player_id: number; priceDelta: number; ownDelta: number }[] = []
    for (const [player_id, rows] of byPlayer) {
      if (rows.length < 2) continue
      const [latest, prev] = rows
      diffs.push({
        player_id,
        priceDelta: (latest.price ?? 0) - (prev.price ?? 0),
        ownDelta: (latest.ownership ?? 0) - (prev.ownership ?? 0),
      })
    }
    return diffs
      .filter((d) => d.priceDelta !== 0 || d.ownDelta !== 0)
      .sort((a, b) => Math.abs(b.priceDelta) - Math.abs(a.priceDelta))
      .slice(0, 3)
  }, [dailyState])

  if (squadState.status === 'loading') return <section className="card">loading alerts…</section>
  if (squadState.status === 'empty') {
    return (
      <section className="card empty-state">no squad snapshot yet — no alerts to show</section>
    )
  }

  const hasAlerts = statusAlerts.length > 0 || movers.length > 0

  return (
    <section className="card">
      <h2>Alerts</h2>
      {!hasAlerts && <p className="empty-state">no alerts — quiet day.</p>}
      {statusAlerts.map((p) => (
        <p key={p.id} className="alert-row">
          {p.web_name}: status {p.status ?? 'unknown'}
          {p.news ? ` — ${p.news}` : ''}
          {Math.abs(p.cost_change_event) > 0
            ? ` (price moved ${p.cost_change_event > 0 ? '+' : ''}${p.cost_change_event})`
            : ''}
        </p>
      ))}
      {movers.map((m) => {
        const name =
          playersState.status === 'data'
            ? playersState.data.find((p) => p.id === m.player_id)?.web_name
            : undefined
        return (
          <p key={m.player_id} className="alert-row">
            {name ?? `player ${m.player_id}`}: price Δ{m.priceDelta.toFixed(1)}, ownership Δ
            {m.ownDelta.toFixed(1)}
          </p>
        )
      })}
    </section>
  )
}

export function ThisWeek() {
  return (
    <div className="tab-content">
      <DeadlineCard />
      <CaptainList />
      <Alerts />
    </div>
  )
}
