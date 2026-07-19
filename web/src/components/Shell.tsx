import { useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { FreshnessBadge } from './FreshnessBadge'
import { OfflineBanner } from './OfflineBanner'
import { ThisWeek } from '../tabs/ThisWeek'
import { Transfers } from '../tabs/Transfers'
import { RivalsStub } from '../tabs/RivalsStub'
import { ChartsStub } from '../tabs/ChartsStub'

const TABS = [
  { id: 'this-week', label: 'This week' },
  { id: 'transfers', label: 'Transfers' },
  { id: 'rivals', label: 'Rivals' },
  { id: 'charts', label: 'Charts' },
] as const

type TabId = (typeof TABS)[number]['id']

export function Shell() {
  const [activeTab, setActiveTab] = useState<TabId>('this-week')

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
        {activeTab === 'this-week' && <ThisWeek />}
        {activeTab === 'transfers' && <Transfers />}
        {activeTab === 'rivals' && <RivalsStub />}
        {activeTab === 'charts' && <ChartsStub />}
      </main>

      <nav className="tab-bar">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={activeTab === tab.id ? 'tab-active' : ''}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
    </div>
  )
}
