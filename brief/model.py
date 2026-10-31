"""GW-ahead points projection model (v4): recency-weighted, xG-based fixtures, set pieces.

Per fixture a player projects

    appearance + 0.70 x expected_core + 0.30 x (exp_min/90) x regressed_observed90

where `expected_core` is the bottom-up expected points *excluding* appearance
points, and `regressed_observed90` is his decayed points-per-90 *excluding*
appearance points, regressed to the positional median. Appearance points sit
outside the blend so they are counted once, in full, from expected minutes.
Spec: memory notes fpl-projection-model-v3 + fpl-use-recency-weighted.
"""
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from brief.availability import availability
from brief.set_pieces import is_first_taker, resolve_set_pieces, set_piece_extras
from brief.types import Fixture, FlagRow, Gameweek, HistoryRow, Player

# --- Blend and recency (memory notes) ---
EXPECTED_WEIGHT = 0.70   # share of expected points in the blend (note v3)
OBSERVED_WEIGHT = 0.30   # share of regressed observed rate in the blend (note v3)
DECAY = 0.8              # per-GW recency decay, most recent GW = 1.0 (note recency-weighted)

# --- Regression of the observed rate (note v3 + controller resolution) ---
REGRESSION_MINUTES = 700          # w = min(1, mins / 700) (note v3)
TAKER_REGRESSION_MINUTES = 500    # first set-piece takers regress less (controller resolution)
DEFENSIVE_REGRESSION_FACTOR = 0.75  # w x 0.75 for DEF/GKP (note v3)
MEDIAN_MIN_MINUTES = 270          # players counted in the positional median (controller resolution)

# --- Expected points (note v3 / v4 + controller resolution) ---
GOAL_VALUE = {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}  # note v3
ASSIST_VALUE = 3                                        # note v3
CS_POINTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}    # FPL scoring (controller resolution)
CONCEDE_PENALTY = 0.5          # -1 per 2 conceded -> -0.5 x lambda, GKP/DEF (controller resolution)
APPEARANCE_FULL = 2            # 2 points for 60+ minutes (controller resolution)
APPEARANCE_MINUTES = 60        # minutes for full appearance / clean-sheet eligibility
DEFCON_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12}    # note v3 2026-10-10 rebuild
DEFCON_POINTS = 2              # note v3: 2 x clamp((cbit90 - (thr-4))/8, 0, 1)
BONUS_BPS_BASE = 16            # note v3: max(0, (BPS90 - 16)/18)
BONUS_BPS_SCALE = 18
GK_SAVES_POINTS = 1.15         # flat saves value; player_history has no saves column (note v3)
MAX_MINUTES = 90               # expected minutes cap per fixture (controller resolution)

# --- Team strength (note v4) ---
TEAM_SHRINK = 0.35             # shrink decayed team xG/xGC 35% to the league mean
HOME_BOOST = 1.1               # attack multiplier at home
AWAY_BOOST = 0.9               # attack multiplier away
ATTACK_MULT_MIN = 0.6
ATTACK_MULT_MAX = 1.6

FLAG_STATUSES = frozenset("isund")  # GWs flagged with these are skipped in minutes security (note v4)


@dataclass(frozen=True)
class Projection:
    """A player's projected points per window GW (already x availability)."""
    player_id: int
    points: dict[int, float]
    captain_basis: dict[int, float]
    exp_minutes: dict[int, float]


@dataclass(frozen=True)
class _Rates:
    """A player's decayed per-90 inputs and minutes figures."""
    xg90: float
    xa90: float
    bps90: float
    cbit90: float
    observed90: float  # decayed points per 90, excluding appearance points
    raw_minutes: int
    exp_minutes: float  # per fixture


@dataclass(frozen=True)
class _TeamStrength:
    """Decayed, shrunk per-fixture team xG/xGC and their league means."""
    xg: dict[int, float]
    xgc: dict[int, float]
    mean_xg: float
    mean_xgc: float


def _weight(gw: int, last_gw: int) -> float:
    """Recency weight: 1.0 for the most recent completed GW, x0.8 per GW before it."""
    return DECAY ** (last_gw - gw)


def _decayed_mean(values: dict[int, float], last_gw: int) -> float | None:
    """Decay-weighted mean of {gw: value}, or None when empty."""
    total_w = sum(_weight(gw, last_gw) for gw in values)
    if total_w == 0:
        return None
    return sum(_weight(gw, last_gw) * v for gw, v in values.items()) / total_w


def _appearance_played(minutes: int, n_fixtures: int) -> float:
    """Appearance points actually earned in a GW, splitting minutes evenly across fixtures."""
    per_fixture = minutes / n_fixtures
    if per_fixture >= APPEARANCE_MINUTES:
        return APPEARANCE_FULL * n_fixtures
    return (APPEARANCE_FULL / 2) * n_fixtures if per_fixture > 0 else 0.0


def _team_strength(
    players: dict[int, Player], history: list[HistoryRow],
    fix_counts: dict[tuple[int, int], int], last_gw: int,
) -> _TeamStrength:
    """Team xG (SUM of player xg) and xGC (MAX of player xgc) per fixture, decayed and shrunk."""
    xg_sum: dict[tuple[int, int], float] = defaultdict(float)
    xgc_max: dict[tuple[int, int], float] = defaultdict(float)
    for row in history:
        player = players.get(row.player_id)
        if player is None:
            continue
        key = (player.team_id, row.gw)
        xg_sum[key] += row.xg
        xgc_max[key] = max(xgc_max[key], row.xgc)
    raw_xg: dict[int, float] = {}
    raw_xgc: dict[int, float] = {}
    for team in {t for t, _ in xg_sum}:
        gws = [gw for (t, gw) in xg_sum if t == team and fix_counts.get((t, gw), 0) > 0]
        raw_xg[team] = _decayed_mean({gw: xg_sum[(team, gw)] / fix_counts[(team, gw)] for gw in gws}, last_gw) or 0.0
        raw_xgc[team] = _decayed_mean({gw: xgc_max[(team, gw)] / fix_counts[(team, gw)] for gw in gws}, last_gw) or 0.0
    mean_xg = statistics.fmean(raw_xg.values()) if raw_xg else 0.0
    mean_xgc = statistics.fmean(raw_xgc.values()) if raw_xgc else 0.0
    return _TeamStrength(
        xg={t: (1 - TEAM_SHRINK) * v + TEAM_SHRINK * mean_xg for t, v in raw_xg.items()},
        xgc={t: (1 - TEAM_SHRINK) * v + TEAM_SHRINK * mean_xgc for t, v in raw_xgc.items()},
        mean_xg=mean_xg,
        mean_xgc=mean_xgc,
    )


def _flagged_gws(
    flags: list[FlagRow], gameweeks: list[Gameweek], gws: list[int]
) -> set[int]:
    """GWs (of `gws`) whose last flag row on or before the deadline date is i/s/u/n/d."""
    deadlines = {g.gw: g.deadline.date() for g in gameweeks}
    ordered = sorted(flags, key=lambda f: f.as_of_date)
    flagged = set()
    for gw in gws:
        if gw not in deadlines:
            continue
        before = [f for f in ordered if f.as_of_date <= deadlines[gw]]
        if before and before[-1].status in FLAG_STATUSES:
            flagged.add(gw)
    return flagged


def _expected_minutes(
    rows: dict[int, HistoryRow], team_gws: list[int], flagged: set[int],
    fix_counts: dict[int, int], last_gw: int,
) -> float:
    """Decayed average minutes per fixture over unflagged team-fixture GWs, capped at 90."""
    if not rows:
        return 0.0
    first = min(rows)
    sample = {
        gw: (rows[gw].minutes if gw in rows else 0) / fix_counts[gw]
        for gw in team_gws if first <= gw <= last_gw and gw not in flagged
    }
    return min(MAX_MINUTES, _decayed_mean(sample, last_gw) or 0.0)


def _per90(rows: list[HistoryRow], values: list[float], last_gw: int) -> float:
    """Decayed sum of a stat over decayed sum of minutes, x90 (0 with no minutes)."""
    minutes = sum(_weight(r.gw, last_gw) * r.minutes for r in rows)
    if minutes == 0:
        return 0.0
    return 90 * sum(_weight(r.gw, last_gw) * v for r, v in zip(rows, values)) / minutes


def _player_rates(
    rows: list[HistoryRow], team_gws: list[int], flagged: set[int],
    fix_counts: dict[int, int], last_gw: int,
) -> _Rates:
    """Decayed per-90 inputs, raw minutes and expected minutes for one player."""
    observed = [r.total_points - _appearance_played(r.minutes, fix_counts.get(r.gw, 1)) for r in rows]
    return _Rates(
        xg90=_per90(rows, [r.xg for r in rows], last_gw),
        xa90=_per90(rows, [r.xa for r in rows], last_gw),
        bps90=_per90(rows, [r.bps for r in rows], last_gw),
        cbit90=_per90(rows, [r.cbit for r in rows], last_gw),
        observed90=_per90(rows, observed, last_gw),
        raw_minutes=sum(r.minutes for r in rows),
        exp_minutes=_expected_minutes({r.gw: r for r in rows}, team_gws, flagged, fix_counts, last_gw),
    )


def _positional_medians(players: dict[int, Player], rates: dict[int, _Rates]) -> dict[str, float]:
    """Median observed90 per position over players with at least 270 raw minutes."""
    by_pos: dict[str, list[float]] = defaultdict(list)
    for pid, r in rates.items():
        if r.raw_minutes >= MEDIAN_MIN_MINUTES:
            by_pos[players[pid].pos].append(r.observed90)
    return {pos: statistics.median(vals) for pos, vals in by_pos.items()}


def _regressed_observed(pos: str, rates: _Rates, median: float, taker: bool) -> float:
    """Observed rate shrunk to the positional median by the minutes-based weight."""
    denom = TAKER_REGRESSION_MINUTES if taker else REGRESSION_MINUTES
    w = min(1.0, rates.raw_minutes / denom)
    if pos in ("DEF", "GKP"):
        w *= DEFENSIVE_REGRESSION_FACTOR
    return w * rates.observed90 + (1 - w) * median


def _appearance(exp_min: float) -> float:
    """Expected appearance points for one fixture."""
    return APPEARANCE_FULL * min(exp_min, APPEARANCE_MINUTES) / APPEARANCE_MINUTES


def _expected_core(
    pos: str, rates: _Rates, extras: tuple[float, float], attack_mult: float, lam: float,
) -> float:
    """Expected points for one fixture excluding appearance points."""
    scale = rates.exp_minutes / 90
    xg90, xa90 = rates.xg90 + extras[0], rates.xa90 + extras[1]
    per90 = (xg90 * GOAL_VALUE[pos] + xa90 * ASSIST_VALUE) * attack_mult
    per90 += max(0.0, (rates.bps90 - BONUS_BPS_BASE) / BONUS_BPS_SCALE)
    if pos in DEFCON_THRESHOLD:
        thr = DEFCON_THRESHOLD[pos]
        per90 += DEFCON_POINTS * min(1.0, max(0.0, (rates.cbit90 - (thr - 4)) / 8))
    if pos in ("GKP", "DEF"):
        per90 -= CONCEDE_PENALTY * lam
    if pos == "GKP":
        per90 += GK_SAVES_POINTS
    clean_sheet = CS_POINTS[pos] * math.exp(-lam) * min(1.0, rates.exp_minutes / APPEARANCE_MINUTES)
    return per90 * scale + clean_sheet


def _fixture_context(fixture: Fixture, teams: _TeamStrength) -> tuple[float, float]:
    """Return (attack multiplier, clean-sheet lambda) for one side of a fixture."""
    opp_xgc = teams.xgc.get(fixture.opp_id, teams.mean_xgc)
    opp_xg = teams.xg.get(fixture.opp_id, teams.mean_xg)
    own_xgc = teams.xgc.get(fixture.team_id, teams.mean_xgc)
    venue = HOME_BOOST if fixture.home else AWAY_BOOST
    attack = opp_xgc / teams.mean_xgc * venue if teams.mean_xgc else 1.0
    attack = min(ATTACK_MULT_MAX, max(ATTACK_MULT_MIN, attack))
    lam = own_xgc * opp_xg / teams.mean_xg if teams.mean_xg else own_xgc
    return attack, lam


def _project_player(
    player: Player, rates: _Rates, observed: float, extras: tuple[float, float],
    fixtures_by_gw: dict[int, list[Fixture]], teams: _TeamStrength,
    window: list[int], avail: list[float],
) -> Projection:
    """Sum blended and pure-expected points over each window GW's fixtures."""
    points, captain, minutes = {}, {}, {}
    for gw, mult in zip(window, avail):
        pts = cap = 0.0
        fixtures = fixtures_by_gw.get(gw, [])
        for fixture in fixtures:
            attack, lam = _fixture_context(fixture, teams)
            core = _expected_core(player.pos, rates, extras, attack, lam)
            appearance = _appearance(rates.exp_minutes)
            pts += appearance + EXPECTED_WEIGHT * core + OBSERVED_WEIGHT * observed * rates.exp_minutes / 90
            cap += appearance + core
        points[gw] = pts * mult
        captain[gw] = cap * mult
        minutes[gw] = rates.exp_minutes * len(fixtures) * mult
    return Projection(player.id, points, captain, minutes)


def project_all(
    players: dict[int, Player], history: list[HistoryRow], fixtures: list[Fixture],
    flags: list[FlagRow], gameweeks: list[Gameweek], window: list[int], today: date,
) -> dict[int, Projection]:
    """Project every player's points for each GW in `window`."""
    past = [r for r in history if r.gw < window[0]]
    last_gw = max((r.gw for r in past), default=0)
    fix_counts: dict[tuple[int, int], int] = defaultdict(int)
    for f in fixtures:
        fix_counts[(f.team_id, f.gw)] += 1
    teams = _team_strength(players, past, fix_counts, last_gw)

    rows_by_player: dict[int, list[HistoryRow]] = defaultdict(list)
    for row in past:
        rows_by_player[row.player_id].append(row)
    flags_by_player: dict[int, list[FlagRow]] = defaultdict(list)
    for flag in flags:
        flags_by_player[flag.player_id].append(flag)

    rates: dict[int, _Rates] = {}
    for pid, player in players.items():
        team_counts = {gw: n for (t, gw), n in fix_counts.items() if t == player.team_id}
        team_gws = sorted(gw for gw in team_counts if gw <= last_gw)
        flagged = _flagged_gws(flags_by_player[pid], gameweeks, team_gws)
        rates[pid] = _player_rates(rows_by_player[pid], team_gws, flagged, team_counts, last_gw)
    medians = _positional_medians(players, rates)
    duties = resolve_set_pieces(players)

    projections: dict[int, Projection] = {}
    for pid, player in players.items():
        own = duties.get(pid, {})
        observed = _regressed_observed(player.pos, rates[pid], medians.get(player.pos, 0.0), is_first_taker(own))
        fixtures_by_gw: dict[int, list[Fixture]] = defaultdict(list)
        for f in fixtures:
            if f.team_id == player.team_id:
                fixtures_by_gw[f.gw].append(f)
        projections[pid] = _project_player(
            player, rates[pid], observed, set_piece_extras(own), fixtures_by_gw, teams,
            window, availability(player, window, gameweeks, today),
        )
    return projections
