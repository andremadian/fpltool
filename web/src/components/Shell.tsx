import { supabase } from '../lib/supabaseClient'
import { FreshnessBadge } from './FreshnessBadge'
import { OfflineBanner } from './OfflineBanner'
import { Brief } from '../brief/Brief'

export function Shell() {
  return (
    <div className="shell">
      <header className="shell-header">
        <span className="app-name">FPL Sniper</span>
        <FreshnessBadge />
        <button type="button" className="sign-out" onClick={() => supabase.auth.signOut()}>
          Sign out
        </button>
      </header>

      <OfflineBanner />

      <main className="shell-main">
        <Brief />
      </main>
    </div>
  )
}
