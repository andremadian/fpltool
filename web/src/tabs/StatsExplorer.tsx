import { Fragment, useMemo, useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { useSupabaseQuery } from '../hooks/useSupabaseQuery'
import { PlayerDetail } from '../components/PlayerDetail'
import {
  PLAYER_COLUMNS,
  TEAM_COLUMNS,
  type ColumnDef,
  type Entity,
  type StatsWindow,
} from './statsExplorerColumns'
import type { PlayerExplorerRow, TeamExplorerRow } from '../types/db'

type Row = Record<string, string | number | null>

interface SortState {
  key: string
  dir: 'asc' | 'desc'
}

interface RangeInput {
  min: string
  max: string
}

const POSITIONS = ['All', 'GKP', 'DEF', 'MID', 'FWD'] as const

const DEFAULT_SORT: Record<Entity, string> = {
  player: 'total_points',
  team: 'points',
}

function viewName(entity: Entity, win: StatsWindow): string {
  return `${entity}_explorer_${win}`
}

function nameKey(entity: Entity): string {
  return entity === 'player' ? 'web_name' : 'short_name'
}

function teamKey(entity: Entity): string {
  return entity === 'player' ? 'team' : 'short_name'
}

function rowId(entity: Entity, row: Row): number {
  return Number(entity === 'player' ? row.player_id : row.team_id)
}

function formatCell(value: string | number | null, col: ColumnDef): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    const text = Number.isInteger(value) ? String(value) : value.toFixed(2)
    return col.unit ? `${text}${col.unit}` : text
  }
  return String(value)
}

export function StatsExplorer() {
  const [entity, setEntity] = useState<Entity>('player')
  const [timeWindow, setTimeWindow] = useState<StatsWindow>('season')
  const [search, setSearch] = useState('')
  const [position, setPosition] = useState<(typeof POSITIONS)[number]>('All')
  const [team, setTeam] = useState('All')
  const [ranges, setRanges] = useState<Record<string, RangeInput>>({})
  const [sort, setSort] = useState<SortState>({ key: DEFAULT_SORT.player, dir: 'desc' })
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const view = viewName(entity, timeWindow)
  const state = useSupabaseQuery<PlayerExplorerRow | TeamExplorerRow>(
    () => supabase.from(view).select('*'),
    [view],
  )

  const columns = useMemo(
    () =>
      (entity === 'player' ? PLAYER_COLUMNS : TEAM_COLUMNS).filter((c) =>
        c.windows.includes(timeWindow),
      ),
    [entity, timeWindow],
  )

  // Deliberate erasure to a dynamic record so cells can be read by column key;
  // the PlayerExplorerRow/TeamExplorerRow types document the view contract.
  const rows = useMemo(
    () => (state.status === 'data' ? (state.data as unknown as Row[]) : []),
    [state],
  )

  const teamOptions = useMemo(() => {
    const key = teamKey(entity)
    const set = new Set<string>()
    for (const r of rows) {
      const v = r[key]
      if (typeof v === 'string') set.add(v)
    }
    return ['All', ...[...set].sort()]
  }, [rows, entity])

  const visible = useMemo(() => {
    const activeRangeKeys = new Set(columns.filter((c) => c.numeric).map((c) => c.key))
    const nk = nameKey(entity)
    const tk = teamKey(entity)
    const q = search.trim().toLowerCase()
    const filtered = rows.filter((r) => {
      if (q && !String(r[nk] ?? '').toLowerCase().includes(q)) return false
      if (entity === 'player' && position !== 'All' && r.position !== position) return false
      if (team !== 'All' && r[tk] !== team) return false
      for (const [key, range] of Object.entries(ranges)) {
        if (!activeRangeKeys.has(key)) continue
        const val = r[key]
        if (typeof val !== 'number') {
          if (range.min !== '' || range.max !== '') return false
          continue
        }
        if (range.min !== '' && val < Number(range.min)) return false
        if (range.max !== '' && val > Number(range.max)) return false
      }
      return true
    })
    const { key, dir } = sort
    const mul = dir === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      const av = a[key]
      const bv = b[key]
      if (av === null || av === undefined) return 1
      if (bv === null || bv === undefined) return -1
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * mul
      return String(av).localeCompare(String(bv)) * mul
    })
  }, [rows, entity, search, position, team, ranges, sort, columns])

  function switchEntity(next: Entity) {
    setEntity(next)
    setSort({ key: DEFAULT_SORT[next], dir: 'desc' })
    setRanges({})
    setPosition('All')
    setTeam('All')
    setExpandedId(null)
  }

  function toggleSort(col: ColumnDef) {
    setSort((prev) =>
      prev.key === col.key
        ? { key: col.key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key: col.key, dir: col.numeric ? 'desc' : 'asc' },
    )
  }

  function setRange(key: string, bound: 'min' | 'max', value: string) {
    setRanges((prev) => {
      const current: RangeInput = prev[key] ?? { min: '', max: '' }
      return { ...prev, [key]: { ...current, [bound]: value } }
    })
  }

  function clearFilters() {
    setSearch('')
    setPosition('All')
    setTeam('All')
    setRanges({})
  }

  return (
    <div className="tab-content stats-explorer">
      <div className="sub-tab-bar">
        <button
          type="button"
          className={entity === 'player' ? 'tab-active' : ''}
          onClick={() => switchEntity('player')}
        >
          Players
        </button>
        <button
          type="button"
          className={entity === 'team' ? 'tab-active' : ''}
          onClick={() => switchEntity('team')}
        >
          Teams
        </button>
      </div>

      <div className="stats-toolbar">
        <div className="segmented">
          <button
            type="button"
            className={timeWindow === 'season' ? 'seg-active' : ''}
            onClick={() => setTimeWindow('season')}
          >
            Season
          </button>
          <button
            type="button"
            className={timeWindow === 'last5' ? 'seg-active' : ''}
            onClick={() => setTimeWindow('last5')}
          >
            Last 5
          </button>
        </div>
        <button
          type="button"
          className="filters-toggle"
          onClick={() => setFiltersOpen((o) => !o)}
        >
          Filters {filtersOpen ? '▲' : '▼'}
        </button>
      </div>

      {filtersOpen && (
        <div className="filters-drawer">
          <input
            className="filter-search"
            type="text"
            placeholder="Search name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {entity === 'player' && (
            <label className="filter-select">
              Position
              <select
                value={position}
                onChange={(e) => setPosition(e.target.value as (typeof POSITIONS)[number])}
              >
                {POSITIONS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
          )}
          {entity === 'player' && (
            <label className="filter-select">
              Team
              <select value={team} onChange={(e) => setTeam(e.target.value)}>
                {teamOptions.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="range-grid">
            {columns
              .filter((c) => c.numeric)
              .map((c) => (
                <div className="range-row" key={c.key}>
                  <span className="range-label">{c.label}</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    placeholder="min"
                    value={ranges[c.key]?.min ?? ''}
                    onChange={(e) => setRange(c.key, 'min', e.target.value)}
                  />
                  <input
                    type="number"
                    inputMode="decimal"
                    placeholder="max"
                    value={ranges[c.key]?.max ?? ''}
                    onChange={(e) => setRange(c.key, 'max', e.target.value)}
                  />
                </div>
              ))}
          </div>
          <button type="button" className="clear-filters" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
      )}

      {state.status === 'loading' && <p>loading stats…</p>}
      {state.status === 'error' && <p>couldn't load stats.</p>}
      {state.status === 'empty' && <p className="empty-state">stats unlock after GW1.</p>}

      {state.status === 'data' && (
        <>
          <p className="stats-count">
            {visible.length} {entity === 'player' ? 'players' : 'teams'}
          </p>
          <div className="stats-table-wrap">
            <table className="stats-table">
              <thead>
                <tr>
                  {columns.map((c, i) => (
                    <th
                      key={c.key}
                      className={i === 0 ? 'sticky-col' : ''}
                      onClick={() => toggleSort(c)}
                    >
                      {c.label}
                      {sort.key === c.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => {
                  const id = rowId(entity, r)
                  const isExpanded = entity === 'player' && expandedId === id
                  return (
                    <Fragment key={id}>
                      <tr
                        className={entity === 'player' ? 'clickable-row' : ''}
                        onClick={() => {
                          if (entity === 'player') setExpandedId(isExpanded ? null : id)
                        }}
                      >
                        {columns.map((c, i) => (
                          <td
                            key={c.key}
                            className={`${i === 0 ? 'sticky-col' : ''} ${c.numeric ? 'num' : ''}`}
                          >
                            {formatCell(r[c.key], c)}
                          </td>
                        ))}
                      </tr>
                      {isExpanded && (
                        <tr className="detail-row">
                          <td colSpan={columns.length}>
                            <PlayerDetail playerId={id} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
