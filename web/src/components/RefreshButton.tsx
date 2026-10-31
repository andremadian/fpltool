import { useState } from 'react'
import { useToast } from './ToastContext'

interface RefreshResponse {
  ok: boolean
  error?: string
}

/**
 * Runs the daily ingest + brief engines on this Mac via the dev server's
 * /api/refresh endpoint (web/refreshPlugin.ts), then tells the page to re-read.
 */
export function RefreshButton({ onRefreshed }: { onRefreshed: () => void }) {
  const [running, setRunning] = useState(false)
  const { showError } = useToast()

  async function refresh() {
    setRunning(true)
    try {
      const res = await fetch('/api/refresh', { method: 'POST' })
      const body = (await res.json()) as RefreshResponse
      if (!body.ok) showError(body.error ?? `Refresh failed (${res.status})`)
      // Re-read even after a failure: the ingest step may have landed before the brief failed.
      onRefreshed()
    } catch {
      showError('Refresh failed: the local server did not answer.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <button
        type="button"
        className="refresh-button"
        onClick={refresh}
        disabled={running}
        title="Fetch the latest FPL data and rebuild the brief"
      >
        <span className={`refresh-icon${running ? ' refresh-spinning' : ''}`} aria-hidden="true">
          ↻
        </span>
        {running ? 'Refreshing…' : 'Refresh'}
      </button>
      <p className="refresh-hint">
        {running
          ? 'Fetching the latest FPL data and rebuilding the brief — about 35 seconds.'
          : 'Refresh pulls the latest prices, injury news and rival teams from FPL, then rebuilds this brief (about 35s). Last gameweek’s match stats arrive with the Tuesday run.'}
      </p>
    </>
  )
}
