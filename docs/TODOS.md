# TODOS — ordered continuation backlog

> The pick-up-where-you-left-off list. Strategy context: [EXPANSION_PLAN.md](EXPANSION_PLAN.md). Last updated: July 7, 2026.

## Now (before GW1 2026/27, ~mid-August)

- [ ] **Arm the dead-man switch** — create three checks at healthchecks.io (free), paste ping URLs into `.env` as `HEALTHCHECK_URL_WEEKLY` / `_DAILY` / `_USER` (grace: daily = 1 day, others weekly), then run `.venv/bin/python fpl_engine.py --daily` and confirm the check goes green. *The one remaining Phase 3A item; closes the silent-failure hole for good. Owner: Andre (needs account signup).*
- [ ] **Set git identity** — `git config --global user.name / user.email`; optionally amend unpushed commits (`--reset-author`) before pushing.
- [ ] **Push to GitHub** — local `main` is ahead of origin (expansion plan, Phase 3A, Phase 3B brief).

## Next (Phase 3B — personal edge PWA; AI agent deferred)

Brief: [FPL_Sniper_Phase3B_PWA_Brief.md](../FPL_Sniper_Phase3B_PWA_Brief.md) (the [agent brief](../FPL_Sniper_Phase3B_ClaudeCode_Brief.md) is deferred — revive as a PWA chat tab only if fixed views prove insufficient). Four sessions, each ends with a commit:

- [ ] **Session 1 — foundation & lockdown**: migration 0008 (RLS lockdown + `gameweeks` + 9 views), Supabase auth setup (invite email, disable signups, redirect URLs), `write_gameweeks` in `fpl_engine.py`. Done criteria 1–5. *Do this before any UI — it closes the anon-key write hole.*
- [ ] **Session 2 — shell + This week + Transfers**: Vite scaffold in `web/`, magic-link login, tab shell + freshness badge, tabs 1–2 with empty states.
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
