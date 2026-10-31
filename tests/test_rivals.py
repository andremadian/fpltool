"""Tests for brief.rivals: mode, utility weights, near-tie guardrail, captaincy, rival projections."""
from brief.model import Projection
from brief.rivals import (
    Mode, Rival, captain_share, decide_mode, optimise_with_guardrail, ownership,
    pick_captain, rival_projection, utility_weights,
)
from tests.conftest import WINDOW


def _pick(pid: int, pos: int, mult: int = 1, cap: bool = False) -> dict:
    """One FPL picks item."""
    return {"element": pid, "position": pos, "multiplier": mult, "is_captain": cap, "is_vice_captain": False}


def _rival(eid: int, rank: int, total: int, picks=None, chip=None) -> Rival:
    """Build a Rival."""
    return Rival(eid, f"T{eid}", f"N{eid}", rank, total, picks, chip)


def _proj(pid: int, pts: float) -> Projection:
    """Single-GW projection (GW 10) with captain basis = points."""
    return Projection(pid, {10: pts}, {10: pts}, {10: 90.0})


def test_mode_defend_when_first():
    """Leader defends against the entry directly below."""
    s = [_rival(1, 1, 100), _rival(2, 2, 90), _rival(3, 3, 80)]
    m = decide_mode(s, 1)
    assert (m.kind, m.target.entry_id, m.gap) == ("defend", 2, -10)


def test_mode_defend_alone():
    """Only entry in the league: defend with no target."""
    m = decide_mode([_rival(1, 1, 100)], 1)
    assert (m.kind, m.target, m.gap) == ("defend", None, 0)


def test_mode_chase_targets_directly_above():
    """Rank 4 chases rank 3, not rank 1."""
    s = [_rival(i, i, 100 - 10 * i) for i in (1, 2, 3, 4)]
    m = decide_mode(s, 4)
    assert (m.kind, m.target.entry_id, m.gap, m.my_rank) == ("chase", 3, 10, 4)


def test_mode_tied_points_uses_rank_order():
    """Equal totals: standings rank decides, then list order for equal ranks."""
    s = [_rival(5, 1, 100), _rival(1, 2, 100), _rival(7, 2, 100)]
    assert decide_mode(s, 5).kind == "defend"
    assert decide_mode(s, 1).target.entry_id == 5
    m = decide_mode(s, 7)  # same rank as entry 1 but listed after it
    assert (m.kind, m.target.entry_id, m.gap) == ("chase", 1, 0)


def test_ownership_and_captain_share_exclude_me_and_no_picks():
    """Shares ignore my entry and rivals without picks."""
    s = [
        _rival(1, 1, 100, [_pick(9, 1, 2, True)]),
        _rival(2, 2, 90, [_pick(9, 1), _pick(8, 2, 2, True)]),
        _rival(3, 3, 80, [_pick(8, 1, 2, True)]),
        _rival(4, 4, 70, None),
    ]
    assert ownership(s, 1) == {9: 0.5, 8: 1.0}
    assert captain_share(s, 1) == {8: 1.0}


def test_utility_weights_modes():
    """Chase rewards players the target lacks; defend rewards widely owned ones."""
    target = _rival(2, 2, 90, [_pick(9, 1)])
    own = {9: 1.0, 8: 0.5}
    chase = utility_weights(Mode("chase", 3, 80, target, 10), own, 0.1, player_ids={7})
    assert chase == {9: 1.0, 8: 1.1, 7: 1.1}
    defend = utility_weights(Mode("defend", 1, 100, target, -10), own, 0.1)
    assert defend == {9: 1.1, 8: 1.05}
    no_picks = utility_weights(Mode("chase", 3, 80, _rival(2, 2, 90), 10), own, 0.1)
    assert no_picks == {9: 1.0, 8: 1.05}


def _swap_world(projs, make_proj, b_pts_per_gw: float):
    """Candidate A (id 11) at 5.0/GW; differential B (id 12) at `b_pts_per_gw`/GW."""
    projs = dict(projs)
    projs[11] = make_proj(11, 5.0)
    projs[12] = make_proj(12, b_pts_per_gw)
    return projs


def _solve(projs, players, my_squad, weights):
    """One-transfer guardrail solve with the default near-tie."""
    return optimise_with_guardrail(projs, players, my_squad, WINDOW, 1, 1, None, weights)


def test_guardrail_rejects_costly_differential(players, projs, my_squad, make_proj):
    """A differential 3 points worse over the window is not chosen, even if utility prefers him."""
    p = _swap_world(projs, make_proj, 4.4)  # 0.6/GW x 5 = 3.0 worse
    sol, changed = _solve(p, players, my_squad, {12: 1.5})
    assert 11 in sol.squad and 12 not in sol.squad
    assert changed is False


def test_guardrail_allows_near_tie_differential(players, projs, my_squad, make_proj):
    """A differential 1 point worse over the window is chosen."""
    p = _swap_world(projs, make_proj, 4.8)  # 0.2/GW x 5 = 1.0 worse
    sol, changed = _solve(p, players, my_squad, {12: 1.05})
    assert 12 in sol.squad and 11 not in sol.squad
    assert changed is True
    assert sol.raw_total > 0


def test_guardrail_neutral_weights_solve_once(players, projs, my_squad):
    """All-1.0 weights return the raw solution, unchanged."""
    _, changed = _solve(projs, players, my_squad, {1: 1.0})
    assert changed is False


def test_captain_defend_prefers_consensus_within_tie():
    """Defend: among near-equal candidates, take the most captained."""
    projs = {1: _proj(1, 8.0), 2: _proj(2, 7.7), 3: _proj(3, 5.0)}
    mode = Mode("defend", 1, 100, _rival(2, 2, 90), -10)
    assert pick_captain([1, 2, 3], projs, 10, mode, {2: 0.6, 1: 0.1}) == (2, 1)


def test_captain_never_low_projection_differential():
    """A differential 1 point worse (outside the 0.5 window) is never captained."""
    projs = {1: _proj(1, 8.0), 2: _proj(2, 7.0)}
    target = _rival(9, 2, 90, [_pick(1, 1, 2, True)])
    mode = Mode("chase", 3, 80, target, 10)
    assert pick_captain([1, 2], projs, 10, mode, {1: 0.9, 2: 0.0}) == (1, 2)


def test_captain_chase_avoids_target_captain():
    """Chase: within the tie window, pick someone the target isn't captaining."""
    projs = {1: _proj(1, 8.0), 2: _proj(2, 7.8), 3: _proj(3, 7.9)}
    target = _rival(9, 2, 90, [_pick(1, 1, 2, True)])
    mode = Mode("chase", 3, 80, target, 10)
    cap, vice = pick_captain([1, 2, 3], projs, 10, mode, {1: 0.5, 2: 0.4, 3: 0.1})
    assert (cap, vice) == (3, 1)
    # target captains every candidate -> lowest own_captain share
    only = {1: _proj(1, 8.0), 2: _proj(2, 7.0)}
    assert pick_captain([1, 2], only, 10, mode, {1: 0.5}) == (1, 2)


def test_rival_projection_captain_and_bench():
    """Captain doubles, bench scores nothing; bboost counts the bench; 3xc triples."""
    projs = {1: _proj(1, 6.0), 2: _proj(2, 4.0), 3: _proj(3, 2.0)}
    picks = [_pick(1, 1, 2, True), _pick(2, 2), _pick(3, 12, 0)]
    assert rival_projection(_rival(1, 1, 0, picks), projs, 10) == 16.0
    bb = [_pick(1, 1, 2, True), _pick(2, 2), _pick(3, 12, 1)]
    assert rival_projection(_rival(1, 1, 0, bb, "bboost"), projs, 10) == 18.0
    tc = [_pick(1, 1, 3, True), _pick(2, 2), _pick(3, 12, 0)]
    assert rival_projection(_rival(1, 1, 0, tc, "3xc"), projs, 10) == 22.0
    # no multiplier field: derived from position / captain / chip
    raw = [{"element": 1, "position": 1, "is_captain": True}, {"element": 3, "position": 13}]
    assert rival_projection(_rival(1, 1, 0, raw, "3xc"), projs, 10) == 18.0
    assert rival_projection(_rival(1, 1, 0, [_pick(99, 1)]), projs, 10) == 0.0


def test_rival_without_picks_skipped():
    """No picks: projection is None and ownership ignores the rival."""
    r = _rival(2, 2, 90, None)
    assert rival_projection(r, {}, 10) is None
    assert ownership([_rival(3, 3, 80, [_pick(5, 1)]), r], 1) == {5: 1.0}
