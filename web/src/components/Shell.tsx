import { useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { FreshnessBadge } from './FreshnessBadge'
import { OfflineBanner } from './OfflineBanner'
import { RefreshButton } from './RefreshButton'
import { Brief } from '../brief/Brief'

export function Shell() {
  // Bumped after a manual refresh so the brief and the badge re-query.
  const [version, setVersion] = useState(0)

  return (
    <div className="shell">
      <header className="shell-header">
        <span className="app-name">FPL Sniper</span>
        <FreshnessBadge version={version} />
        {/* The refresh endpoint lives in the dev server; a production build has none. */}
        {import.meta.env.DEV && <RefreshButton onRefreshed={() => setVersion((v) => v + 1)} />}
        <button type="button" className="sign-out" onClick={() => supabase.auth.signOut()}>
          Sign out
        </button>
      </header>

      <OfflineBanner />

      <main className="shell-main">
        <Brief version={version} />
      </main>
    </div>
  )
}
