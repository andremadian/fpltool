export type FreeTransfers = 1 | 2 | 3 | 4 | 5
export type Hits = 0 | 4 | 8

export interface BriefPrefs {
  ft: FreeTransfers
  hits: Hits
}

const KEY = 'fplsniper.brief.prefs'
const DEFAULT_PREFS: BriefPrefs = { ft: 1, hits: 0 }
const FT_VALUES: readonly number[] = [1, 2, 3, 4, 5]
const HIT_VALUES: readonly number[] = [0, 4, 8]

/** The saved FT/hits selection, or the default when storage is empty, invalid or blocked. */
export function loadPrefs(): BriefPrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return DEFAULT_PREFS
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return DEFAULT_PREFS
    const { ft, hits } = parsed as Record<string, unknown>
    if (typeof ft !== 'number' || !FT_VALUES.includes(ft)) return DEFAULT_PREFS
    if (typeof hits !== 'number' || !HIT_VALUES.includes(hits)) return DEFAULT_PREFS
    return { ft: ft as FreeTransfers, hits: hits as Hits }
  } catch {
    return DEFAULT_PREFS
  }
}

/** Remember the FT/hits selection; silently does nothing when storage is blocked. */
export function savePrefs(prefs: BriefPrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs))
  } catch {
    // Private window or blocked storage: the selection just won't survive a reload.
  }
}
