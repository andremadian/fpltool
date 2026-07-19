import { useMemo, useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { useSupabaseQuery } from '../hooks/useSupabaseQuery'
import type { PlayerSeasonStats, UserTeamSnapshot } from '../types/db'

/** Numeric columns of player_season_stats offered as chart axes (brief §Chart maker). */
const METRICS = [
  { key: 'xg', label: 'xG' },
  { key: 'xa', label: 'xA' },
  { key: 'xgi', label: 'xGI' },
  { key: 'xgc', label: 'xGC' },
  { key: 'goals', label: 'Goals' },
  { key: 'assists', label: 'Assists' },
  { key: 'goal_involvements', label: 'Goal involvements' },
  { key: 'total_points', label: 'Total points' },
  { key: 'minutes', label: 'Minutes' },
  { key: 'price', label: 'Price' },
  { key: 'ownership', label: 'Ownership' },
  { key: 'form', label: 'Form' },
  { key: 'cbit', label: 'CBIT' },
  { key: 'bps', label: 'BPS' },
] as const

type MetricKey = (typeof METRICS)[number]['key']

const POSITIONS = ['all', 'GKP', 'DEF', 'MID', 'FWD'] as const
type PositionFilter = (typeof POSITIONS)[number]

const MY_COLOR = '#1D9E75'
const REST_COLOR = '#378ADD'

// SVG geometry (viewBox coordinates; the element scales to its container).
const W = 360
const H = 360
const M = { top: 16, right: 16, bottom: 44, left: 48 }
const PLOT_W = W - M.left - M.right
const PLOT_H = H - M.top - M.bottom
const MAX_R = 18
const MIN_R = 2.5

function metricValue(p: PlayerSeasonStats, key: MetricKey): number {
  return p[key] ?? 0
}

function labelFor(key: MetricKey): string {
  return METRICS.find((m) => m.key === key)?.label ?? key
}

interface Bubble {
  player_id: number
  name: string
  cx: number
  cy: number
  r: number
  isMine: boolean
  xVal: number
  yVal: number
  sizeVal: number
}

function useLatestSquadIds(): Set<number> | null {
  const state = useSupabaseQuery<UserTeamSnapshot>(
    () =>
      supabase
        .from('user_team_snapshots')
        .select('*')
        .order('season', { ascending: false })
        .order('gw', { ascending: false })
        .limit(1),
    [],
  )
  return state.status === 'data' ? new Set(state.data[0].player_ids) : null
}

export function Charts() {
  const [xKey, setXKey] = useState<MetricKey>('xg')
  const [yKey, setYKey] = useState<MetricKey>('xa')
  const [sizeKey, setSizeKey] = useState<MetricKey>('goal_involvements')
  const [position, setPosition] = useState<PositionFilter>('all')
  const [minMinutes, setMinMinutes] = useState(400)
  const [highlightMine, setHighlightMine] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const state = useSupabaseQuery<PlayerSeasonStats>(
    () => supabase.from('player_season_stats').select('*'),
    [],
  )
  const squadIds = useLatestSquadIds()

  const players = useMemo(() => {
    if (state.status !== 'data') return []
    return state.data.filter(
      (p) =>
        p.minutes >= minMinutes && (position === 'all' || p.position === position),
    )
  }, [state, minMinutes, position])

  const bubbles = useMemo<Bubble[]>(() => {
    if (players.length === 0) return []
    const xs = players.map((p) => metricValue(p, xKey))
    const ys = players.map((p) => metricValue(p, yKey))
    const sizes = players.map((p) => metricValue(p, sizeKey))
    const xMin = Math.min(...xs)
    const xMax = Math.max(...xs)
    const yMin = Math.min(...ys)
    const yMax = Math.max(...ys)
    const sizeMax = Math.max(...sizes)
    const xRange = xMax - xMin || 1
    const yRange = yMax - yMin || 1
    // Area ∝ size metric → radius = k·√v (brief). k pins the largest to MAX_R.
    const k = sizeMax > 0 ? MAX_R / Math.sqrt(sizeMax) : 0

    return players.map((p) => {
      const xVal = metricValue(p, xKey)
      const yVal = metricValue(p, yKey)
      const sizeVal = metricValue(p, sizeKey)
      const cx = M.left + ((xVal - xMin) / xRange) * PLOT_W
      const cy = M.top + PLOT_H - ((yVal - yMin) / yRange) * PLOT_H
      const r = Math.max(MIN_R, k * Math.sqrt(Math.max(0, sizeVal)))
      const isMine = highlightMine && squadIds !== null && squadIds.has(p.player_id)
      return { player_id: p.player_id, name: p.web_name, cx, cy, r, isMine, xVal, yVal, sizeVal }
    })
  }, [players, xKey, yKey, sizeKey, highlightMine, squadIds])

  // Direct labels on the top 5 by size metric.
  const topIds = useMemo(() => {
    return new Set(
      [...bubbles]
        .sort((a, b) => b.sizeVal - a.sizeVal)
        .slice(0, 5)
        .map((b) => b.player_id),
    )
  }, [bubbles])

  const domain = useMemo(() => {
    if (players.length === 0) return null
    const xs = players.map((p) => metricValue(p, xKey))
    const ys = players.map((p) => metricValue(p, yKey))
    return {
      xMin: Math.min(...xs),
      xMax: Math.max(...xs),
      yMin: Math.min(...ys),
      yMax: Math.max(...ys),
    }
  }, [players, xKey, yKey])

  const selected = bubbles.find((b) => b.player_id === selectedId) ?? null

  return (
    <div className="tab-content">
      <div className="chart-controls">
        <label>
          X axis
          <select value={xKey} onChange={(e) => setXKey(e.target.value as MetricKey)}>
            {METRICS.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Y axis
          <select value={yKey} onChange={(e) => setYKey(e.target.value as MetricKey)}>
            {METRICS.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Bubble size
          <select value={sizeKey} onChange={(e) => setSizeKey(e.target.value as MetricKey)}>
            {METRICS.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Position
          <select value={position} onChange={(e) => setPosition(e.target.value as PositionFilter)}>
            {POSITIONS.map((p) => (
              <option key={p} value={p}>
                {p === 'all' ? 'All' : p}
              </option>
            ))}
          </select>
        </label>
        <label className="slider-label">
          Min minutes: {minMinutes}
          <input
            type="range"
            min={0}
            max={3420}
            step={10}
            value={minMinutes}
            onChange={(e) => setMinMinutes(Number(e.target.value))}
          />
        </label>
        <label className="toggle-label">
          <input
            type="checkbox"
            checked={highlightMine}
            onChange={(e) => setHighlightMine(e.target.checked)}
          />
          Highlight my squad
        </label>
      </div>

      {state.status === 'loading' && <p>loading players…</p>}
      {state.status === 'error' && <p>couldn't load player data.</p>}
      {state.status === 'empty' && (
        <p className="empty-state">charts unlock once the season has data.</p>
      )}
      {state.status === 'data' && bubbles.length === 0 && (
        <p className="empty-state">no players match these filters — lower the minutes threshold.</p>
      )}

      {state.status === 'data' && bubbles.length > 0 && domain && (
        <>
          <svg
            className="bubble-chart"
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label={`${labelFor(xKey)} vs ${labelFor(yKey)}, bubble size ${labelFor(sizeKey)}`}
          >
            {/* axes */}
            <line
              className="chart-axis"
              x1={M.left}
              y1={M.top + PLOT_H}
              x2={M.left + PLOT_W}
              y2={M.top + PLOT_H}
            />
            <line
              className="chart-axis"
              x1={M.left}
              y1={M.top}
              x2={M.left}
              y2={M.top + PLOT_H}
            />

            {/* axis tick labels (min/max, 1 decimal) */}
            <text className="chart-tick" x={M.left} y={H - 26} textAnchor="start">
              {domain.xMin.toFixed(1)}
            </text>
            <text className="chart-tick" x={M.left + PLOT_W} y={H - 26} textAnchor="end">
              {domain.xMax.toFixed(1)}
            </text>
            <text
              className="chart-tick"
              x={M.left - 6}
              y={M.top + PLOT_H}
              textAnchor="end"
              dominantBaseline="middle"
            >
              {domain.yMin.toFixed(1)}
            </text>
            <text
              className="chart-tick"
              x={M.left - 6}
              y={M.top + 4}
              textAnchor="end"
              dominantBaseline="middle"
            >
              {domain.yMax.toFixed(1)}
            </text>

            {/* axis titles */}
            <text className="chart-axis-title" x={M.left + PLOT_W / 2} y={H - 8} textAnchor="middle">
              {labelFor(xKey)}
            </text>
            <text
              className="chart-axis-title"
              transform={`translate(12 ${M.top + PLOT_H / 2}) rotate(-90)`}
              textAnchor="middle"
            >
              {labelFor(yKey)}
            </text>

            {/* bubbles */}
            {bubbles.map((b) => (
              <circle
                key={b.player_id}
                cx={b.cx}
                cy={b.cy}
                r={b.r}
                fill={b.isMine ? MY_COLOR : REST_COLOR}
                fillOpacity={0.72}
                className="bubble"
                onClick={() => setSelectedId(selectedId === b.player_id ? null : b.player_id)}
                onMouseEnter={() => setSelectedId(b.player_id)}
              />
            ))}

            {/* direct labels on the top 5 by size; anchor flips near the
                edges so a right-most name (e.g. Haaland) isn't clipped */}
            {bubbles
              .filter((b) => topIds.has(b.player_id))
              .map((b) => {
                const anchor = b.cx > W - 44 ? 'end' : b.cx < 44 ? 'start' : 'middle'
                return (
                  <text
                    key={`lbl-${b.player_id}`}
                    className="bubble-label"
                    x={b.cx}
                    y={b.cy - b.r - 2}
                    textAnchor={anchor}
                  >
                    {b.name}
                  </text>
                )
              })}

            {/* tooltip for the selected bubble */}
            {selected && (
              <g className="chart-tooltip" pointerEvents="none">
                <rect
                  x={Math.min(selected.cx + 6, W - 132)}
                  y={Math.max(selected.cy - 46, 2)}
                  width={126}
                  height={44}
                  rx={4}
                />
                <text
                  x={Math.min(selected.cx + 6, W - 132) + 6}
                  y={Math.max(selected.cy - 46, 2) + 14}
                  className="tooltip-name"
                >
                  {selected.name}
                </text>
                <text
                  x={Math.min(selected.cx + 6, W - 132) + 6}
                  y={Math.max(selected.cy - 46, 2) + 27}
                  className="tooltip-val"
                >
                  {labelFor(xKey)} {selected.xVal.toFixed(1)} · {labelFor(yKey)}{' '}
                  {selected.yVal.toFixed(1)}
                </text>
                <text
                  x={Math.min(selected.cx + 6, W - 132) + 6}
                  y={Math.max(selected.cy - 46, 2) + 39}
                  className="tooltip-val"
                >
                  {labelFor(sizeKey)} {selected.sizeVal.toFixed(1)}
                </text>
              </g>
            )}
          </svg>

          <div className="chart-legend">
            <span>
              <span className="legend-dot" style={{ background: MY_COLOR }} /> my squad
            </span>
            <span>
              <span className="legend-dot" style={{ background: REST_COLOR }} /> rest
            </span>
            <span className="note">bubble area ∝ {labelFor(sizeKey)}</span>
          </div>
        </>
      )}
    </div>
  )
}
