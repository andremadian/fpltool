"""Chip evaluation: Triple Captain, Bench Boost, Free Hit, Wildcard."""
from brief.chips import CHIP_THRESHOLDS, evaluate_chips, solve_freehit, solve_wildcard
from brief.optimise import Solution, optimise
from tests.conftest import SQUAD_IDS


def _scenario(window, projs, squad_ids=SQUAD_IDS, captain=31, raw_total=100.0) -> Solution:
    """A hand-built Solution: first 11 ids start, last 4 are the bench, `captain` captains every GW."""
    xi, bench = list(squad_ids[:11]), list(squad_ids[11:])
    if captain not in xi:
        xi[-1] = captain
        bench = [p for p in squad_ids if p not in xi]
    vice = next(p for p in xi if p != captain)
    return Solution(
        list(squad_ids), {g: list(xi) for g in window}, {g: captain for g in window},
        {g: vice for g in window}, {g: list(bench) for g in window}, [], [], 0, raw_total,
    )


def test_tc_best_gw_is_dgw(window, projs, make_proj, players):
    """A double-GW captain makes that GW the best Triple Captain slot, but not play-now."""
    projs[31] = make_proj(31, {10: 6.0, 11: 6.0, 12: 14.0, 13: 6.0, 14: 6.0})
    scenario = _scenario(window, projs)
    advice = evaluate_chips(["3xc"], scenario, projs, window, None, None, players)
    assert len(advice) == 1
    tc = advice[0]
    assert tc.chip == "3xc"
    assert tc.best_gw == 12 and tc.gain_best == 14.0
    assert tc.gain_now == 6.0
    assert not tc.play_now  # best GW is not the target GW
    assert "hold" in tc.reason and "GW12" in tc.reason and "P31" in tc.reason


def test_bb_play_now_requires_threshold(window, projs, make_proj, players):
    """Bench Boost plays now only when the target-GW bench clears 8.0 points."""
    scenario = _scenario(window, projs)
    bench = scenario.bench_order[10]
    for pid in bench:
        projs[pid] = make_proj(pid, 1.5)  # 4 x 1.5 = 6.0 < 8.0
    low = evaluate_chips(["bboost"], scenario, projs, window, None, None, players)[0]
    assert low.gain_now == 6.0 and not low.play_now
    for pid in bench:
        projs[pid] = make_proj(pid, 2.5)  # 4 x 2.5 = 10.0 >= 8.0
    high = evaluate_chips(["bboost"], scenario, projs, window, None, None, players)[0]
    assert high.gain_now == 10.0 and high.best_gw == 10 and high.play_now
    assert high.reason.endswith("play now.")
    assert CHIP_THRESHOLDS["bboost"] == 8.0


def test_used_chip_omitted(window, projs, players):
    """Only available chips are returned, in CHIP_CODES order."""
    scenario = _scenario(window, projs)
    advice = evaluate_chips(["3xc", "bboost"], scenario, projs, window, None, None, players)
    assert [a.chip for a in advice] == ["bboost", "3xc"]
    assert evaluate_chips([], scenario, projs, window, None, None, players) == []
    # freehit / wildcard are omitted when their solutions are None, even if available.
    both = evaluate_chips(["wildcard", "freehit"], scenario, projs, window, None, None, players)
    assert both == []


def test_wildcard_gain_vs_scenario(window, projs, my_squad, players, make_proj):
    """Wildcard and Free Hit gains are measured against the scenario solution."""
    # A cheap non-squad forward who massively outscores everyone: only unlimited transfers use him.
    projs[40] = make_proj(40, 12.0)
    scenario = optimise(projs, players, my_squad, window, 0, 1)
    wc = solve_wildcard(projs, players, my_squad, window)
    fh = solve_freehit(projs, players, my_squad, window[0])
    assert list(fh.xi) == [window[0]]
    assert wc.raw_total > scenario.raw_total

    advice = evaluate_chips(["freehit", "wildcard"], scenario, projs, window, fh, wc, players)
    assert [a.chip for a in advice] == ["wildcard", "freehit"]
    wildcard, freehit = advice
    assert wildcard.gain_now == round(wc.raw_total - scenario.raw_total, 1)
    assert wildcard.best_gw == window[0] and wildcard.gain_best == wildcard.gain_now
    assert freehit.best_gw == window[0] and freehit.gain_now > 0
    assert f"{wildcard.gain_now}" in wildcard.reason and "5 GWs" in wildcard.reason
    assert f"{freehit.gain_now}" in freehit.reason
