"""Tests for the MILP squad / XI / captain optimiser."""
from collections import Counter
from dataclasses import replace

from brief.optimise import Solution, optimise

XI_RANGES = {"GKP": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
SQUAD_QUOTA = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}


def _assert_legal(sol: Solution, players: dict, window: list[int]) -> None:
    """Assert squad shape, club limit, and per-GW XI/captain/vice/bench legality."""
    assert len(sol.squad) == 15
    assert Counter(players[p].pos for p in sol.squad) == SQUAD_QUOTA
    assert max(Counter(players[p].team_id for p in sol.squad).values()) <= 3
    for g in window:
        xi = sol.xi[g]
        assert len(xi) == 11 and set(xi) <= set(sol.squad)
        counts = Counter(players[p].pos for p in xi)
        for pos, (lo, hi) in XI_RANGES.items():
            assert lo <= counts[pos] <= hi
        assert sol.captain[g] in xi
        assert sol.vice[g] in xi and sol.vice[g] != sol.captain[g]
        bench = sol.bench_order[g]
        assert sorted(bench) == sorted(set(sol.squad) - set(xi))
        assert players[bench[0]].pos == "GKP"


def test_respects_budget_and_club_limit(players, projs, my_squad, window, make_proj) -> None:
    """An unaffordable star stays out; a stacked club is capped at 3."""
    players[40] = replace(players[40], price=15.0)
    projs[40] = make_proj(40, 20.0)
    for pid in (17, 25):  # club 2, where the squad already holds 3
        projs[pid] = make_proj(pid, 15.0)
    sol = optimise(projs, players, my_squad, window, max_transfers=None, free_transfers=1)
    _assert_legal(sol, players, window)
    assert 40 not in sol.squad
    assert {17, 25} <= set(sol.squad)
    cost = sum(my_squad.selling[p] if p in my_squad.player_ids else players[p].price
               for p in sol.squad)
    assert cost <= sum(my_squad.selling.values()) + my_squad.bank + 1e-9
    assert sol.hit_cost == 0


def test_formation_valid_each_gw(players, projs, my_squad, window, make_proj) -> None:
    """Every GW gets a legal XI, captain, vice and GK-first bench; solves are deterministic."""
    projs[11] = make_proj(11, {10: 9.0, 11: 0.0, 12: 9.0, 13: 9.0, 14: 9.0})
    first = optimise(projs, players, my_squad, window, max_transfers=None, free_transfers=1)
    _assert_legal(first, players, window)
    for g in window:
        outfield = first.bench_order[g][1:]
        pts = [projs[p].points[g] for p in outfield]
        assert pts == sorted(pts, reverse=True)
    again = optimise(projs, players, my_squad, window, max_transfers=None, free_transfers=1)
    assert again == first


def test_transfer_cap_and_hit(players, projs, my_squad, window, make_proj) -> None:
    """FT 1, max 2: three big upgrades exist, exactly two are made for one -4 hit."""
    for pid in (23, 24, 34):
        projs[pid] = make_proj(pid, 12.0)
    sol = optimise(projs, players, my_squad, window, max_transfers=2, free_transfers=1)
    _assert_legal(sol, players, window)
    assert len(sol.transfers_in) == 2 and len(sol.transfers_out) == 2
    assert sol.hit_cost == 4
    xi_pts = sum(projs[p].points[g] for g in window for p in sol.xi[g])
    cap_pts = sum(projs[sol.captain[g]].points[g] for g in window)
    assert abs(sol.raw_total - (xi_pts + cap_pts - 4)) < 1e-6


def test_unflagged_alternative_preferred(players, projs, my_squad, window, make_proj) -> None:
    """A squad player projecting 0 is benched every GW when a fit option exists."""
    projs[18] = make_proj(18, 0.0)
    sol = optimise(projs, players, my_squad, window, max_transfers=0, free_transfers=1)
    _assert_legal(sol, players, window)
    assert all(18 not in sol.xi[g] for g in window)


def test_blank_gw_player_benched(players, projs, my_squad, window, make_proj) -> None:
    """A starter whose team blanks in GW11 sits that GW only; the XI stays legal."""
    projs[31] = make_proj(31, {10: 5.6, 11: 0.0, 12: 5.6, 13: 5.6, 14: 5.6})
    sol = optimise(projs, players, my_squad, window, max_transfers=0, free_transfers=1)
    _assert_legal(sol, players, window)
    assert 31 not in sol.xi[11]
    assert 31 in sol.xi[10] and 31 in sol.xi[12]


def test_buyable_excludes_flagged(players, projs, my_squad, window, make_proj) -> None:
    """A player outside `buyable` is never brought in, however good."""
    projs[39] = make_proj(39, 20.0)
    allowed = set(players) - {39}
    sol = optimise(projs, players, my_squad, window, max_transfers=1, free_transfers=1,
                   buyable=allowed)
    assert 39 not in sol.squad
    open_sol = optimise(projs, players, my_squad, window, max_transfers=1, free_transfers=1)
    assert open_sol.transfers_in == [39]


def test_zero_transfers_when_no_gain(players, projs, my_squad, window, make_proj) -> None:
    """No pointless moves, and no -4 hit for a gain under 4 points."""
    idle = optimise(projs, players, my_squad, window, max_transfers=1, free_transfers=1)
    assert idle.transfers_in == [] and idle.transfers_out == [] and idle.hit_cost == 0
    projs[23] = make_proj(23, 12.0)  # big gain: worth the free transfer
    projs[24] = make_proj(24, 5.3)   # marginal gain (< 4 over the window): not worth a hit
    sol = optimise(projs, players, my_squad, window, max_transfers=2, free_transfers=1)
    assert sol.transfers_in == [23]
    assert sol.hit_cost == 0
