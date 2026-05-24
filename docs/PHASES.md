# FPL Sniper — Phase Plan & Current State

> Use this doc as ground-truth context when refining Phase 2+ in Claude Chat. Paste the whole thing into a fresh conversation and pick up from "Open scope" below.

---

## Vision

FPL Sniper is a **conversational-first Fantasy Premier League companion app**, built in 5 phases. The end goal is an LLM-powered assistant that helps a single FPL manager (me) make decisions — transfers, captains, formations, chip timing — by querying personal data, league context, and historical signal.

| Phase | Status | One-line scope |
|---|---|---|
| 1. Data ingestion | ✅ shipped (May 2026) | Python script + Supabase schema, daily cron |
| 2. (not yet briefed) | ⬜ open | TBD — refine in Claude Chat |
| 3. Conversational layer | 🟡 scaffolded in schema | LLM agent with user-specific context |
| 4. (not yet briefed) | ⬜ open | TBD |
| 5. (not yet briefed) | ⬜ open | TBD |

---

## Phase 1 — Shipped

A daily Python script that fetches FPL data and writes it to Supabase Postgres. Running on local macOS cron (Friday 5pm WIB).

### Pipeline (5 functions called from `main()`)

1. `fetch_bootstrap()` — pulls bootstrap-static (840 players, 20 teams, gameweek metadata)
2. `write_snapshot()` — cleans + upserts `teams` + `players_master`
3. `fetch_player_history()` — for each active player (~534), pulls element-summary, builds GW history with DGW aggregation
4. `write_history()` — batch upserts `player_history` (~18.7k rows by end of season)
5. `fetch_fixtures()` + `write_fixtures()` — pulls /fixtures/ endpoint, upserts 380 fixtures with FDR + scores

Full run: ~2.5 minutes. Idempotent. Logs to `logs/cron.log`.

### Schema today

```
teams                   20 PL clubs + strength ratings
players_master          current snapshot per player (~840 rows)
                        includes price, ownership, form, xG/xA/xGI/xGC (season cumulative),
                        derived points_per_90 / price_per_point / cbit
player_history          per-(player, GW) time series (~18.7k rows)
                        per-GW stats; PK (player_id, gw); xgc added in migration 0002
team_history            view aggregating player_history to team-GW level
                        team_xgc = MAX(xgc) over players (NOT sum, since xgc scales with minutes)
fixtures                every PL fixture this season (380 rows, ~10 unfinished at season's end)
                        FDR ratings, kickoff times, scores (null until finished=true)

users / user_rivals / conversations / messages / user_profile
                        SCAFFOLDED, EMPTY — populated by Phase 3+
                        RLS enabled on all of these, scaffolded for multi-tenant
                        (but realistically one user)
```

### Curated SQL queries (in `sql/queries/`)

| File | Purpose | Sort key |
|---|---|---|
| `attackers_recent_form.sql` | xGI + form over last 5 GWs | xgi_last_5 |
| `defenders_recent_form.sql` | CBIT/game + xGC + form over last 5 GWs | cbit_per_game |
| `attackers_projection.sql` | xGI × opp xGC × form_recent for upcoming fixtures | projection_score |
| `defenders_projection.sql` | CBIT × form / (own xGC × opp xG) for upcoming fixtures | projection_score |

Projection queries also return `form_3gw` and `form_delta` as acceleration signals (`form_delta > 0` = heating up, `< 0` = cooling off, `~0` = stable).

### Capability matrix — what can the data answer today?

✅ Recent form rankings (attackers, defenders)
✅ Matchup projections when fixtures are unfinished (`fixtures.finished = false`)
✅ Price trajectory of any player across the season
✅ Players who outperformed/underperformed their xG
✅ Team-level defensive form (`team_xgc` per GW)
✅ Fixture difficulty for upcoming weeks (FDR + recent xG/xGC context)
✅ Acceleration signals (3GW vs 5GW form delta)
✅ Highest-scoring single gameweeks, season trends, ownership shifts

❌ User's own FPL team / squad / transfer history
❌ User's rivals' squads (mini-league comparisons)
❌ Captain optimization based on user's current squad
❌ Chip-strategy modeling
❌ Conversational interface (LLM agent)
❌ Cross-season analysis — current ingestion overwrites players_master each season because FPL re-issues player IDs
❌ Injury / lineup news (no external sources beyond FPL API)
❌ Underlying stats beyond FPL's: shots in box, big chances created, etc. (would need FBref/Understat)

---

## Phase 3 — Implied by the schema

The 5 user-related tables that are already in the schema strongly imply Phase 3 is **"build the LLM-driven chat app on top of the Phase 1 data layer"**:

- `users` — FPL team owner + their FPL team ID + display name
- `user_rivals` — mini-league rivals, with squads pulled from FPL API
- `conversations` + `messages` — OpenAI-style chat history with `tool_calls` jsonb (LLM tool-use)
- `user_profile` — LLM-maintained summary of the user (preferences, risk tolerance, style, decision history)

The agent in Phase 3 would presumably:
- Query the Phase 1 tables on demand (using the saved queries + ad-hoc SQL)
- Know the user's own team and watchlist
- Know their rivals' squads
- Maintain conversational memory across sessions
- Maintain a long-term profile of the user

Phase 3 is "sketched, not briefed." Phases 2, 4, 5 are wide open.

---

## Open scope — Phases 2, 4, 5

Phase 2 is the next decision. The most useful framing isn't "what's elegant to build" — it's **"what's the smallest thing that would change my actual Friday-afternoon decisions?"**

### Possible Phase 2 directions (not exhaustive — Claude Chat can expand)

1. **External data enrichment** — pull from FBref / Understat / Twitter for signals FPL doesn't track (shot locations, big chances, injury news). Stays within the ingestion paradigm of Phase 1, just adds more sources.
2. **Cross-season history** — fix the player-ID re-issue problem so historical seasons can be analyzed. Probably a small change (a `seasons` table + player name-matching), but unlocks "compare Salah's 2024/25 vs 2025/26".
3. **User team ingestion** — fetch the user's own FPL team via `/entry/{team_id}/` and `/entry/{team_id}/event/{gw}/picks/`. Lightweight version of Phase 3's user layer. Doesn't require chat or auth — just one more table.
4. **Personalized digest** — instead of building a frontend, automate "every Friday after the cron run, generate a markdown digest of: my team's projections, my rivals' likely captain picks, transfer recommendations, and email it to me." Skill output, no UI needed.
5. **Frontend / dashboard** — Supabase Studio is fine for ad-hoc queries but slow for weekly review. A bookmarkable web UI (Next.js / Streamlit) on top of the queries.
6. **Chip strategy backtester** — historical data → simulate "what if I'd used Triple Captain in GW X". Pure SQL/Python; no new ingestion needed.
7. **The full Phase 3 jump** — go straight to the conversational agent if you believe that's the actual unlock.

### Questions to answer (in Claude Chat)

1. **What's the biggest pain when playing FPL right now?** Don't generalize — name the specific situation that wastes time or causes a bad call.
2. **Is the next bottleneck data (missing signal) or UX (signal is there, but takes too long to extract)?**
3. **What's the minimum data your decision-making process actually uses?** If it's just "form + fixtures + xG vs xGC" — Phase 1 already covers this and Phase 2 should be UX/automation, not more data.
4. **Local-only, or does Phase 2 need any hosting?** (Same constraint as Phase 1 — you prefer local cron over paid platforms.)
5. **Cross-season** — fix it now as a small Phase 1.5 detour, or defer? Probably defer unless you're about to lose the 2025/26 data when 2026/27 starts in July.
6. **What does success look like for Phase 2?** A concrete test: "I should be able to do X in Y minutes that takes me Z minutes today."

### Suggested prompts for Claude Chat

Paste this doc and open with one of these:

> "Based on the ❌ list and the open Phase 2 directions in this doc, help me pick the highest-leverage Phase 2. Walk me through the 'questions to answer' section one at a time."

> "Help me write the brief for Phase 2 in the same format as my Phase 1 brief. Push back on scope — keep it inspectable."

> "I'm worried I'm building elegant infrastructure but not improving my actual FPL decisions. Use the capability matrix to argue for the smallest Phase 2 that meaningfully changes my Friday process."

---

## Deployment + repo facts (for context)

- **Repo:** [github.com/andremadian/fpltool](https://github.com/andremadian/fpltool) (public)
- **Cron tag:** `# fpl-sniper-fetch` in user's local crontab
- **Schedule:** `0 17 * * 5` (Friday 5pm WIB)
- **Logs:** `logs/cron.log` (gitignored)
- **Stack:** Python 3.14, Supabase Postgres, pandas, supabase-py 2.30.0+, requests, python-dotenv
- **Deployment philosophy:** local cron preferred over paid hosting (saved to memory)
- **Original Phase 1 brief:** `FPL_Sniper_Phase1_ClaudeCode_Brief.md` in repo root — attach this to Claude Chat for full Phase 1 detail
- **Project-level operational doc:** `CLAUDE.md` in repo root — explains decisions that departed from the brief (supabase-py version, DGW aggregation, in-memory filter, RLS choice, fixtures schema)
