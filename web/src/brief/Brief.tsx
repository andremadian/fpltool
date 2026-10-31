import { useState } from 'react'
import { useBrief } from './useBrief'
import { loadPrefs, savePrefs, type BriefPrefs, type FreeTransfers, type Hits } from './prefs'
import { CaptainCard, ChipsCard, RivalsCard, TransfersCard, XiCard } from './cards'
import type { Mode } from './types'

const FT_OPTIONS: FreeTransfers[] = [1, 2, 3, 4, 5]
const HIT_OPTIONS: { value: Hits; label: string }[] = [
  { value: 0, label: 'None' },
  { value: 4, label: '−4' },
  { value: 8, label: '−8' },
]
const FALLBACK_SCENARIO = '1_0'
/** A brief older than this reads as stale, as does one whose deadline has passed. */
const STALE_AFTER_MS = 36 * 60 * 60 * 1000

/** "Saturday 1 Nov, 18:30" in the viewer's locale and time zone. */
function formatDeadline(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "31 Oct, 09:30" in the viewer's locale and time zone. */
function formatGenerated(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** True when the brief is over 36h old or its target GW's deadline has passed. */
function isStale(generatedAt: string, deadline: string | undefined, now: number): boolean {
  if (now - new Date(generatedAt).getTime() > STALE_AFTER_MS) return true
  return deadline !== undefined && now > new Date(deadline).getTime()
}

/** 1 → "1st", 2 → "2nd", 11 → "11th", 23 → "23rd". */
function ordinal(n: number): string {
  const teen = n % 100 >= 11 && n % 100 <= 13
  const suffix = teen ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'
  return `${n}${suffix}`
}

/** "DEFEND · 1st · 20 ahead of X" or "CHASE · 3rd · 12 behind Y". */
function modeLabel(mode: Mode): string {
  const rank = ordinal(mode.my_rank)
  if (mode.kind === 'defend') {
    const head = `DEFEND · ${rank}`
    return mode.target ? `${head} · ${Math.abs(mode.gap)} ahead of ${mode.target.player_name}` : head
  }
  const head = `CHASE · ${rank}`
  return mode.target ? `${head} · ${mode.gap} behind ${mode.target.player_name}` : head
}

export function Brief() {
  const state = useBrief()
  const [prefs, setPrefs] = useState<BriefPrefs>(loadPrefs)
  const [now] = useState(() => Date.now())

  const update = (next: BriefPrefs) => {
    setPrefs(next)
    savePrefs(next)
  }

  if (state.status === 'loading') return <p className="brief-status">loading brief…</p>
  if (state.status === 'error') return <p className="brief-status">Couldn't load the brief.</p>
  if (state.status === 'empty' || !state.brief) {
    return <p className="brief-status">No brief yet: the engine hasn't run since the update.</p>
  }

  const brief = state.brief
  const generatedAt = state.generatedAt ?? brief.generated_at
  // Briefs written before `deadline` existed lack it; render without the subline.
  const deadline: string | undefined = brief.deadline
  const stale = isStale(generatedAt, deadline, now)
  const scenario =
    brief.scenarios[`${prefs.ft}_${prefs.hits}`] ?? brief.scenarios[FALLBACK_SCENARIO]
  if (!scenario) return <p className="brief-status">This brief has no scenarios to show.</p>

  return (
    <div className="brief">
      <header className="brief-header">
        <h1 className="brief-title">Gameweek {brief.gw}</h1>
        {deadline && <p className="brief-deadline">Deadline {formatDeadline(deadline)}</p>}
        <p className={`brief-generated${stale ? ' brief-stale' : ''}`}>
          Generated {formatGenerated(generatedAt)}
          {stale && ' (stale)'}
        </p>
      </header>
      <div className="brief-controls">
        <div className="brief-control">
          <span className="brief-control-label" id="ft-label">
            Free transfers
          </span>
          <div className="segmented" role="group" aria-labelledby="ft-label">
            {FT_OPTIONS.map((ft) => (
              <button
                key={ft}
                type="button"
                aria-pressed={prefs.ft === ft}
                className={prefs.ft === ft ? 'seg-active' : ''}
                onClick={() => update({ ...prefs, ft })}
              >
                {ft}
              </button>
            ))}
          </div>
        </div>
        <div className="brief-control">
          <span className="brief-control-label" id="hits-label">
            Hits
          </span>
          <div className="segmented" role="group" aria-labelledby="hits-label">
            {HIT_OPTIONS.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                aria-pressed={prefs.hits === value}
                className={prefs.hits === value ? 'seg-active' : ''}
                onClick={() => update({ ...prefs, hits: value })}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <span className={`brief-mode brief-mode-${brief.mode.kind}`}>{modeLabel(brief.mode)}</span>
        <p className="brief-assumption">{brief.assumption}</p>
      </div>

      <TransfersCard scenario={scenario} />
      <XiCard scenario={scenario} />
      <CaptainCard scenario={scenario} />
      <RivalsCard scenario={scenario} rivals={brief.rivals} />
      <ChipsCard scenario={scenario} />
    </div>
  )
}
