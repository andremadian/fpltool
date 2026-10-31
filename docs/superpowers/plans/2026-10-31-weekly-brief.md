# Weekly Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the five-tab PWA with one scrolling screen of five weekly answers (transfers, best XI, captain, you vs rivals, chips), produced by a new scheduled engine that runs the committed projection model.

**Architecture:** A new `brief/` Python package holds the model, injury rules, MILP optimiser, rival logic and chip logic as pure functions. `fpl_brief_engine.py` orchestrates them: it reads Supabase and the live FPL API, precomputes 15 scenarios (FT 1–5 × hits 0/4/8), and inserts one JSON row into `weekly_brief`. The PWA reads the latest row and picks a scenario client-side.

**Tech Stack:** Python 3 + supabase 2.30.0 + pandas + numpy + scipy (`milp`) + pytest; React 19 + Vite + TypeScript; Supabase Postgres; macOS launchd.

**Spec:** `docs/superpowers/specs/2026-10-31-weekly-brief-design.md`.

The model's formulas live in these memory notes; the Task 4 implementer must read them:
- `~/.claude/projects/-Users-andremadian-Documents-1--PROJECTS-PERSONAL-AGENTIC-AI-FPL-Tool/memory/fpl-projection-model-v3.md`
- `fpl-use-recency-weighted.md` (same folder)
- `fpl-set-piece-takers-2026-27.md` (same folder)

## Global Constraints

- **Window:** 5 GWs = target GW + next 4, capped at GW38. The target GW is the first GW whose `deadline_time` is in the future.
- **Scenarios:** FT ∈ {1,2,3,4,5} × max hit ∈ {0,4,8}. Scenario key is `"{ft}_{hits}"`, e.g. `"2_4"`.
- **Hit cost:** 4 × max(0, transfers − FT). Transfers ≤ FT + hits/4.
- **Engine conventions:**
  - sync only, `logging` at INFO, no `print()`;
  - type hints and a one-line docstring on every function;
  - `wait_for_supabase` + `assert_schema` at startup;
  - a `pipeline_runs` row on every run (engine name `fpl_brief_engine`);
  - ping `HEALTHCHECK_URL_BRIEF`.
- **Always run via `.venv/bin/python`.** scipy and pytest are pinned in `requirements.txt` and installed into `.venv`.
- **The brief engine writes only `weekly_brief`.** It never writes user-engine or Phase 1 tables.
- **Join players on `id`, never `web_name`.** There are 18 name collisions in 2026/27.
- **Paginate with `.order(...)`.** Every paginated Supabase read (`range()`) must order on its PK, or pages overlap.
- **Supabase reads are current-season only.** `players_master` is filtered by `last_seen_season = season` (decision #14).
- **Displayed points are always raw projections.** The rival-mode bonus never appears in a number shown to the user.
- **Injury rules** (verbatim from the spec):
  - Target GW: chance scales minutes (75% → ×0.75, 0% → 0). Status `a` or a null chance means ×1.
  - A return date in `news` means out for every GW whose deadline is before that date.
  - With no date: 0% means ×0.5 the next GW, then full; 25–75% means full from the next GW; `s` lasts 1 GW unless the news gives a length.
  - Never buy a player at ≤50%. A 75% player may be bought only if he ranks best after the cut, and his reason says "75% doubtful".
  - A player out for ≥3 of the 5 window GWs is a priority sell.
- **Rival mode:**
  - 1st → `defend` against rank 2.
  - Otherwise → `chase` against the entry ranked directly above me.
- **Chips:** one use per half-season (GW1–19, GW20–38). Codes are `wildcard`, `freehit`, `bboost`, `3xc`.
- **The web app reads Supabase via the anon key only.**
- **Logs live in `~/Library/Logs/fplsniper/cron.log`**, never under `~/Documents`.
- **The old curated views stay in the database.** Only the web code that used them is deleted.

## Review Focus

1. **Blank GW in the window:** a player whose team doesn't play in a window GW projects 0 for that GW, and the optimiser must still field a legal XI. Test in Task 5 (`test_blank_gw_player_benched`).
2. **Double GW:** both fixtures are summed. Test in Task 4 (`test_double_gw_sums_fixtures`).
3. **Window near season end** (target GW 36): the window shrinks to 36–38 without errors. Test in Task 3 (`test_window_capped_at_38`).
4. **Tied league points**, or me with no entry above (rank 1 tied): mode is decided by standings `rank`, then by list order. Test in Task 6 (`test_mode_tied_points_uses_rank_order`).
5. **Rival with no picks yet** (a new entry, or a 404): skip them and show "no squad yet". Never crash. Test in Task 6 (`test_rival_without_picks_skipped`).

## File Structure

| File | Responsibility |
|---|---|
| `brief/__init__.py` | empty |
| `brief/types.py` | dataclasses shared across the package |
| `brief/fpl_api.py` | live FPL API fetches (bootstrap, entry history/picks/transfers, league standings, rival picks) |
| `brief/data.py` | Supabase reads (history, fixtures, gameweeks, player_daily, tracked_leagues) |
| `brief/window.py` | target GW and window resolution |
| `brief/availability.py` | injury and suspension multipliers per window GW, buy eligibility, priority sells |
| `brief/set_pieces.py` | the set-piece taker table and its resolution to player IDs |
| `brief/model.py` | per-player per-GW projections (points + captain basis) |
| `brief/squad.py` | my squad, selling prices, bank, chips still available |
| `brief/optimise.py` | the MILP squad/XI/captain optimiser |
| `brief/rivals.py` | mode, target, ownership weights, rival projections |
| `brief/chips.py` | chip evaluation |
| `brief/payload.py` | scenario assembly, reason templates, payload dict |
| `fpl_brief_engine.py` | orchestration + ops helpers (copied from `fpl_user_engine.py`) |
| `tests/test_*.py` | one test file per `brief/` module |
| `supabase/migrations/0014_weekly_brief.sql` | table + RLS |
| `launchd/com.fplsniper.brief.plist` | schedule |
| `web/src/brief/*` | payload types, data hook, screen, cards |

---

### Task 1: Migration, dependencies, test harness

**Files:**
- Create: `supabase/migrations/0014_weekly_brief.sql`
- Create: `brief/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `.gitignore`

**Interfaces:**
- Produces: the table `weekly_brief(id bigint identity pk, season text not null, gw int not null, generated_at timestamptz not null default now(), mode text not null, payload jsonb not null)`, with an index on `generated_at desc`.

- [ ] **Step 1: Write the migration.**
  - Create the table above.
  - `alter table weekly_brief enable row level security`.
  - Add `create policy "owner read" ... for select to authenticated using ((select auth.uid()) = '8c4afa9c-e4ed-4b45-9f9e-02f347944ecb'::uuid)`, same as `0008_pwa_foundation.sql:588`.
  - `revoke insert, update, delete on weekly_brief from authenticated` and `revoke all on weekly_brief from anon`.
  - Make it idempotent: `create table if not exists`, and wrap the policy in the same `duplicate_object` handler.
- [ ] **Step 2: Add the dependencies.** Append `scipy==1.16.2` and `pytest==8.4.2` to `requirements.txt`. Add `HEALTHCHECK_URL_BRIEF=` to `.env.example`. Add `.superpowers/` to `.gitignore`.
- [ ] **Step 3: Install.**
  - Run `.venv/bin/pip install -r requirements.txt`.
  - Then run `.venv/bin/python -c "import scipy.optimize as o; print(o.milp)"`.
  - Expected: prints a function.
- [ ] **Step 4: Ask the user to apply 0014** in the Supabase SQL Editor. Do not continue until they confirm.
- [ ] **Step 5: Check the harness.** Run `.venv/bin/python -m pytest -q`. Expected: "no tests ran", exit code 5.
- [ ] **Step 6: Commit.**

```bash
git add supabase/migrations/0014_weekly_brief.sql brief/__init__.py tests/ requirements.txt .env.example .gitignore
git commit -m "Weekly brief: migration 0014, scipy + pytest"
```

(`.gitignore` already has uncommitted user edits. Before committing, show the user the full diff and ask whether to include those edits too.)

---

### Task 2: Shared types + live FPL API + Supabase reads

**Files:**
- Create: `brief/types.py`
- Create: `brief/fpl_api.py`
- Create: `brief/data.py`
- Test: `tests/test_data.py`

**Interfaces — produces (`brief/types.py`, all `@dataclass(frozen=True)`):**
- `Player(id: int, name: str, team_id: int, team_short: str, pos: str, price: float, status: str, chance: int | None, news: str)`. `pos` is one of `GKP|DEF|MID|FWD`; `name` is `web_name`.
- `Fixture(gw: int, team_id: int, opp_id: int, home: bool)`. Each FPL fixture produces two of these, one per side.
- `Gameweek(gw: int, deadline: datetime)`.
- `HistoryRow(player_id: int, gw: int, minutes: int, total_points: int, xg: float, xa: float, xgc: float, bps: int, cbit: int, goals: int, assists: int, clean_sheets: int)`.
- `FlagRow(player_id: int, as_of_date: date, status: str, chance: int | None)`.

**Interfaces — produces (`brief/fpl_api.py`):** each function GETs `https://fantasy.premierleague.com/api/...` with a 30s timeout, raises on non-2xx except where noted, and sleeps 0.5–1.0s between per-entry calls.
- `fetch_bootstrap() -> dict`
- `fetch_entry_history(entry_id: int) -> dict`
- `fetch_entry_transfers(entry_id: int) -> list[dict]`
- `fetch_entry_picks(entry_id: int, gw: int) -> dict | None`: returns `None` on 404.
- `fetch_league_standings(league_id: int) -> list[dict]`: paginated; each item keeps `entry, entry_name, player_name, rank, total`.
- `players_from_bootstrap(bootstrap: dict, season_players: set[int] | None = None) -> dict[int, Player]`: pos from `element_type` 1–4; price `now_cost/10`.

**Interfaces — produces (`brief/data.py`):**
- `load_history(sb, season: str) -> list[HistoryRow]`: pages of 1000, ordered `player_id, gw`.
- `load_fixtures(sb, season: str) -> list[Fixture]`
- `load_gameweeks(sb, season: str) -> list[Gameweek]`
- `load_flags(sb, season: str) -> list[FlagRow]`: from `player_daily`, ordered `player_id, as_of_date`, paged.
- `load_tracked_league(sb) -> tuple[int, int]`: `(league_id, my_fpl_team_id)`, first row.

- [ ] **Step 1: Write the failing test.** `test_load_history_orders_pages` uses a fake client that records the `.order()` calls and returns 2 pages. Assert:
  - `order` was called with `"player_id"` and `"gw"`;
  - all rows were returned once;
  - `HistoryRow` numeric fields are floats/ints, not `Decimal`/`None`. A `None` xgc becomes 0.0.
- [ ] **Step 2: Run it.** `.venv/bin/python -m pytest tests/test_data.py -v`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** `types.py`, `fpl_api.py` and `data.py` to the signatures above. Reuse the request headers from `fpl_user_engine.py`.
- [ ] **Step 4: Run it.** Expected: PASS.
- [ ] **Step 5: Commit** `brief/types.py brief/fpl_api.py brief/data.py tests/test_data.py` with message "Weekly brief: data access layer".

---

### Task 3: Window + availability (injury rules)

**Files:**
- Create: `brief/window.py`
- Create: `brief/availability.py`
- Test: `tests/test_window.py`
- Test: `tests/test_availability.py`

**Interfaces:**
- Consumes: `Gameweek`, `Player`.
- Produces:
  - `target_gw(gameweeks: list[Gameweek], now: datetime) -> int`
  - `window_gws(target: int, last_gw: int = 38, size: int = 5) -> list[int]`
  - `parse_return_date(news: str, today: date) -> date | None`: matches "Expected back 22 Nov" (also "22 November"). It picks the next occurrence on or after `today`, so a December `today` and "3 Jan" give next year.
  - `availability(player: Player, window: list[int], gameweeks: list[Gameweek], today: date) -> list[float]`: one multiplier per window GW.
  - `can_buy(player: Player) -> bool`: `False` if `chance is not None and chance <= 50`, or if status is `i`, `s`, `u` or `n`.
  - `needs_doubt_note(player: Player) -> bool`: `True` when `chance == 75`.
  - `is_priority_sell(mults: list[float]) -> bool`: `True` when the number of GWs with a multiplier of `0.0` is ≥ 3.
- **Status `u`** (left the club) and **`n`** (on loan) give 0 for the whole window.

- [ ] **Step 1: Write the failing tests:**
  - `test_target_gw_first_future_deadline`
  - `test_window_capped_at_38`: `window_gws(36) == [36,37,38]`
  - `test_available_player_full`: `[1,1,1,1,1]`
  - `test_chance_75_target_only`: `[0.75,1,1,1,1]`
  - `test_chance_0_no_date`: `[0,0.5,1,1,1]`
  - `test_return_date_blocks_until_date`: deadlines are weekly from 1 Nov; news is "Expected back 22 Nov"; result is `[0,0,0,1,1]` (the deadline on 22 Nov itself counts as back)
  - `test_suspension_one_gw`: status `s`, empty news gives `[0,1,1,1,1]`
  - `test_suspension_length_from_news`: "Suspended for 3 matches" gives `[0,0,0,1,1]`
  - `test_cannot_buy_50`
  - `test_can_buy_75_with_note`
  - `test_priority_sell_three_out`
- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_window.py tests/test_availability.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** to the signatures above.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with message "Weekly brief: window + injury rules".

---

### Task 4: Projection model (v4, recency-weighted, set pieces)

**Files:**
- Create: `brief/set_pieces.py`
- Create: `brief/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: Task 2 types, and `availability()` from Task 3.
- Produces:
  - `SET_PIECES: dict[str, dict[str, list[str]]]`: club short name → `{"pens": [...], "fk": [...], "corners": [...]}` in taker order. Transcribe it verbatim from the memory note's table.
  - `resolve_set_pieces(players: dict[int, Player]) -> dict[int, dict[str, int]]`: player id → `{"pens": order, ...}`, with 1 = first taker. It matches `web_name` **within the club** and logs a warning for every name it cannot match.
  - `@dataclass(frozen=True) Projection(player_id: int, points: dict[int, float], captain_basis: dict[int, float], exp_minutes: dict[int, float])`. Keys are window GWs. `points` is already multiplied by availability; a blank GW is 0.0.
  - `project_all(players, history, fixtures, flags, gameweeks, window, today) -> dict[int, Projection]`

**Model rules.** Port these exactly from the memory notes:
- Points blend: 0.70 × expected points + 0.30 × regressed observed rate, × expected minutes / 90.
- Recency decay: 0.8 per GW, applied to all per-90 rates and to minutes security.
- Regression of the observed rate to the positional median: `w = min(1, mins/700)`, × 0.75 for DEF/GKP.
- Goal values: GK 10 / DEF 6 / MID 5 / FWD 4. Each xA is worth 3.
- Clean sheet: `4·e^(−λ)`, where `λ = own xGC × opp xG / league mean`.
- Attack multiplier: opponent xGC / league mean × 1.1 at home or 0.9 away, clamped to [0.6, 1.6].
- Team xG and xGC are decayed and shrunk 35% toward the mean. Team xGC per GW is the MAX of player xgc; team xG is the SUM of player xg.
- Defensive contribution: `2·clamp((cbit90 − (thr−4))/8, 0, 1)`, with thr 10 for DEF and 12 for MID/FWD.
- Bonus proxy: `max(0, (BPS90 − 16)/18)`.
- GK saves: a flat +1.15.
- Set pieces: incremental 55% for pens and 50% for dead-ball creation. A taker's regression weight is reduced.
- Minutes security skips GWs where the player was flagged (`i/s/u/n/d` on the last `player_daily` row before that GW's deadline).
- `captain_basis` is the pure expected component with no observed blend.

- [ ] **Step 1: Write the failing tests:**
  - `test_double_gw_sums_fixtures`: two fixtures in one GW give ≈ 2 × the single-fixture points.
  - `test_blank_gw_zero`
  - `test_regression_damps_low_minutes_outlier`: a 4.6 DEF with 2 goals off 1.38 xG in 300 minutes projects below a MID with steady 0.5 xGI/90 over 900 minutes.
  - `test_recency_weighting_beats_single_haul`: 23 points in GW1, then four games of 2, projects below a steady 6/game.
  - `test_injured_target_gw_zero`: chance 0 gives `points[target] == 0`.
  - `test_captain_basis_excludes_observed`: a hot streak with low xG doesn't raise `captain_basis`.
  - `test_set_piece_resolution_by_club`: two players with the same `web_name` at different clubs resolve to the right IDs.
- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_model.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** to the signatures and the rules above. Use pandas where it simplifies the aggregation.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with message "Weekly brief: projection model v4 committed to the repo".

---

### Task 5: My squad + MILP optimiser

**Files:**
- Create: `brief/squad.py`
- Create: `brief/optimise.py`
- Test: `tests/test_squad.py`
- Test: `tests/test_optimise.py`

**Interfaces:**
- Produces (`brief/squad.py`):
  - `@dataclass(frozen=True) MySquad(player_ids: list[int], selling: dict[int, float], bank: float, chips_available: list[str], last_picks_gw: int)`
  - `selling_price(purchase: float, current: float) -> float`: equals `purchase + floor((current − purchase) × 10 / 2) / 10` when the price has risen, else `current`.
  - `build_my_squad(history: dict, transfers: list[dict], picks: dict, players: dict[int, Player], gw1_prices: dict[int, float], target: int) -> MySquad`
    - Purchase price is the latest `element_in_cost / 10` from transfers, or else the GW1 `player_history.price`.
    - Bank is the latest `history.current[-1].bank / 10`.
    - Chips available: every code not used in the half containing `target`, from `history.chips[].name` and `.event`.
- Produces (`brief/optimise.py`):
  - `@dataclass(frozen=True) Solution(squad: list[int], xi: dict[int, list[int]], captain: dict[int, int], vice: dict[int, int], bench_order: dict[int, list[int]], transfers_out: list[int], transfers_in: list[int], hit_cost: int, raw_total: float)`. All dicts are keyed by window GW. `raw_total` is the window total of XI + captain extra − hit cost, with no bench and no bonus.
  - `optimise(projs: dict[int, Projection], players: dict[int, Player], squad: MySquad, window: list[int], max_transfers: int | None, free_transfers: int, utility: dict[int, float] | None = None, bench_weight: float = 0.12, buyable: set[int] | None = None) -> Solution`. `max_transfers=None` means unlimited with no hit cost (Wildcard/Free Hit). `utility` is a per-player multiplier applied only inside the objective.

**Formulation:** `scipy.optimize.milp`, binary variables:
- `s_p` (in squad), `x_{p,g}` (starting), `c_{p,g}` (captain), `v_{p,g}` (vice), and `h` (paid transfers, integer).
- **Squad:** 15 players: 2 GKP, 5 DEF, 5 MID, 3 FWD. At most 3 per club.
- **Budget:** sum of buy prices of incoming + selling prices of kept ≤ selling value of the squad + bank.
- **XI per GW:** 11 players: exactly 1 GKP, DEF 3–5, MID 2–5, FWD 1–3. `x ≤ s`.
- **Captain/vice:** exactly one each, `c ≤ x`, `v ≤ x`, `c + v ≤ 1`.
- **Transfers:** incoming = Σ s_p over players not in my squad. Incoming ≤ max_transfers; `h ≥ incoming − free_transfers`; hit cost = 4h.
- **Buyable:** players not in `buyable` cannot be incoming.
- **Objective:** maximise Σ_g Σ_p u_p · (proj·x + proj·c + bench_weight·proj·(s − x)) − 4h.

Bench order is GK first, then outfield by target-GW projection, descending.

- [ ] **Step 1: Write the failing tests:**
  - `test_selling_price_rounds_down`: (5.0, 5.3) → 5.1; (5.0, 4.8) → 4.8.
  - `test_chips_by_half`: wildcard used GW3, target 10 → `wildcard` missing; target 20 → present.
  - `test_respects_budget_and_club_limit`
  - `test_formation_valid_each_gw`
  - `test_transfer_cap_and_hit`: FT 1, max 2 → at most 2 in; when 2 are made, `hit_cost == 4`.
  - `test_unflagged_alternative_preferred`: a squad player projecting 0 is benched when a fit option exists.
  - `test_blank_gw_player_benched`
  - `test_buyable_excludes_flagged`
  - `test_zero_transfers_when_no_gain`: hit not taken when the gain is < 4.
- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_squad.py tests/test_optimise.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** to the signatures and formulation above. Use a small synthetic 40-player pool in the test fixtures (in `tests/conftest.py`) so each solve runs in under 1s.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with message "Weekly brief: squad state + MILP optimiser".

---

### Task 6: Rivals — mode, utility, guardrail, rival projections

**Files:**
- Create: `brief/rivals.py`
- Test: `tests/test_rivals.py`

**Interfaces:**
- Consumes: the `fetch_league_standings` output, rival picks dicts, `Projection`, `optimise`, `Solution`.
- Produces:
  - `@dataclass(frozen=True) Rival(entry_id: int, team_name: str, player_name: str, rank: int, total: int, picks: list[dict] | None, chip: str | None)`
  - `@dataclass(frozen=True) Mode(kind: str, my_rank: int, my_total: int, target: Rival | None, gap: int)`. `kind` is `"defend"` or `"chase"`; `gap` = target total − my total.
  - `decide_mode(standings: list[Rival], my_entry: int) -> Mode`: sort by `rank`, then by original order. Defend if I'm first in that order, targeting the next entry. Otherwise chase the entry immediately before me.
  - `ownership(rivals: list[Rival]) -> dict[int, float]`: the share of rivals (excluding me, and excluding rivals with `picks is None`) owning each player.
  - `utility_weights(mode: Mode, own: dict[int, float], bonus: float = RIVAL_BONUS) -> dict[int, float]`
    - Chase: `1 + bonus × (0 if target owns p else 1)`.
    - Defend: `1 + bonus × own[p]`.
    - `RIVAL_BONUS = 0.08`.
  - `optimise_with_guardrail(projs, players, squad, window, max_transfers, free_transfers, buyable, weights: dict[int, float], near_tie: float = NEAR_TIE_PTS) -> tuple[Solution, bool]`: the same arguments as `optimise`, plus `weights` from `utility_weights`. Solves raw (`utility=None`) and solves with utility. It returns the utility solution if `raw.raw_total − util.raw_total ≤ near_tie`, else the raw one. The bool is `True` when the mode changed the answer. `NEAR_TIE_PTS = 2.0` over the window.
  - `pick_captain(xi: list[int], projs, gw: int, mode: Mode, own_captain: dict[int, float]) -> tuple[int, int]`
    - Candidates are players within `CAPTAIN_NEAR_TIE = 0.5` of the top `captain_basis`.
    - Chase picks the candidate the target isn't captaining, else the highest share of rivals *not* captaining him; defend picks the highest `own_captain` share.
    - Ties go to the higher `captain_basis`.
    - Vice is the best remaining by `captain_basis`.
  - `rival_projection(r: Rival, projs, gw: int) -> float | None`: the sum of `points[gw] × multiplier` over picks (multiplier 0 for bench unless `chip == "bboost"`; captain 2, or 3 with `3xc`). Returns `None` when `picks is None`.

- [ ] **Step 1: Write the failing tests:**
  - `test_mode_defend_when_first`
  - `test_mode_chase_targets_directly_above`: me at rank 4, target at rank 3.
  - `test_mode_tied_points_uses_rank_order`
  - `test_guardrail_rejects_costly_differential`: a differential 3 points worse over the window is not chosen.
  - `test_guardrail_allows_near_tie_differential`: 1 point worse is chosen in chase.
  - `test_captain_defend_prefers_consensus_within_tie`
  - `test_captain_never_low_projection_differential`: a 1-point-worse differential is not captained.
  - `test_rival_projection_captain_and_bench`
  - `test_rival_without_picks_skipped`: `rival_projection` is `None` and `ownership` ignores him.
- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_rivals.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** to the signatures above.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with message "Weekly brief: rival modes with near-tie guardrail".

---

### Task 7: Chips

**Files:**
- Create: `brief/chips.py`
- Test: `tests/test_chips.py`

**Interfaces:**
- Consumes: `Solution`, `Projection`, `optimise`, `MySquad`.
- Produces:
  - `@dataclass(frozen=True) ChipAdvice(chip: str, gain_now: float, best_gw: int, gain_best: float, play_now: bool, reason: str)`
  - `CHIP_THRESHOLDS = {"3xc": 6.0, "bboost": 8.0, "freehit": 10.0, "wildcard": 12.0}`
  - `evaluate_chips(available: list[str], scenario: Solution, projs, window: list[int], freehit: Solution | None, wildcard: Solution | None) -> list[ChipAdvice]`
    - **`3xc`:** gain per GW = the captain's `points[g]`, using that GW's scenario captain.
    - **`bboost`:** gain per GW = the sum of the 4 bench players' `points[g]`.
    - **`freehit`:** `gain_now` = target-GW XI + captain of the `freehit` solution − the same for the scenario. Free Hit only evaluates the target GW, so `best_gw = target`.
    - **`wildcard`:** `gain_now` = `wildcard.raw_total − scenario.raw_total`, with `best_gw = target`.
    - `play_now` = (`best_gw == target`) and (`gain_now ≥ threshold`).
    - Chips not in `available` are omitted.
  - `solve_freehit(...) -> Solution` and `solve_wildcard(...) -> Solution`: both call `optimise(max_transfers=None)`. Free Hit uses a window of `[target]`; Wildcard uses the full window. Each is solved **once per run**.

- [ ] **Step 1: Write the failing tests:**
  - `test_tc_best_gw_is_dgw`
  - `test_bb_play_now_requires_threshold`
  - `test_used_chip_omitted`
  - `test_wildcard_gain_vs_scenario`
- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_chips.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** to the signatures above.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with message "Weekly brief: chip evaluation".

---

### Task 8: Payload + reasons

**Files:**
- Create: `brief/payload.py`
- Test: `tests/test_payload.py`

**Interfaces — produces:** `build_payload(...) -> dict` matching the schema below exactly. Task 10's TypeScript types mirror it. `version: 1`.

```
{ version, season, gw, generated_at (ISO), window: int[],
  mode: { kind, my_rank, my_total, gap, target: {entry_id, team_name, player_name, rank, total} | null },
  assumption: "Assumes no transfers made since the GW{n} deadline.",
  rivals: [{ entry_id, team_name, player_name, rank, total, projected_points: number|null, captain: string|null, is_target: bool }],
  scenarios: { "<ft>_<hits>": {
      transfers: [{ out: PlayerRef, in: PlayerRef, gain_window: number, reason: string }],
      hit_cost: int, net_gain_window: number, hit_note: string|null,
      priority_sells: [{ player: PlayerRef, reason: string }],
      formation: "3-4-3", xi: PlayerSlot[], bench: PlayerSlot[],
      captain: PlayerSlot & {reason}, vice: PlayerSlot,
      projected_points: number, mode_changed_answer: bool,
      chips: ChipAdvice[] } },
  inputs: { bank, squad_ids, selling, flagged_ids } }
PlayerRef  = { id, name, team, pos, price }
PlayerSlot = PlayerRef & { proj: number, flag: {status, chance, news} | null }
```

**Rules:**
- Numbers are rounded to 1 decimal.
- `projected_points` = target-GW XI points + captain's points again (raw).
- **Transfer pairing:** pair outs and ins by position, ins sorted by `gain_window` descending.
- **`gain_window`:** the in-player's window points minus the out-player's.
- **`hit_note`:** set only when `hits == 0`. If the same FT with hits 4 has `net_gain_window` > the hits-0 scenario's, it reads "A -4 for {out}→{in} gains +{g} over 5 GWs, net +{g-4}."
- **Reason templates.** Each must be true of the numbers:
  - **Transfer:** "{in} projects {x} over the next 5 GWs vs {y} for {out}". Then append each that applies:
    - " · {out} {flag text}" when out is flagged;
    - " · 75% doubtful" when in is at 75%;
    - " · owned by {k} of {n} rivals" in defend;
    - " · {target} doesn't own him" in chase, only if the target really doesn't own him.
  - **Captain:** "{name} projects {p} (next best {q}: {name2})". Then append " · {k}/{n} rivals likely captain him" or " · {target} isn't captaining him" when true.

- [ ] **Step 1: Write the failing tests:**
  - `test_payload_has_15_scenarios`
  - `test_hit_note_only_when_hit_pays`
  - `test_chase_reason_never_claims_false_differential`: when the target owns the in-player, the text contains no "doesn't own".
  - `test_doubt_note_on_75_buy`
  - `test_payload_json_serialisable`: `json.dumps` succeeds.
- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_payload.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** to the schema and rules above.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with message "Weekly brief: payload + reason templates".

---

### Task 9: Engine, schedule, health check

**Files:**
- Create: `fpl_brief_engine.py`
- Create: `launchd/com.fplsniper.brief.plist`
- Modify: `health_check.py:49-53`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `main() -> None`
  - `run(sb, now: datetime) -> dict`: returns the payload; `main` inserts it.
  - The ops helpers `wait_for_supabase`, `assert_schema`, `log_pipeline_run`, `ping_healthcheck`, copied from `fpl_user_engine.py` (deliberate duplication, per CLAUDE.md), with:
    - engine name `fpl_brief_engine`;
    - env var `HEALTHCHECK_URL_BRIEF`;
    - `SCHEMA_CHECKS = [("weekly_brief","payload","0014_weekly_brief.sql"), ("players_master","last_seen_season","0013_players_master_season_stamp.sql"), ("pipeline_runs","engine","0007_player_daily_and_pipeline_runs.sql")]`.

**`run` flow:**
1. Fetch bootstrap. Exit early with `skipped_offseason` if every GW is finished.
2. Work out the season (the same rule as `fpl_engine.determine_season`), the target GW and the window.
3. Load the Supabase data.
4. Build players from bootstrap, restricted to `last_seen_season = season`, with live flags.
5. Project everyone.
6. Fetch my history, transfers and the latest available picks: try `target − 1` and step down until one returns.
7. Fetch standings and each rival's latest picks the same way.
8. Decide the mode.
9. Solve Free Hit and Wildcard once.
10. For each of the 15 scenarios, call `optimise_with_guardrail`, then `pick_captain` per GW, then `evaluate_chips`.
11. Build the payload.
12. Insert `{season, gw, mode, payload}`.
13. Log `pipeline_runs` with `rows_written=1` and a detail like `"mode=chase target=Budi 15 scenarios 42s"`.

A failure anywhere logs `status="failed"` with the exception text, pings `/fail`, and exits 1.

**Plist:** copy `com.fplsniper.user.plist`. Set label `com.fplsniper.brief` and program `fpl_brief_engine.py`. Use `StartCalendarInterval` entries for:
- daily 09:30 (no Weekday key);
- Weekday 6, 10:30.

Logs go to `~/Library/Logs/fplsniper/cron.log`.

**`health_check.py`:** add `"fpl_brief_engine": 8` to `EXPECTED_RUNS_PER_WEEK` (7 daily + Sat) and update the comment.

- [ ] **Step 1: Write the failing test.** `test_run_end_to_end_with_fakes` monkeypatches the `brief.fpl_api` functions and the `brief.data` loaders with a 40-player synthetic world. Assert that the payload has 15 scenarios, `mode.kind == "chase"` for a rank-3 fixture, and that every XI has 11 players.
- [ ] **Step 2: Run it.** `.venv/bin/python -m pytest tests/test_engine.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `fpl_brief_engine.py`, the plist and the `health_check.py` change.
- [ ] **Step 4: Run the whole suite.** `.venv/bin/python -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Run it live.** `.venv/bin/python fpl_brief_engine.py`. Expected:
  - it exits 0 in under 3 minutes;
  - the log ends with the summary line;
  - `select gw, mode, generated_at from weekly_brief order by generated_at desc limit 1` returns the new row.

  Sanity-check against reality and show the user the GW target and mode:
  - the squad matches the user's actual team;
  - injured players are flagged.
- [ ] **Step 6: Install the agent.**
  - `cp launchd/com.fplsniper.brief.plist ~/Library/LaunchAgents/`
  - `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fplsniper.brief.plist`
  - `launchctl list | grep fplsniper.brief` should show the agent.
- [ ] **Step 7: Commit** with message "Weekly brief: engine + launchd schedule + heartbeat".

---

### Task 10: PWA — the Brief screen, delete the tabs

**Files:**
- Create: `web/src/brief/types.ts`
- Create: `web/src/brief/useBrief.ts`
- Create: `web/src/brief/prefs.ts`
- Create: `web/src/brief/Brief.tsx`
- Create: `web/src/brief/cards.tsx`
- Modify: `web/src/components/Shell.tsx`
- Modify: `web/src/components/FreshnessBadge.tsx:6`
- Modify: `web/src/types/db.ts`
- Modify: `web/src/App.css`
- Delete: `web/src/tabs/` (all files)
- Delete: `web/src/components/PlayerDetail.tsx`
- Delete: `web/src/components/Sparkline.tsx`

**Interfaces:**
- Consumes: the Task 8 payload schema.
- Produces:
  - `types.ts`: `BriefPayload`, `Scenario`, `PlayerRef`, `PlayerSlot`, `ChipAdvice`, `RivalRow`, `Mode`, mirroring the schema field for field.
  - `useBrief(): { status: 'loading'|'error'|'empty'|'ready', brief?: BriefPayload, generatedAt?: string }`: reads `supabase.from('weekly_brief').select('payload, generated_at').order('generated_at', {ascending:false}).limit(1)` through the existing `useSupabaseQuery`.
  - `prefs.ts`: `loadPrefs(): {ft: 1|2|3|4|5, hits: 0|4|8}` and `savePrefs(p)`. Both use `localStorage` key `fplsniper.brief.prefs`, every access is wrapped in try/catch, and the default is `{ft:1, hits:0}`.
  - `Brief.tsx`:
    - **Header strip:** the FT segmented control 1–5 and the hits control (None / −4 / −8). Next to them, a mode badge: "DEFEND · 1st, +{gap} over {target}" or "CHASE · {rank}th, {gap} behind {target}". Then the `assumption` text, small.
    - **Five cards, in order:** Transfers → Best XI → Captain → You vs rivals → Chips.
    - **Each card** shows its answer, its one-line reason, and tap-to-expand detail (all transfers with gains, full XI with projections and flags, the top-5 captain options, every rival row, every chip).
  - `cards.tsx`: one component per card, named `TransfersCard`, `XiCard`, `CaptainCard`, `RivalsCard`, `ChipsCard`.
  - `Shell.tsx`: header (`FreshnessBadge`, sign out) + `OfflineBanner` + `<Brief />`. No tab bar.
  - `FreshnessBadge`: append `'fpl_brief_engine'` to `ENGINES`.
  - `db.ts`: remove the types that only the deleted tabs used. Keep `PipelineRun`.
  - CSS: remove the tab-bar and tab-only styles; add card styles in the existing app's colours and fonts. The layout must fit 375px width with no horizontal scroll.

- [ ] **Step 1: Delete** the tabs, `PlayerDetail` and `Sparkline`. Create the new files to the interfaces above.
- [ ] **Step 2: Build and lint.** `cd web && npm run build && npm run lint`. Expected: both succeed with no unused-import errors.
- [ ] **Step 3: Verify in the browser.**
  - Open `http://localhost:5173` (the `com.fplsniper.web` agent serves it; no restart needed).
  - Sign in if prompted. The user does this; don't type credentials.
  - Check:
    - the five cards render;
    - changing FT and hits changes the transfers instantly;
    - a reload keeps the selection;
    - at 375px there is no horizontal scroll;
    - the console has no errors.
  - Take a screenshot for the user.
- [ ] **Step 4: Commit** with message "PWA: replace five tabs with the one-screen weekly brief".

---

### Task 11: Docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `docs/TODOS.md`

- [ ] **Step 1: Update `CLAUDE.md`:**
  - **Phase table:** add a row "3D. Weekly brief ✅".
  - **Pipelines:** add a third-engine section for `fpl_brief_engine.py` (flow and outputs).
  - **Deployment:** add `com.fplsniper.brief` (daily 09:30 + Sat 10:30).
  - **Schema:** add `weekly_brief`.
  - **Migrations:** add 0014.
  - **PWA section:** one screen, five cards.
  - **Files tree:** add `brief/` and `tests/`.
  - **Decision #16:** the model was moved into the repo after three scratchpad losses; rival data is fetched live; the near-tie guardrail; the old views are kept but unused.
- [ ] **Step 2: Update `README.md`.** Add the run command, the plist install, `HEALTHCHECK_URL_BRIEF`, and `pytest`.
- [ ] **Step 3: Update `docs/TODOS.md`.** Add: backtest the model; season-long chip planning; queued-transfer awareness.
- [ ] **Step 4: Commit** with message "Docs: weekly brief engine + one-screen PWA".
