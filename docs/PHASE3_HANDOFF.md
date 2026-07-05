# FPL Sniper — Phase 3 Handoff Doc

Paste this entire document into a fresh Claude Chat conversation to produce the Phase 3 brief.

---

## What this project is

**FPL Sniper** is a conversational-first Fantasy Premier League companion app, built in 5 phases by one person (me), for one person (me). The end goal is an LLM-powered assistant that helps me make FPL decisions — transfers, captains, formations, chip timing — by querying personal data, league context, and historical signal from a Supabase Postgres database.

**Stack:** Python 3.11 (project venv at `.venv/` — cron runs the engines through it), Supabase Postgres, supabase-py 2.30.0, pandas, requests, python-dotenv. No cloud hosting — local macOS cron for all automation. No auth (yet).

---

## What has been built (Phases 1 and 2 — both shipped)

### Phase 1 — Global FPL data ingestion (`fpl_engine.py`)

A Python script that runs every Friday 5pm WIB via local cron and writes global FPL data to Supabase.

**Pipeline:**
1. `fetch_bootstrap()` — pulls bootstrap-static (840 players, 20 teams, GW metadata)
2. `write_snapshot()` — upserts `teams` + `players_master`
3. `fetch_player_history()` — per active player, pulls element-summary, aggregates DGW rows, builds GW time series
4. `write_history()` — batch upserts `player_history` (~18.7k rows by season end)
5. `fetch_fixtures()` + `write_fixtures()` — upserts all 380 fixtures with FDR + scores

Full run: ~2.5 minutes. Idempotent.

**Tables populated:**

| Table | Description |
|-------|-------------|
| `teams` | 20 PL clubs + strength ratings |
| `players_master` | Current snapshot per player (~840 rows). Includes `price`, `ownership`, `form`, `xG/xA/xGI/xGC` (season cumulative), derived `points_per_90`, `price_per_point`, `cbit` |
| `player_history` | Per-(season, player, GW) time series. PK `(season, player_id, gw)`. Per-GW stats including `xgc` |
| `team_history` | View aggregating `player_history` to (season, team, GW) level. `team_xgc = MAX(xgc)` over players |
| `fixtures` | All 380 fixtures per season, PK `(season, id)`. FDR ratings, kickoff times, scores (null until `finished=true`) |
| `players_season_archive` / `teams_season_archive` | Who each re-issuable FPL ID referred to in a given season. Snapshotted automatically at season end (migration 0005) — join these for historical-season names |

**Curated SQL queries in `sql/queries/`:**
- `attackers_recent_form.sql` — xGI + form over last 5 GWs
- `defenders_recent_form.sql` — CBIT/game + xGC + form over last 5 GWs
- `attackers_projection.sql` — xGI × opp xGC × form for upcoming fixtures (includes `form_3gw`, `form_delta`)
- `defenders_projection.sql` — CBIT × form / (own xGC × opp xG) for upcoming fixtures

### Phase 2 — User + rivals ingestion (`fpl_user_engine.py`)

A second Python script that runs Fridays 5:30pm + Saturdays 10am WIB. Ingests my own FPL squad per GW and the squads of all rivals across my tracked mini-leagues.

**Pipeline:**
1. `load_tracked_leagues()` — reads config table; exits cleanly if empty
2. `fetch_bootstrap()` + `determine_current_gw()` — anchors to `is_current` GW (falls back to `is_next`)
3. `fetch_and_write_my_squads()` — picks + /history/ for each unique `my_fpl_team_id`, upserts `user_team_snapshots`
4. `write_league_standings()` — paginates `/leagues-classic/.../standings/`, upserts `league_rivals`
5. `fetch_rival_squads()` — deduplicated rival IDs across leagues, jittered sleep, skips pre-deadline 404s and stale GW responses
6. `write_rival_squads()` — batch upserts `rival_team_snapshots` in chunks of 200

Runtime: ~5–30s. Saturday 10am run is the canonical capture (post-deadline); Friday run is a safety net.

**Tables populated:**

| Table | Description |
|-------|-------------|
| `tracked_leagues` | Config table. Manually populated. One row per league to follow. Includes `my_fpl_team_id`. |
| `user_team_snapshots` | My squad per GW. PK `(season, fpl_team_id, gw)`. Includes captain, chip, bench, transfers, event_points, overall_rank, bank, team_value. |
| `league_rivals` | Mini-league standings. PK `(league_id, rival_fpl_team_id)`. Replaced (delete + insert) each run. |
| `rival_team_snapshots` | Rivals' squads per GW. PK `(season, rival_fpl_team_id, gw)`. Same shape as `user_team_snapshots` minus personal-finance fields. |

**Phase 2 SQL queries in `sql/queries/`:**
- `my_squad_vs_rivals.sql` — my players + % of rivals who own them (sorted by rival_ownership_pct asc — differentials at top)
- `rival_captain_consensus.sql` — who rivals captained and how many times, for the most recent GW
- `rival_transfers_in_out.sql` — who rivals transferred in/out between the last two GWs
- `league_template_vs_global.sql` — players heavily owned by rivals but not globally (template_delta = rival_pct − global_pct)

---

## What the schema has scaffolded but not yet used

These five tables exist in the schema (migration 0001) but are **empty**. They are the scaffolding for Phase 3:

| Table | Purpose |
|-------|---------|
| `users` | FPL team owner — display name, FPL team ID, created_at. FKs to `auth.users`. |
| `user_rivals` | Rivals associated with a user (for user-scoped views). FKs to `auth.users`. |
| `conversations` | Chat sessions. FKs to `auth.users`. Has `title`, `created_at`, `updated_at`. |
| `messages` | Individual messages in a conversation. Includes `role` (user/assistant/tool), `content`, `tool_calls` jsonb (for LLM tool-use). |
| `user_profile` | LLM-maintained summary of the user — preferences, risk tolerance, decision history, watchlist. |

RLS is enabled on all five. They're multi-tenant-ready but in practice will have one user.

---

## Full capability matrix today

**What the data can answer:**

✅ Recent form rankings (attackers, defenders)
✅ Matchup projections for upcoming fixtures
✅ Price trajectory of any player across the season
✅ Players who outperformed/underperformed their xG
✅ Team-level defensive form (team_xgc per GW)
✅ Fixture difficulty for upcoming weeks (FDR + xG/xGC context)
✅ Acceleration signals (3GW vs 5GW form delta)
✅ My squad vs rivals ownership comparison
✅ Rival captain consensus for a given GW
✅ Rival transfer patterns between GWs
✅ Mini-league template vs global template

**What it still cannot answer:**
❌ Conversational interface — no LLM agent, no chat
❌ Captain optimization that accounts for my specific squad (e.g. "given my squad, who should I captain?")
❌ Transfer recommendations grounded in budget + squad context
❌ Chip strategy recommendations
❌ Injury / lineup news (FPL API doesn't expose this; would need external sources)
❌ Underlying stats: shots in box, big chances created (would need FBref/Understat)
✅ Cross-season data integrity (migration 0005: all time-series tables are season-keyed, and `players_season_archive`/`teams_season_archive` preserve what each re-issued ID meant per season — though cross-season *player identity linking* still doesn't exist, since FPL provides no stable player ID)

---

## Phase 3 — What the schema implies

The five scaffolded tables strongly suggest Phase 3 is the **conversational layer**: an LLM agent that can query the Phase 1 + 2 data on demand, know the user's own squad context, and maintain conversation history + a long-term user profile across sessions.

What a Phase 3 agent would presumably do:
- Answer FPL questions in natural language ("who should I captain this week?" / "is Salah worth the premium right now?")
- Run the saved SQL queries (or ad-hoc SQL) on demand, scoped to my league context
- Know my current squad, budget, chip status
- Know my rivals' likely picks (from `rival_team_snapshots`)
- Maintain chat history across sessions (via `conversations` + `messages`)
- Maintain a long-term profile of my FPL style, preferences, chip history (via `user_profile`)

This is "sketched, not briefed." The goal of the Claude Chat session this doc seeds is to **produce a detailed Phase 3 brief** in the same format as the Phase 1 and Phase 2 briefs.

---

## Key constraints and decisions to carry forward

1. **Local-first, no paid hosting.** All Phase 1 + 2 automation runs on local macOS cron. Phase 3 may introduce a small server (to handle chat requests), but the preference is still local or free-tier.
2. **Single user.** Phase 3 auth scaffolding exists but this is a personal tool. Multi-tenant support is a nice-to-have, not a requirement.
3. **No new dependencies without justification.** Phase 1 + 2 have zero dependencies beyond what's in `requirements.txt`. If Phase 3 adds LLM calls, explain which SDK and why.
4. **Sync Python preferred.** The brief mandate was "synchronous only." If Phase 3 needs async (e.g. streaming LLM responses), call it out and justify.
5. **Supabase-py pinned to 2.30.0+** — not 2.9.1 (that version rejects the new `sb_secret_*` API key format Supabase rolled out in late 2025).
6. **Migration files are numbered sequentially.** Applied migrations so far: 0001 (initial), 0002 (xgc column), 0003 (fixtures), 0004 (Phase 2 tables), 0005 (season rollover). Next migration is **0006**.

---

## Questions to answer before writing the Phase 3 brief

Use these to guide the Claude Chat conversation before producing the brief:

1. **What's the actual interface?** CLI chat in terminal? A local web UI (e.g. Streamlit)? A WhatsApp/Telegram bot? A simple HTTP endpoint I query via curl?
2. **Which LLM?** Claude API (most natural for this stack) or something else? Streaming or one-shot responses?
3. **Tool use vs RAG?** Does the agent run SQL tools on demand (tool-use pattern) or do queries get embedded and retrieved (RAG)? Tool-use is simpler and more controllable for structured data.
4. **Does Phase 3 need auth?** The schema has it scaffolded, but if this is local + single user, skipping Supabase Auth entirely and using a hardcoded user ID may be the right call.
5. **What's the minimum useful version?** A Phase 3 that just lets me ask "who should I captain?" and gets a grounded answer from the data — no history, no profile — is a valid v1. History and profile can be Phase 3.1.
6. **How should the agent handle the FPL season end / off-season?** (Season ends ~May, restarts ~August.) The ingestion side already handles this — both engines detect a completed season, archive identities, and idle until the new API goes live; queries anchor on the latest season automatically. The open question is only conversational: what should the agent say/do when asked for advice during the off-season?

---

## Suggested opening prompt for this Claude Chat session

> "I'm planning Phase 3 of my FPL Sniper project — a conversational LLM agent that queries my FPL data in Supabase. I've pasted the full context above. Before writing the brief, walk me through the 'Questions to answer' section one at a time so we can nail down the scope. Start with the interface question."

Or, if you already know what you want:

> "Based on the context above, write the Phase 3 brief in the same format as the Phase 2 brief at the bottom of this doc. Interface: [X]. LLM: Claude API. Auth: skip Supabase Auth for now, hardcode user. Tool-use pattern, not RAG. Push back on scope — keep it inspectable and buildable in one session."

---

## Reference: Phase 2 brief (for format parity)

The Phase 2 brief lives at `FPL_Sniper_Phase2_ClaudeCode_Brief.md` in the repo root. Its structure was:
- What you're building (1 paragraph)
- Existing context (what Phase 1 shipped)
- Deliverables (exact file list)
- Tech constraints
- Schema additions (exact SQL)
- Python script spec (step-by-step, each step a named function)
- Environment variables
- Quality bar
- Cron / deployment
- SQL queries (purpose + required columns + sort)
- What you don't need to build
- Done criteria (numbered, verifiable without follow-up)
- Order of operations

The Phase 3 brief should match this structure.
