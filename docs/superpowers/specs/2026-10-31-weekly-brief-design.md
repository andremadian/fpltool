# Weekly Brief — design

*2026-10-31. Replaces the five-tab PWA with a single screen of weekly recommendations.*

## Intent

Every gameweek I want answers to five questions, not tables to read:

1. Who should I transfer in and out?
2. What is my best XI (and bench order)?
3. Who should be captain and vice-captain?
4. How does my projected score compare with my league rivals this GW?
5. Should I play a chip?

Today I get these answers by asking Claude Code directly. The answers have been good because they come from a projection model built during those chats. That model has never been committed, though: it lived in a scratchpad and has been lost and rebuilt three times (GW6, GW8, GW9). The current PWA uses older SQL projections. It ranks players in tables but never makes a decision, so it goes unused.

**The goal:** the app shows those five answers automatically, with no Claude Code session needed. The model moves into the repo as a scheduled engine.

## Goals

- **One screen, one scroll.** Five stacked cards, in this order: Transfers → Best XI → Captain → You vs rivals → Chips. Each card shows the answer, the key numbers and a one-line reason. Tapping a card expands the detail.
- **Controls at the top:**
  - **Free transfers:** 1–5. I set it; the app never infers it.
  - **Hits allowed:** none / up to -4 / up to -8.
  - **Mode badge:** Defend or Chase, plus league position and the gap to the target rival. Set automatically.
- **Transfers are judged over a 5-gameweek window:** the target GW plus the next 4, *including* the current one. A hit is only worth taking if it gains more than its cost over that window.
- **Even with "none" selected**, the Transfers card says when a hit would be worth it, e.g. "a -4 for X→Y gains +6.1 over 5 GWs, net +2.1". It is never applied silently.
- **Injury news is built in.** A player's status flag (`i/s/u/n/d`) and chance of playing cut his expected minutes. A flagged player is never recommended as a buy and is a natural sell or bench candidate.
- **Injury rules across the window (decided by me):**
  - **Target GW:** `chance_of_playing_next_round` scales expected minutes (75% → ×0.75, 0% → 0). Status `a` or a null chance means full minutes.
  - **Later GWs with a return date:** if `news` contains one (e.g. "Expected back 22 Nov"), the player counts as out for every GW whose deadline falls before that date, and full after it.
  - **Later GWs without a return date:**
    - a player at 0% counts ×0.5 in the next GW and full from the GW after;
    - a player at 25–75% is full from the next GW;
    - a suspension (`s`) lasts 1 GW unless the news gives a length.
  - **Buying:** never buy a player at ≤50%. A 75% player may be bought only if he still ranks best *after* the minutes cut, and his reason must say "75% doubtful".
  - **Selling:** a player projected out for 3 or more of the 5 window GWs is marked a priority sell on the Transfers card.
- **Rivals shape every answer.** The engine picks the mode from my position in the tracked league:
  - **1st → Defend** against whoever is 2nd. Favour players the rivals own (their hauls become mine). Favour the captain the rivals are likely to pick. Penalise risky differentials.
  - **Not 1st → Chase** the manager *directly above me*. Favour high-projection players that manager doesn't own, and a captain they aren't on.
  - **Guardrail in both modes:** the mode only breaks near-ties. A player or captain enters on a cover or differential bonus only if his raw projection is close to the best alternative. Displayed points are always the raw projection; the mode never inflates the numbers I see.
- **Chips:** only the chips I still have are shown, read from FPL's entry history and respecting the 2026/27 two-per-season split (first set must be used by the GW19 deadline). For each chip:
  - **Triple Captain:** captain projection this GW, and the best GW for it within the 5-GW window.
  - **Bench Boost:** bench projection this GW, and the best GW within the window.
  - **Free Hit:** the best one-GW squad within budget vs my XI. Shows the gain.
  - **Wildcard:** the best squad over the window with unlimited transfers vs my best normal-transfer scenario. Shows the gain.

  The card says "play now" only when this GW is the best in the window and the gain clears a threshold.

  **Chip baseline (my call):** chip gains follow the selected scenario. Triple Captain and Bench Boost use the post-transfer squad of that scenario, and Wildcard is compared against that scenario's total. Free Hit and Wildcard squads are each optimised once per run; only the comparison is done for each of the 15 scenarios, so the extra runtime is small.
- **Automatic refresh.** The brief is regenerated on a schedule (see Architecture). The existing `FreshnessBadge` shows its age.
- **$0/month**, same as today.

## Non-goals

- Season-long chip planning, e.g. "save BB for the GW33 double". Only the 5-GW window is considered.
- Multi-week transfer planning (rolling a transfer, a sequence of moves across GWs). Transfers are made in the target GW and the resulting squad is held over the window.
- Reasons written by an LLM. Reasons come from templates filled with the engine's numbers.
- More than one league, or other users. There is one tracked league today (Cimanuk-ers, 1707018).
- Deploying to Vercel. The app stays on the local always-on dev server.
- Keeping any of the old tabs.

## Anti-goals (failure even if it "works")

- Recommending an injured, suspended or flagged-out player as a buy, or starting one when a fit option exists.
- Picking a captain or transfer *only* for being a differential or cover when it projects clearly worse.
- A reason that the numbers don't support, e.g. "differential vs Budi" when Budi owns him.
- Blending seasons or mis-attributing re-issued IDs (decisions #10, #13 and #14 in CLAUDE.md). Join on `id`, never `web_name`: 18 names collide in 2026/27.
- An app heavier or slower than today.

## Decided

- **Layout:** one scroll (mockup A). I chose it over pitch-first with tabs.
- **Window:** 5 GWs including the target GW.
- **FT input:** 1–5. **Hit input:** 0 / -4 / -8.
- **Mode rules:** Defend when 1st (against 2nd). Chase the manager directly above.
- **Old tabs:** delete them and their code (This week, Transfers, Rivals, Stats, Chart maker).
- **Chips:** included in v1 as described above.
- **Injury rules across the window:** as listed under Goals.

## Architecture (my calls unless marked)

### Engine: `fpl_brief_engine.py` (new, third engine)

The engine follows the repo conventions: sync only, `logging`, type hints plus one-line docstrings, `wait_for_supabase` + `assert_schema`, a `pipeline_runs` row on every run, and a healthchecks ping (`HEALTHCHECK_URL_BRIEF`). It writes only `weekly_brief`. It reads Supabase plus the live FPL API. The `FreshnessBadge` engine list (`web/src/components/FreshnessBadge.tsx`) gains the brief engine. Set-piece takers in the memory note are keyed by `web_name`, so resolve them to IDs by club.

**Projection model.** The spec is the memory notes:
- `~/.claude/projects/-Users-andremadian-Documents-1--PROJECTS-PERSONAL-AGENTIC-AI-FPL-Tool/memory/fpl-projection-model-v3.md` (v3 + v4 sections)
- `fpl-use-recency-weighted.md`
- `fpl-set-piece-takers-2026-27.md`

In short:
- Points per player per fixture are a blend of 0.70 expected and 0.30 regressed observed, scaled by expected minutes.
- Fixture strength comes from opponent xG/xGC (not FDR), with a home/away factor and clamping.
- Recency decay is 0.8 per GW, applied to rates and to minutes security.
- Regression to the positional median, a defensive-contribution term and set-piece duty are all included.
- Flagged GWs are skipped when estimating minutes security.
- The captain is chosen on a pure-expected basis.

Blank gameweeks score 0 and double gameweeks sum both fixtures. The set-piece taker list becomes a hand-edited Python dict in the repo. The model is not backtested; that's acknowledged, not in scope.

**Target GW:** the first GW whose deadline is in the future.

**My squad, bank, selling prices and chips used** come from the FPL public API: `entry/{id}/picks`, `/history/` and `/transfers/`. Selling price is purchase price plus half of any rise, rounded down. Purchase price is taken from the transfers list, or from GW1 `player_history.price` for original picks.

**Known limit:** the public API does not show transfers queued for the upcoming GW. The brief assumes none have been made since the last deadline, and the app says so in small text.

**Rivals: fetched live (my call).** The brief engine fetches standings and each rival's latest picks directly from the FPL API (`leagues-classic/{id}/standings`, `entry/{id}/event/{gw}/picks`) on every run. It does not rely on `league_rivals`/`rival_team_snapshots`, which are only written Fri/Sat and would leave Tue–Fri mode decisions on stale standings. The league ID and my team ID still come from `tracked_leagues`. The fetched responses are stored only inside the brief payload. The brief engine never writes to the user-engine tables, so the two engines stay disjoint.

**What "You vs rivals" compares (my call).** The comparison is for the target GW, the one I can still act on. Each rival's squad and captain is their most recent picks: their real team for the GW just locked, used as the best guess for the next. My side is my recommended post-transfer XI and captain for the selected scenario.

**Optimisation:** a scipy `milp`, the same formulation as the 2026-10-10 rebuild.
- A 15-man squad, 3 per club, within the selling-price budget.
- Valid formation.
- Objective: XI points + 0.12 × bench + captain double, summed over the 5-GW window, minus hit cost.
- Number of transfers ≤ FT + hits/4.

The rival-mode bonus enters the objective as a small multiplier on players according to target-rival ownership (Chase) or league ownership (Defend). It is capped by the near-tie guardrail. The builder picks the exact form and tuning, and must test that it does not override clear projection gaps.

**Scenarios.** Each run precomputes 5 FT values × 3 hit levels = 15 scenarios, plus the chip evaluations. The app picks a scenario client-side, so switching is instant and works offline.

Each scenario stores:
- transfers (out, in, gain over the window),
- XI, formation and bench order,
- captain and vice,
- projected target-GW points,
- the "would a hit pay?" note.

**Output.** One new row per run in table `weekly_brief`:
- `season`, `gw`, `generated_at`, `mode`, `payload jsonb`
- The payload holds all scenarios, chips and the rival comparison, plus the inputs used (squad, bank, flags) so a wrong answer can be traced.

The app reads the latest row.

### Migration `0014_weekly_brief.sql`

- Creates `weekly_brief` with RLS enabled and the "owner read" policy (the 0008 rule for new tables). The engine writes with the service key.
- Old curated views (0008–0013) stay in the database, unused. Dropping them isn't worth the risk. The engine's `assert_schema` requires 0014.

### Schedule

- New `com.fplsniper.brief` LaunchAgent, daily at 09:30 WIB, after the 09:00 daily and Tuesday postgw runs.
- A second slot on Saturday at 10:30, after the canonical rival capture.
- Logs go to `~/Library/Logs/fplsniper/cron.log`, never under `~/Documents` (decision #12).
- `health_check.py` should count it among the expected engines.

### Dependencies

- Add `scipy` (pinned) to `requirements.txt` and install it into `.venv`.

### PWA

Keep:
- `Login`, `useAuth`, `supabaseClient`, `FreshnessBadge`, `OfflineBanner`
- the PWA manifest and service worker setup

Delete:
- all files in `src/tabs/`
- `PlayerDetail`, `Sparkline`
- any tab-only hooks or types

Build:
- one `Brief` screen.
- FT and hit selections are remembered in `localStorage`, wrapped in try/catch, default FT 1 / hits none.
- The visual style follows the existing app.

### Docs

Update CLAUDE.md (phase table, engine section, schema, decision log) and the README.

## Left to the builder

- Exact form and tuning of the rival-mode bonus and the near-tie threshold.
- The chip "play now" threshold.
- Template wording for reasons.
- File layout of the engine (single file vs a small `brief/` package).
- Test approach. At minimum, unit tests on:
  - optimiser constraints (budget, 3-per-club, formation, transfer count),
  - the flagged-player exclusion,
  - the guardrail.
