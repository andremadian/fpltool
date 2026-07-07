# TODOS — ordered continuation backlog

> The pick-up-where-you-left-off list. Strategy context: [EXPANSION_PLAN.md](EXPANSION_PLAN.md). Last updated: July 7, 2026.

## Now (before GW1 2026/27, ~mid-August)

- [ ] **Arm the dead-man switch** — create three checks at healthchecks.io (free), paste ping URLs into `.env` as `HEALTHCHECK_URL_WEEKLY` / `_DAILY` / `_USER` (grace: daily = 1 day, others weekly), then run `.venv/bin/python fpl_engine.py --daily` and confirm the check goes green. *The one remaining Phase 3A item; closes the silent-failure hole for good. Owner: Andre (needs account signup).*
- [ ] **Set git identity** — `git config --global user.name / user.email`; optionally amend unpushed commits (`--reset-author`) before pushing.
- [ ] **Push to GitHub** — local `main` is ahead of origin (expansion plan, Phase 3A, Phase 3B brief).

## Next (Phase 3B — conversational agent)

Brief: [FPL_Sniper_Phase3B_ClaudeCode_Brief.md](../FPL_Sniper_Phase3B_ClaudeCode_Brief.md). Three sessions, each ends with a commit:

- [ ] **Session 1 — agent core + CLI**: migration 0008 (seed user + `run_readonly_query`), `fpl_agent.py` (4 tools, SQL guard, Claude loop, persistence), `fpl_chat.py --cli`. Done criteria 1–4.
- [ ] **Session 2 — Telegram front-end**: BotFather token + chat id (Andre), sync long-poll loop, allowlist, chunking. Done criterion 5.
- [ ] **Session 3 — evals + install**: `evals/` golden questions + guard tests, `com.fplsniper.chat` KeepAlive plist, README/CLAUDE.md updates. Done criteria 6–10.

User-side prerequisites for 3B: an Anthropic API key (`ANTHROPIC_API_KEY`), a Telegram bot token from @BotFather, your Telegram chat id.

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
