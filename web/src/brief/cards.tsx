import { useId, useState, type ReactNode } from 'react'
import type { ChipAdvice, ChipCode, PlayerSlot, Position, RivalRow, Scenario } from './types'

const POSITIONS: Position[] = ['GKP', 'DEF', 'MID', 'FWD']
const CHIP_NAMES: Record<ChipCode, string> = {
  wildcard: 'Wildcard',
  freehit: 'Free Hit',
  bboost: 'Bench Boost',
  '3xc': 'Triple Captain',
}
const RIVALS_COLLAPSED = 5

/** One decimal, the way the engine rounds every number. */
function pts(value: number): string {
  return value.toFixed(1)
}

/** A gain with an explicit sign, e.g. "+11.5" or "-2.0". */
function signed(value: number): string {
  return `${value >= 0 ? '+' : ''}${pts(value)}`
}

/** Card shell: a title row that toggles the optional detail section. */
function Card({ title, children, detail }: { title: string; children: ReactNode; detail?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const detailId = useId()

  return (
    <section className="brief-card">
      <h2 className="brief-card-title">
        {detail ? (
          <button
            type="button"
            className="brief-card-head"
            aria-expanded={open}
            aria-controls={detailId}
            onClick={() => setOpen((v) => !v)}
          >
            <span>{title}</span>
            <span className="brief-card-toggle" aria-hidden="true">
              {open ? 'Less ▴' : 'More ▾'}
            </span>
          </button>
        ) : (
          <span className="brief-card-head">{title}</span>
        )}
      </h2>
      <div className="brief-card-body">{children}</div>
      {detail && open && (
        <div id={detailId} className="brief-card-detail">
          {detail}
        </div>
      )}
    </section>
  )
}

/** Small availability marker, e.g. "! 75%". */
function FlagMark({ slot }: { slot: PlayerSlot }) {
  if (!slot.flag) return null
  const chance = slot.flag.chance
  return (
    <span className="brief-flag" title={slot.flag.news || `status ${slot.flag.status}`}>
      ! {chance === null ? slot.flag.status : `${chance}%`}
    </span>
  )
}

export function TransfersCard({ scenario }: { scenario: Scenario }) {
  const { transfers, hit_note, priority_sells } = scenario

  return (
    <Card
      title="Transfers"
      detail={
        <>
          {transfers.map((t) => (
            <p key={`${t.out.id}-${t.in.id}`} className="brief-reason">
              {t.reason}
            </p>
          ))}
          <dl className="brief-facts">
            <dt>Hit cost</dt>
            <dd>{scenario.hit_cost === 0 ? 'none' : `−${scenario.hit_cost}`}</dd>
            <dt>Net gain over window</dt>
            <dd>{signed(scenario.net_gain_window)}</dd>
          </dl>
        </>
      }
    >
      {transfers.length === 0 ? (
        <p className="brief-answer">Hold. No transfer improves your team enough</p>
      ) : (
        <ul className="brief-list">
          {transfers.map((t) => (
            <li key={`${t.out.id}-${t.in.id}`} className="brief-answer">
              {t.out.name} → {t.in.name} <span className="brief-gain">{signed(t.gain_window)}</span>
            </li>
          ))}
        </ul>
      )}
      {hit_note && <p className="brief-note">{hit_note}</p>}
      {priority_sells.length > 0 && (
        <ul className="brief-list brief-sells">
          {priority_sells.map((s) => (
            <li key={s.player.id}>
              Sell {s.player.name}: {s.reason}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export function XiCard({ scenario }: { scenario: Scenario }) {
  const captainId = scenario.captain.id
  const viceId = scenario.vice.id
  const flagged = [...scenario.xi, ...scenario.bench].filter((s) => s.flag)

  const tag = (id: number) => (id === captainId ? ' (C)' : id === viceId ? ' (V)' : '')

  return (
    <Card
      title="Best XI"
      detail={
        <>
          <h3 className="brief-sub">Bench</h3>
          <ol className="brief-list">
            {scenario.bench.map((s) => (
              <li key={s.id} className="brief-player">
                <span>
                  {s.name} <FlagMark slot={s} />
                </span>
                <span className="brief-num">{pts(s.proj)}</span>
              </li>
            ))}
          </ol>
          {flagged.length > 0 && (
            <>
              <h3 className="brief-sub">Flagged</h3>
              <ul className="brief-list">
                {flagged.map((s) => (
                  <li key={s.id} className="brief-note">
                    {s.name}: {s.flag?.news || `status ${s.flag?.status}`}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      }
    >
      <p className="brief-answer">{scenario.formation}</p>
      {POSITIONS.map((pos) => {
        const slots = scenario.xi.filter((s) => s.pos === pos)
        if (slots.length === 0) return null
        return (
          <div key={pos} className="brief-pos-group">
            <span className="brief-pos">{pos}</span>
            <ul className="brief-list">
              {slots.map((s) => (
                <li key={s.id} className="brief-player">
                  <span>
                    {s.name}
                    <strong>{tag(s.id)}</strong> <FlagMark slot={s} />
                  </span>
                  <span className="brief-num">{pts(s.proj)}</span>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </Card>
  )
}

export function CaptainCard({ scenario }: { scenario: Scenario }) {
  const { captain, vice } = scenario
  const options = [...scenario.captain_options].sort((a, b) => b.basis - a.basis)

  return (
    <Card
      title="Captain"
      detail={
        <>
          <h3 className="brief-sub">Captain score (expected output)</h3>
          <ol className="brief-list">
            {options.map((s) => (
              <li key={s.id} className="brief-player">
                <span>
                  {s.name} <FlagMark slot={s} />
                </span>
                <span className="brief-num">{pts(s.basis)}</span>
              </li>
            ))}
          </ol>
        </>
      }
    >
      <div className="brief-player brief-answer">
        <span>
          <strong>(C)</strong> {captain.name} <FlagMark slot={captain} />
        </span>
        <span className="brief-num">{pts(captain.proj)}</span>
      </div>
      <div className="brief-player">
        <span>
          <strong>(V)</strong> {vice.name} <FlagMark slot={vice} />
        </span>
        <span className="brief-num">{pts(vice.proj)}</span>
      </div>
      <p className="brief-reason">{captain.reason}</p>
    </Card>
  )
}

/** One league-table row. */
function RivalItem({ rival }: { rival: RivalRow }) {
  return (
    <li className={`brief-rival${rival.is_target ? ' brief-target' : ''}`}>
      <span className="brief-rank">{rival.rank}</span>
      <span className="brief-rival-name">
        {rival.player_name}
        {rival.captain && <small className="brief-captain"> (C) {rival.captain}</small>}
      </span>
      <span className="brief-num">
        {rival.projected_points === null ? 'no squad yet' : pts(rival.projected_points)}
      </span>
    </li>
  )
}

export function RivalsCard({ scenario, rivals }: { scenario: Scenario; rivals: RivalRow[] }) {
  const shown = rivals.slice(0, RIVALS_COLLAPSED)
  const rest = rivals.slice(RIVALS_COLLAPSED)

  return (
    <Card
      title="You vs rivals"
      detail={
        rest.length > 0 ? (
          <ul className="brief-list">
            {rest.map((r) => (
              <RivalItem key={r.entry_id} rival={r} />
            ))}
          </ul>
        ) : undefined
      }
    >
      <div className="brief-player brief-answer">
        <span>You</span>
        <span className="brief-num">{pts(scenario.projected_points)}</span>
      </div>
      {rivals.length === 0 ? (
        <p className="brief-note">No rivals tracked.</p>
      ) : (
        <ul className="brief-list">
          {shown.map((r) => (
            <RivalItem key={r.entry_id} rival={r} />
          ))}
        </ul>
      )}
    </Card>
  )
}

/** One chip row with its verdict. */
function ChipItem({ chip }: { chip: ChipAdvice }) {
  return (
    <li className={`brief-chip${chip.play_now ? ' brief-chip-play' : ''}`}>
      <span className="brief-answer">
        {CHIP_NAMES[chip.chip] ?? chip.chip}
        {chip.play_now && <span className="brief-play-tag">Play now</span>}
      </span>
      <p className="brief-reason">{chip.reason}</p>
    </li>
  )
}

export function ChipsCard({ scenario }: { scenario: Scenario }) {
  return (
    <Card title="Chips">
      {scenario.chips.length === 0 ? (
        <p className="brief-answer">No chips left this half.</p>
      ) : (
        <ul className="brief-list">
          {scenario.chips.map((c) => (
            <ChipItem key={c.chip} chip={c} />
          ))}
        </ul>
      )}
    </Card>
  )
}
