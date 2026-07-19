# TODOS — ordered continuation backlog

> The pick-up-where-you-left-off list. Strategy context: [EXPANSION_PLAN.md](EXPANSION_PLAN.md). Last updated: July 7, 2026.

## Now (before GW1 2026/27, ~mid-August)

- [x] **Arm the dead-man switch** — three checks created at healthchecks.io, ping URLs added to `.env`, confirmed `fpl-daily` goes green on `--daily` run (2026-07-19). Closes the last Phase 3A item.
- [x] **Set git identity** — `git config --global user.name/email` set to `andremadian` / `andremadian@gmail.com` (2026-07-19).
- [x] **Push to GitHub** — pushed local `main` (expansion plan, Phase 3A, Phase 3B brief) to origin (2026-07-19).

## Next (Phase 3B — personal edge PWA; AI agent deferred)

Brief: [FPL_Sniper_Phase3B_PWA_Brief.md](../FPL_Sniper_Phase3B_PWA_Brief.md) (the [agent brief](../FPL_Sniper_Phase3B_ClaudeCode_Brief.md) is deferred — revive as a PWA chat tab only if fixed views prove insufficient). Four sessions, each ends with a commit:

- [x] **Session 1 — foundation & lockdown** (2026-07-19): migration 0008 applied (RLS lockdown + `gameweeks` + `league_rivals.is_me` + `player_season_stats` + 8 curated-query views); Supabase auth configured (invited andremadian@gmail.com, sign-ups/anonymous disabled, OTP template includes `{{ .Token }}`, redirect allowlist has `localhost:5173` for dev); `write_gameweeks()` in `fpl_engine.py` + `is_me` handling in `fpl_user_engine.py`. Done criteria 1–5 all verified: both engines write clean post-lockdown, anon key gets permission-denied on read+write, UUID-impersonation SQL test confirms the owner-read policy, all 9 views queryable with `player_season_stats` G+A spot-checked against raw `player_history` sums.
- [x] **Session 2 — shell + This week + Transfers** (2026-07-19): Vite + React + TS app scaffolded in `web/` (strict TS, `@supabase/supabase-js`, no router — tabs are local state so refresh/redirect can't 404, no chart lib — plain SVG sparklines). Login flow (`signInWithOtp` + `verifyOtp`, magic-link **and** email-code paths per loophole #15). Tab shell (This week / Transfers / Rivals-stub / Charts-stub), freshness badge over `pipeline_runs`, offline banner (window online/offline events; SW is Session 4). This week (deadline countdown + off-season empty state, captain list grouped/squad-filtered from `attackers_projection`, alerts from `players_master` + `player_daily` movers). Transfers (Attackers/Defenders sub-tabs, group-by-player DGW-summed ranking, expandable detail with price/ownership sparklines + `player_season_stats`). **Migration 0009** added (`player_id` appended to the four projection/form views — a join-key gap found during planning; the PWA needs it to filter projections to my squad and pull per-player detail). Verified end-to-end in the browser at 390px: OTP login → all four tabs render correct **off-season empty states** (pre-GW1, so projections/countdown are legitimately empty), freshness badge green+honest ("off-season · <ts>"), per-engine expand panel, zero console errors, `npm run build` clean. Two bugs caught & fixed during verification: login field hard-capped at 6 digits (this project's OTP is 8) → now 6–10; freshness badge read only `status='success'` → a healthy off-season `skipped_offseason` daily run now reads green (loophole #8's intent is "pipeline alive", which a skipped run proves). Docs (CLAUDE.md phase table / `web/` tree / migrations 0008–0009 / lockdown decision) deferred to Session 4 with the rest of done-criterion 11, same as Session 1.
- [ ] **Session 3 — Rivals + Chart maker**: tabs 3–4 (bubble chart: x/y/size metric pickers, my-squad highlight). Done criteria 6–7.
- [ ] **Session 4 — PWA polish + deploy**: manifest/service worker (network-only for Supabase), install tests (iOS + Android), Vercel deploy, docs. Done criteria 8–11.

User-side prerequisites for 3B: a Vercel account (free Hobby tier), and the Supabase dashboard auth steps in the brief (invite your email, disable sign-ups). No API keys, no recurring cost.

## Then (Phase 4 — the Sniper Brief)

- [ ] **Write the Phase 4 brief** (after 3B session 3) — scheduled agent run (cron-shaped, reuses 3B's agent core + notifier), composes the Friday pre-deadline push: projected XI, captain ranking, transfers with rival-swing context, price/news alerts from `player_daily`, freshness footer. Saturday post-deadline recap optional. Off-season: monthly quiet-mode digest. `user_profile` learning starts here.
- [ ] **First real-season eval pass** — after a few 2026/27 GWs, grow `golden_questions.yaml` to ~20 with live-season cases (DGW, price-change morning, post-deadline stale-rival window).

## Later (gated)

- [ ] **Phase 5 — league surface** (gate: you actually want path B). Preconditions in EXPANSION_PLAN: RLS data-model redesign, remove/scope `run_sql` before a second user, FPL API load assessment. Then web dashboard + invites + GH Actions ingestion.
- [ ] **Phase 6 — competitive bets** (gate: Phase 5 retention). Own xP model, solver optimizing league win probability, Understat enrichment, price predictor.
- [ ] **Re-verify market claims before the Phase 5 gate** — official FPL/Microsoft assistant's actual scope, FBref data situation, incumbent pricing (flagged unverified in EXPANSION_PLAN sources note).

## Housekeeping

- [ ] `pip` in venv is old (23.2.1) — harmless; upgrade opportunistically.
- [ ] gstack upgrade available (0.16.2 → 1.58.5) — `/gstack-upgrade` when convenient.
