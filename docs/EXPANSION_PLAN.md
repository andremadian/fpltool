# FPL Sniper — Market Review & Expansion Plan

> Produced by a CEO-mode plan review (July 7, 2026), then revised after an independent adversarial review (15 findings, all addressed). Companion to [PHASES.md](PHASES.md) and [PHASE3_HANDOFF.md](PHASE3_HANDOFF.md). This doc answers two questions: **is the current 5-phase plan market-competitive?** and **what should the roadmap be if the ambition grows beyond a personal tool?**

---

## Verdict up front

The current plan is a **well-executed personal data tool, not a market-competitive product — and it was never designed to be one** (the docs say "by one person, for one person"). That's not a flaw; it's a scope decision that is now worth revisiting deliberately.

The uncomfortable market fact: **conversational AI — the centerpiece of Phase 3 — stopped being a differentiator in 2026.** Team-aware FPL chat assistants already exist (ChatFPL by Fantasy Football Fix, ChatFPL.ai, FPLai, FPL Pulse's "Gaffer's Pulse"), and the official FPL app is expected to ship an AI "assistant manager" through the Premier League's Microsoft partnership. Anyone can ask "who should I captain?" and get a team-aware answer, likely for free, inside the official app.

What FPL Sniper can do that the market underserves:

1. **Mini-league rival intelligence.** `rival_team_snapshots` + `league_rivals` reflect a focus almost no incumbent has: every major tool optimizes for global rank, and almost nobody answers *"what transfer maximizes my chance of overtaking Budi in Cimanuk-ers over the next 5 GWs?"* To be precise about the moat: the data itself is public FPL API output anyone could fetch — the defensibility is the **accumulated multi-season time series of your league's behavior plus the push-habit relationship**, neither of which a copycat gets on day one.
2. **A proactive push agent.** Every tool on the market is pull (you open the app and ask). A weekly autonomous analyst that watches deadlines, price moves, injuries, and rival transfers, then *pushes* a decision-ready brief — that's a different UX category, and it's exactly what the existing cron-pipeline architecture is shaped for.
3. **Personal memory.** `user_profile` (risk tolerance, chip history, decision style) accumulated over seasons is something the official assistant is unlikely to do deeply.

**Recommended strategy: don't fight FPL Review on projections or the official app on chat. Build the best league-warfare + proactive-brief tool that exists, for yourself first, with architecture that lets your own mini-league become the first user base.**

---

## Current status (audited July 7, 2026)

| Item | State |
|---|---|
| Phase 1 + 2 pipelines | ✅ Shipped, ran cleanly through GW38 (June 5). Season 2025/26 fully captured: 19,375 history rows, 380 fixtures, squad + 5 rivals through GW38. |
| Migration 0005 (season rollover) | ✅ Applied and seeded in live DB — verified: `season` column live, `players_season_archive` (841 rows) + `teams_season_archive` (20 rows) populated. |
| **Local runtime** | ⚠️ **Was broken, now repaired.** The July 2026 system-Python wipe deleted `.venv/`; every cron fire since then would have failed (exit 127). Rebuilt July 7 with supabase 2.30.0. Harmless this time only because the season had already ended. |
| **Cron reliability** | ⚠️ No log entries after June 5 — four consecutive scheduled runs left no trace (Mac asleep and/or dead venv). **Nothing alerted.** This is the "zero silent failures" violation to fix before the 2026/27 season starts (~mid-August). |
| Phase 3 | 📝 Handoff doc written (July 5), brief not yet produced. Six scoping questions open — recommended answers below. |
| Phases 4–5 | ⬜ Unbriefed — the plan currently has **no defined path** past the conversational layer. |

**Timeline pressure:** the 2026/27 season starts ~mid-August. Reliability fixes and ingestion upgrades must land *before* GW1 — roughly a 5-week window. That deadline, not the chat agent, drives the sequencing below.

---

## Market landscape (July 2026)

Three-layer synthesis:

**Layer 1 — tried and true.** The paid incumbents own "serious manager" mindshare: FPL Review (ML expected-points model + transfer solver + chip analyser, from ~£3.50/mo via Patreon), Fantasy Football Fix (solver, "89% of members won their mini-league" per their own marketing, ChatFPL), Fantasy Football Hub (Opta-backed content + tools; Trustpilot shows app-reliability complaints), Fantasy Football Scout (content + Opta licensing, set-piece/DEFCON tables). Free tier: LiveFPL (live ranks, EO, price predictor), fpl.page dashboards, Understat for xG. FBref reportedly lost its advanced-data feed in Feb 2026, pushing stats users toward Scout/Understat.

**Layer 2 — new and popular.** "FPL AI" search volume roughly tripled since 2024 (per FPL Pulse). The wave: ChatFPL.ai, FPLai (transfer recs, captain picks, squad health), FPL Pulse's Gaffer's Pulse (team-aware quick prompts), plus open-source agents on GitHub. The Premier League × Microsoft partnership is expected to put an AI assistant *inside the official app*. Team-aware chat is becoming table stakes.

**Layer 3 — first principles.** If every tool converges on "ask AI about your team," the remaining edges are (a) **context nobody else holds** — your league's rival history, your decision profile, multi-season memory; (b) **initiative** — tools that act before you ask; (c) **trust** — grounded answers with visible data lineage (the agent shows the query and the freshness of the data, vs. hallucinating a projection). The current plan is accidentally well-positioned for all three; none of the funded incumbents are structurally push-first.

**Eureka worth naming:** the conventional wisdom is "build a better projection model." First-principles says the projection layer is a commodity you can rent or approximate — the *moat is the accumulated rival time series and the push relationship.* A league-mate can copy your captain pick; they can't copy a season of your league's behavioral data.

> **Sources & verification note:** competitor claims above are from public marketing pages and search results dated July 2026 (fplreview.com, fantasyfootballfix.com, fantasyfootballhub.co.uk + Trustpilot, livefpl.net, chatfpl.ai, fplai.app, fplpulse.com, fantasyfootballscout.co.uk). Several are load-bearing and unverified (official-app AI ship date and its feature depth, FBref feed loss, "89%" claim). **Re-verify the official app's AI scope before committing to the Phase 6 league-product gate** — if the official assistant ships league-context features, the wedge analysis changes.

---

## Gap analysis — FPL Sniper vs. the market

| Capability | FPL Review | Fix / Hub | LiveFPL | Official app + AI | **FPL Sniper today** | Gap severity |
|---|---|---|---|---|---|---|
| xP projection model (ML) | ✅ best-in-class | ✅ | — | partial | ❌ heuristic SQL only | High (rent/approximate, don't rebuild) |
| Transfer solver / optimizer | ✅ | ✅ | — | ❌ | ❌ | Medium (classic LP, buildable) |
| Price-change prediction | via tools | ✅ | ✅ free | ❌ | ❌ (weekly cadence can't) | Medium |
| Injury / availability flags | ✅ | ✅ | ✅ | ✅ | ❌ **but fields already in bootstrap payload — just not stored** | High, trivially cheap |
| Live rank / EO / bonus | — | ✅ | ✅ | ✅ | ❌ | Low (commodity, skip) |
| Team-aware AI chat | — | ✅ ChatFPL | — | ✅ expected | ❌ planned | High (table stakes) |
| **Mini-league rival intel** | — | shallow | shallow | ❌ | ✅ rare focus (moat = accumulation + habit, see Verdict) | — (the wedge) |
| **Proactive push brief** | ❌ | ❌ | ❌ | ❌ | ❌ planned | — (the differentiator) |
| Underlying stats (shots, big chances) | ✅ | ✅ Opta | — | — | ❌ | Low-medium (Understat) |
| Product surface (web/mobile) | ✅ | ✅ | ✅ | ✅ | ❌ Supabase Studio | High if productizing |
| Reliability / hosting | ✅ | ✅ | ✅ | ✅ | ⚠️ local Mac cron, silent-failure incident June–July 2026 | High |
| Multi-user + auth | ✅ | ✅ | ✅ | ✅ | scaffolded, unused | Only matters for league product |

---

## Strategic goal — the decision that gates everything

Three coherent end-states. Everything downstream (hosting, auth, evals, polish bar) depends on which one is ratified.

**A) Best-in-class personal edge tool** — *recommended baseline.* Ship the phases below for one user. Local-first stays viable (with reliability fixes). Zero distribution work. Success metric: "my Friday decision takes 10 minutes and I stopped missing price/injury signals."

**B) League-scale product** — the natural expansion. Same product, but league members get accounts. The rival-ingestion pipeline already collects their data; inviting them converts rivals into users (a built-in distribution loop — every FPL player is in a league with 5–20 others). Needs: hosted ingestion, Supabase Auth on, a web surface. Success metric: **the majority of your active league(s) using it weekly by mid-season** — note the current tracked league has 6 members total, so scale beyond that requires tracking more leagues or members recruiting their *other* leagues.

**C) Commercial product** — head-to-head with funded incumbents and the official AI. Needs a projection model or partnership, paid infra, content/SEO distribution, support. **This is an ocean, not a lake** — flag it, don't boil it. Only revisit if B shows organic retention.

**Recommendation: commit to A now, architect for B (every A deliverable below is B-compatible), defer C.** The plan below assumes A→B.

---

## The roadmap

Phase numbering: "Phase 3" stays the conversational era (matching [PHASE3_HANDOFF.md](PHASE3_HANDOFF.md)) but is split into **3A (pre-season hardening — has the hard deadline, do first)** and **3B (the agent)**. Migration numbers are assigned uniquely: **0006** bootstrap fields, **0007** `player_daily` + `pipeline_runs`, **0008** auth-user seed (the chat tables themselves already exist from migration 0001).

### Phase 3A — Pre-season hardening (before GW1, ~mid-August; 1–2 sessions)

The hard-deadline work. Each item is afternoon-sized; 1–2 sessions total:

1. **Store the bootstrap fields you already download** — `status`, `news`, `chance_of_playing_next_round`, `transfers_in_event`, `transfers_out_event`, `cost_change_event` → `players_master` (**migration 0006**, ~20 LOC in `write_snapshot`). Kills the "no injury data" gap for free and gives the agent availability context.
2. **Split cadence: daily light run + weekly full run.** A bootstrap-only run is one HTTP call (~5s) — run it daily to capture price changes, ownership momentum, and news as a time series (new table `player_daily`, keyed `(season, player_id, date)`, ~840 rows/day ≈ ~300k/season — trivial for Postgres). Keep the full element-summary crawl weekly. This unlocks price-trend signals the Friday-only cadence structurally cannot see. Add a **`pipeline_runs`** table (engine, season, gw, rows_written, duration, status) in the same **migration 0007** — it's what the agent's freshness check will read.
3. **Migrate cron → launchd LaunchAgents** — *sleep mitigation, not a cure-all*: launchd runs a missed `StartCalendarInterval` job on wake from sleep (cron doesn't), but not after a shutdown, and it would **not** have caught the actual June–July failure (a dead venv exits fast with a nonzero code). Detection belongs to item 4.
4. **Dead-man alerting:** end every engine run with a ping to a free healthchecks.io check; it emails when a ping *doesn't* arrive — this is the fix that would have caught both the sleeping Mac and the wiped venv. Add a startup **schema-version assert** (engine checks expected tables/columns exist; exits loudly with "run migration X" if not) so the venv-wipe / unapplied-migration class of failure is self-diagnosing. Document a one-page **season-start runbook** in the README: venv exists → schema assert passes → healthchecks green → GW1 dry-run.

### Phase 3B — Conversational agent MVP (~3–4 sessions, honestly estimated)

The [PHASE3_HANDOFF.md](PHASE3_HANDOFF.md) scoping questions, answered:

- **Interface: Telegram bot, built CLI-first.** Session 1 builds the agent core with a CLI loop (pure dev surface, no hosting question); session 2 wraps it in Telegram; sessions 3–4 harden (guards, evals, persistence). Telegram because it's on your phone where Friday decisions actually happen, it's push-capable (Phase 4 reuses the same surface), and it's free.
- **The always-on problem, named honestly:** a chat bot is a persistent listener, and the Mac sleeps — the June–July incident proves it'll be asleep exactly when you're out on a Friday. Recommended posture: run the listener via **launchd `KeepAlive`** and accept that chat only answers when the Mac is awake (fine for a desk-adjacent personal tool); the Phase 4 *brief* is push-on-schedule and tolerates wake-delays. If away-from-desk chat turns out to matter, the listener is the first component to move to an always-on free-tier box (Oracle Cloud free tier or a Raspberry Pi) — an explicit, contained exception to local-first. Decision deferred until the annoyance is real.
- **Sync-only rule preserved:** do **not** adopt `python-telegram-bot` v20+ (asyncio-native, violates the project's sync mandate). Use a plain **`requests` long-poll loop against the Bot API `getUpdates`** — same HTTP idiom as the engines, zero new frameworks. Allowlist your own chat ID; ignore all other senders.
- **LLM: Claude API (`claude-sonnet-5`), tool-use pattern** (not RAG). Tools: `run_saved_query(name, params)` over the 8 curated queries, `run_sql(select_stmt)` behind a guard (see security), `get_my_squad(gw)`, `get_data_freshness()` (reads `pipeline_runs` max timestamps per engine + latest `(season, gw)` in the data tables).
- **Cost, stated up front (first recurring cost in the project):** ad-hoc chat + weekly evals ≈ low single-digit USD/month on Sonnet at personal usage; the Phase 4 brief adds roughly ~50–100k tokens/week ≈ another few USD/month. Budget ~$5–15/month total; revisit if usage grows.
- **Auth: skip Supabase Auth flows.** Seed one `auth.users` row (**migration 0008**) so the scaffolded `conversations`/`messages` FKs work unchanged; hardcode that user ID. Keeps the league-product path open without schema surgery.
- **Conversation memory:** persist everything to `messages`, feed the model the last ~20 messages per conversation, start a new conversation per GW by default. `user_profile` updates are deferred to Phase 4+ (the brief is a better trigger for profile learning than chat).
- **Grounding rule (non-negotiable): every answer states its data vintage.** First tool call is `get_data_freshness()`; if the latest snapshot is stale (missed run) or it's off-season, the agent says so instead of answering as if data were current. Zero-silent-failures applied to the LLM layer — and a trust differentiator no incumbent chat tool has.
- **Eval harness ships with the agent, not after.** `evals/golden_questions.yaml`, 10 questions at MVP (~20 by season's end) with expected grounded properties ("names a player from my actual squad", "cites the projection score", "declines to invent injury news"). Run per prompt/tool change.

### Phase 4 — The Sniper Brief (the differentiator, ~1–2 sessions)

The product identity. Every Friday (and post-deadline Saturday), a scheduled agent run — same Claude tool-use core as 3B, so it's cron-shaped and needs no listener — composes and pushes a decision-ready brief to Telegram:

- Projected XI + captain ranking for my actual squad (heuristic projections + availability flags from migration 0006 fields)
- Transfer candidates with *league context*: "Riyad is owned by 4/5 rivals — benching him is a 4-rival swing risk"
- Rival watch: captain consensus, transfers in/out since last GW, chip usage
- Price/news alerts on my players and my watchlist (from `player_daily`)
- Data-freshness footer (which runs succeeded, data vintage)

Off-season: monthly quiet-mode digest (pre-season prices, new players, fixture-release analysis). Chat (3B) becomes the follow-up surface: the brief arrives, you interrogate it.

### Phase 5 — League surface (decision gate: only if path B is ratified)

Named preconditions, because two of them are genuinely hard:

1. **RLS data-model redesign, not just a toggle.** `rival_team_snapshots` PK is global `(season, rival_fpl_team_id, gw)`; the same human is "rival" in your league and "user" of their own account. Row visibility needs a real design (likely: snapshots stay global/shared — they're public API data — while `tracked_leagues`, `user_team_snapshots`, conversations, and profiles become user-scoped with RLS). Budget a dedicated migration + test pass.
2. **`run_sql` must be removed or hard-scoped before a second user exists** — a free-SQL tool over shared tables is a data-leak generator. Replace with parameterized saved queries only.
3. **FPL API load assessment.** N users × leagues × rivals from a single GitHub Actions IP against an unofficial, ToS-less API is a rate-limit/blocking risk the personal tool never had. Mitigations: dedupe rivals across users (already the pattern), cache bootstrap per run, cap per-user league count, jittered pacing (already the pattern), and a kill switch. Estimate calls at the gate: ~(1 bootstrap + N_users + Σ unique rivals) per capture window.

Then: Next.js dashboard on a free tier (Vercel) or Streamlit reading Supabase; Supabase Auth on; invite league members (each new user = one `tracked_leagues` row); ingestion moves to GitHub Actions scheduled workflows (free tier) — a deliberate, opt-in exception to local-first, justified because other people now depend on the runs. Season "wrapped" (best call, worst call, rank graph vs rivals) — the shareable artifact that recruits the next league.

### Phase 6 — Competitive bets (only after B shows retention; re-verify market first)

Own xP model trained on `player_history` × `fixtures`; transfer solver (linear programming over xP, budget, and *rival-differential* objectives — solving for league win probability, not global points, is the novel angle); Understat enrichment; price predictor. Each is a separate brief.

---

## Engineering review highlights (condensed registry)

**Architecture.** Current: two engines → Supabase → SQL-in-Studio. Target adds two consumers (chat agent, brief generator) sharing one agent core and one notifier abstraction (Telegram today, swappable later — avoids path-dependency; the CLI dev loop uses the same abstraction with a stdout notifier).

```
FPL API ──▶ fpl_engine.py (weekly full) ──▶ Supabase ◀── fpl_user_engine.py (Fri+Sat)
             └─ daily light run (3A)           │  (+ player_daily, pipeline_runs)
                                    ┌──────────┴──────────┐
                              agent core (Claude tool-use) │
                              ┌─────┴─────┐                │
                        3B chat listener  4 brief (sched) ─▶ notifier ──▶ Telegram / stdout
                        (launchd KeepAlive)                └── healthchecks ping
```

Single points of failure: the Mac (mitigated by launchd + dead-man alerts; eliminated for ingestion in Phase 5 by GH Actions), Supabase free tier (fine at current volume), the unofficial FPL API (existing defensive-fields pattern is right; extend it to the 0006 fields).

**Error map (agent layer — the new failure surface).** Malformed/hallucinated SQL from the LLM → execute under a **read-only Postgres role** with a SELECT-only, table-allowlisted guard; on error, return the DB message to the model for one retry, then apologize with specifics. Empty result (off-season, pre-GW1) → freshness tool makes this a stated condition, never a silent zero. Claude API timeout/429 → retry with backoff, then a "brain offline, data fine" Telegram message. Stale data → freshness footer (never answer as if current). Telegram send failure → log + healthcheck fail ping. Rival names and FPL `news` strings are **untrusted input to the prompt** — treat as data, never as instructions (prompt injection via a rival renaming their team "Ignore previous instructions…" is a real, funny, and cheap attack).

**Security.** The service-role key currently in `.env` must never be reachable from the LLM-facing path — give the agent a separate restricted connection (read-only role or PostgREST anon with RLS). Telegram: chat-ID allowlist (above). Phase 5 flips RLS from "deliberately off" to load-bearing — covered by Phase 5 precondition #1.

**Tests/evals.** Golden-question evals (3B); freshness-guard unit tests (stale, off-season, missing-table); SQL-guard tests (rejects UPDATE/DELETE/DDL, rejects non-allowlisted tables); one end-to-end brief generation against a fixture DB snapshot. The 2am-Friday-confidence test: "the brief that arrives is either correct-and-current or explicitly says what it's missing."

**Observability.** Healthchecks per engine + per brief run; run-summary lines already exist (keep); `pipeline_runs` turns "did Friday work?" into a query; persist agent tool calls to `messages.tool_calls` (schema already has it) so any bad answer is reconstructable three weeks later.

**Deployment/rollout.** Order per phase: migration → engine change → agent change; every migration remains additive (project rule). launchd migration is reversible in one `crontab -e`. Rollback for the agent is "stop the bot"; ingestion is untouched. Season-start runbook per 3A item 4.

## NOT in scope (deferred, with reasons)

- **Own projection ML model / solver** — Phase 6, only after league-product retention is proven; commodity elsewhere until then.
- **Live BPS / live rank ticking** — LiveFPL does it free; zero edge.
- **Scraped paid data (Opta) or FBref** — licensing dead-end as of Feb 2026 (reportedly); Understat only, and only at Phase 6.
- **Mobile app, billing, multi-league tenancy at scale** — path C material.
- **Async/streaming rewrite** — sync Python stays the project rule; the Telegram long-poll loop is designed around it.

## Dream-state delta

```
CURRENT (Jul 2026)              THIS PLAN (Phases 3A–5)            12-MONTH IDEAL (Jul 2027)
Season of data, dead runtime →  Self-healing ingestion,        →   Every GW: brief lands Friday,
SQL-in-Studio research tool     chat agent + push brief,           you interrogate it in chat,
(one user, pull-only)           league-ready architecture          league-mates use it too, and it
                                                                   remembers two seasons of your calls
```

## Decisions awaiting ratification

| # | Decision | Recommendation | Status |
|---|---|---|---|
| 1 | Strategic goal (A/B/C) | A now, B-compatible architecture, C deferred | ✅ **ratified — option A** (July 7, 2026) |
| 2 | Phase 3B interface | ~~Telegram bot~~ → **PWA, no AI** (4 tabs incl. chart maker) — user pivot, July 2026; see [PWA brief](../FPL_Sniper_Phase3B_PWA_Brief.md) | ✅ ratified — PWA |
| 3 | Always-on chat listener | Moot for the PWA (static hosting); revisit only if the agent is revived | ⏸ deferred with the agent |
| 4 | Auth approach | Supabase magic-link, single invited email, signups disabled, RLS allowlist (migration 0008) | ✅ ratified — in PWA brief |
| 5 | Daily light-run cadence | Yes — `player_daily` + `pipeline_runs` (migration 0007) | ✅ accepted — shipped in Phase 3A |
| 6 | launchd + healthchecks migration | Yes, before GW1 (~mid-August) — 3A is the deadline-bound phase | ✅ accepted — shipped in Phase 3A |
| 7 | LLM budget | $0 — AI deferred; was ~$5–15/month, becomes the bar the chat tab must clear to be revived | ✅ resolved by the pivot |
| 8 | GH Actions ingestion | Defer to Phase 5 (local-first holds until others depend on it) | deferred by design |

> **July 2026 amendment:** Phase 3B pivoted from the conversational agent to a **$0/month PWA** (This week / Transfers / Rivals / Chart maker, magic-link auth). Rationale: the moat is the data + rival graph, not the chat layer; the PWA is also the Phase 5 surface built early. Phase 3B (agent) sections below are superseded accordingly — the agent survives as a deferred add-on ([brief](../FPL_Sniper_Phase3B_ClaudeCode_Brief.md)). Phase 4's Sniper Brief becomes template-rendered (no LLM) in this PWA, with Web Push.
