"""Payload assembly: schema shape, hit note, honest reasons, serialisability."""
import json
from dataclasses import replace
from datetime import datetime, timezone

from brief.chips import ChipAdvice
from brief.model import Projection
from brief.optimise import Solution
from brief.payload import ScenarioResult, build_payload, scenario_key
from brief.rivals import Mode, Rival
from brief.squad import MySquad
from tests.conftest import SQUAD_IDS, WINDOW

ME = 100
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
DEADLINE = datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc)


def _solution(swaps: list[tuple[int, int]], raw_total: float, hit_cost: int = 0) -> Solution:
    """A Solution whose squad is SQUAD_IDS with each (out, in) swap applied; a 3-4-3 XI starts."""
    squad = [dict(swaps).get(p, p) for p in SQUAD_IDS]
    start = {1, 6, 7, 8, 18, 19, 20, 21, 31, 32, 33}
    xi = [p for p in squad if p in start or p in dict(swaps).values()][:11]
    bench = [p for p in squad if p not in xi]
    return Solution(squad, {g: list(xi) for g in WINDOW}, {g: 31 for g in WINDOW},
                    {g: 32 for g in WINDOW}, {g: list(bench) for g in WINDOW},
                    [o for o, _ in swaps], [i for _, i in swaps], hit_cost, raw_total)


def _pick(pid: int, position: int, captain: bool = False) -> dict:
    """One FPL picks item."""
    return {"element": pid, "position": position, "is_captain": captain, "multiplier": 2 if captain else 1}


def _rival(eid: int, rank: int, picks=None) -> Rival:
    """A rival with simple names."""
    return Rival(eid, f"T{eid}", f"N{eid}", rank, 100 - rank, picks, None)


def _build(players, projs, scenarios, mode=None, rivals=None, squad=None, sells=None):
    """Call build_payload with the synthetic world."""
    rivals = rivals if rivals is not None else [_rival(ME, 2), _rival(1, 1, [_pick(31, 1, True)])]
    mode = mode or Mode("chase", 2, 98, rivals[1], 2)
    squad = squad or MySquad(list(SQUAD_IDS), {p: players[p].price for p in SQUAD_IDS}, 2.0, [], 9)
    return build_payload(season="2026/27", window=list(WINDOW), generated_at=NOW, deadline=DEADLINE, mode=mode,
                         rivals=rivals, my_entry=ME, players=players, projs=projs, squad=squad,
                         scenarios=scenarios, hold_total=100.0, priority_sells={6: 4} if sells is None else sells)


def _boost(projs, make_proj, pid: int, pts: float) -> None:
    """Make `pid` project `pts` every GW."""
    projs[pid] = make_proj(pid, pts)


def test_payload_has_15_scenarios(players, projs):
    """5 free-transfer counts x 3 hit levels give 15 keyed scenarios."""
    scen = [ScenarioResult(ft, h, _solution([], 100.0, h), False, [])
            for ft in range(1, 6) for h in (0, 4, 8)]
    payload = _build(players, projs, scen)
    assert len(payload["scenarios"]) == 15
    assert set(payload["scenarios"]) == {scenario_key(ft, h) for ft in range(1, 6) for h in (0, 4, 8)}
    s = payload["scenarios"]["1_0"]
    assert s["formation"] == "3-4-3"
    assert len(s["xi"]) == 11 and len(s["bench"]) == 4
    assert payload["assumption"] == "Assumes no transfers made since the GW9 deadline."
    assert payload["deadline"] == "2026-11-01T11:00:00+00:00"
    assert payload["inputs"]["selling"]["1"] == players[1].price


def test_hit_note_only_when_hit_pays(players, projs, make_proj):
    """hit_note appears on hits-0 only, and only when the -4 scenario nets more."""
    _boost(projs, make_proj, 11, 8.0)   # DEF in: 40 window pts vs 4.x for DEF 6
    _boost(projs, make_proj, 12, 8.0)
    free = ScenarioResult(1, 0, _solution([(6, 11)], 110.0), False, [])
    paid = ScenarioResult(1, 4, _solution([(6, 11), (7, 12)], 112.0, 4), False, [])
    payload = _build(players, projs, [free, paid])
    note = payload["scenarios"]["1_0"]["hit_note"]
    assert note is not None and "P7→P12" in note and "net +" in note
    assert payload["scenarios"]["1_4"]["hit_note"] is None
    worse = ScenarioResult(1, 4, _solution([(6, 11), (7, 12)], 105.0, 4), False, [])
    assert _build(players, projs, [free, worse])["scenarios"]["1_0"]["hit_note"] is None


def test_chase_reason_never_claims_false_differential(players, projs, make_proj):
    """If the chase target owns the incoming player the reason never says 'doesn't own'."""
    _boost(projs, make_proj, 11, 8.0)
    scen = [ScenarioResult(1, 0, _solution([(6, 11)], 110.0), False, [])]
    owns = [_rival(ME, 2), _rival(1, 1, [_pick(11, 1), _pick(31, 2, True)])]
    reason = _build(players, projs, scen, rivals=owns)["scenarios"]["1_0"]["transfers"][0]["reason"]
    assert "doesn't own" not in reason
    lacks = [_rival(ME, 2), _rival(1, 1, [_pick(31, 1, True)])]
    reason = _build(players, projs, scen, rivals=lacks)["scenarios"]["1_0"]["transfers"][0]["reason"]
    assert "N1 doesn't own him" in reason
    assert reason.startswith("P11 projects 40.0 over the next 5 GWs vs ")


def test_doubt_note_on_75_buy(players, projs, make_proj):
    """Buying a 75% player appends the doubtful note; flagged outs get their news."""
    players[11] = replace(players[11], status="d", chance=75, news="Knock")
    players[6] = replace(players[6], status="i", chance=0, news="Hamstring")
    _boost(projs, make_proj, 11, 8.0)
    scen = [ScenarioResult(1, 0, _solution([(6, 11)], 110.0), False, [])]
    payload = _build(players, projs, scen)
    reason = payload["scenarios"]["1_0"]["transfers"][0]["reason"]
    assert "75% doubtful" in reason and "P6: Hamstring" in reason
    assert payload["inputs"]["flagged_ids"] == [6]


def test_defend_suffixes_and_rival_rows(players, projs, make_proj):
    """Defend mode counts owners and captainers; rival rows exclude me, sort by rank."""
    _boost(projs, make_proj, 11, 8.0)
    rivals = [_rival(ME, 1), _rival(2, 3, None),
              _rival(1, 2, [_pick(11, 1), _pick(31, 2, True)])]
    mode = Mode("defend", 1, 99, rivals[2], 1)
    scen = [ScenarioResult(1, 0, _solution([(6, 11)], 110.0), False, [])]
    payload = _build(players, projs, scen, mode=mode, rivals=rivals, sells={7: 4})
    s = payload["scenarios"]["1_0"]
    assert s["transfers"][0]["reason"].endswith("owned by 1 of 1 rival")
    assert s["captain"]["reason"].endswith("1/1 rival likely captains him")
    assert [r["entry_id"] for r in payload["rivals"]] == [1, 2]
    assert payload["rivals"][0]["is_target"] and payload["rivals"][0]["captain"] == "P31"
    assert payload["rivals"][1]["projected_points"] is None and payload["rivals"][1]["captain"] is None
    assert s["priority_sells"][0]["reason"] == "Out for 4 of the next 5 GWs"
    assert s["net_gain_window"] == 10.0


def test_payload_json_serialisable(players, projs):
    """The payload round-trips through json.dumps, including a null-target mode."""
    chip = ChipAdvice("3xc", 5.04, 12, 9.26, False, "hold")
    scen = [ScenarioResult(ft, 0, _solution([], 100.0), True, [chip]) for ft in range(1, 6)]
    rivals = [_rival(ME, 1)]
    payload = _build(players, projs, scen, mode=Mode("defend", 1, 99, None, 0), rivals=rivals)
    assert payload["mode"]["target"] is None
    def keys_are_str(node) -> bool:
        """True when every dict key at every depth is a str."""
        if isinstance(node, dict):
            return all(isinstance(k, str) and keys_are_str(v) for k, v in node.items())
        if isinstance(node, list):
            return all(keys_are_str(v) for v in node)
        return True

    assert keys_are_str(payload)
    back = json.loads(json.dumps(payload))
    assert back["version"] == 1
    assert back["scenarios"]["1_0"]["chips"][0]["gain_best"] == 9.3


def _split(pid: int, pts: float, basis: float) -> Projection:
    """A projection whose captain basis differs from its points."""
    return Projection(pid, {g: pts for g in WINDOW}, {g: basis for g in WINDOW},
                      {g: 90.0 for g in WINDOW})


def _captain(players, projs) -> dict:
    """The 1_0 captain block of a hold scenario (captain P31, vice P32)."""
    top = ScenarioResult(1, 0, _solution([], 100.0), False, [])
    return _build(players, projs, [top])["scenarios"]["1_0"]["captain"]


def test_captain_reason_top_basis_and_points(players, projs, make_proj):
    """Top on both expected output and points: 'next best' by points."""
    _boost(projs, make_proj, 31, 6.0)
    cap = _captain(players, projs)
    assert cap["reason"].startswith("P31 projects 6.0 (next best 5.7: P33)")
    assert cap["basis"] == 6.0


def test_captain_reason_near_tie_on_basis(players, projs):
    """A captain within CAPTAIN_NEAR_TIE of the top basis reads 'near-tied ... on expected output'."""
    projs[31] = _split(31, 6.0, 6.0)
    projs[32] = _split(32, 5.0, 6.3)
    reason = _captain(players, projs)["reason"]
    assert reason.startswith("P31 projects 6.0, near-tied with P32 on expected output")
    assert "next best" not in reason


def test_captain_reason_top_basis_lower_points(players, projs):
    """Top basis but out-projected on points: says it was picked on expected output."""
    projs[31] = _split(31, 6.0, 7.0)
    projs[32] = _split(32, 6.5, 5.0)
    reason = _captain(players, projs)["reason"]
    assert reason.startswith("P31 picked on expected output; P32 projects higher on form (6.5 vs 6.0)")


def test_captain_reason_far_below_top_basis(players, projs):
    """A captain clearly behind on expected output never claims to be picked on it."""
    projs[31] = _split(31, 6.0, 6.0)
    projs[32] = _split(32, 5.0, 8.0)
    reason = _captain(players, projs)["reason"]
    assert reason.startswith("P31 projects 6.0; P32 rates higher on expected output (8.0 vs 6.0)")
    assert "picked on expected output" not in reason


def test_captain_options_sorted_by_basis(players, projs):
    """captain_options: the top 5 XI players by captain basis, each with its basis; vice has basis."""
    projs[18] = _split(18, 3.0, 9.0)
    top = ScenarioResult(1, 0, _solution([], 100.0), False, [])
    s = _build(players, projs, [top])["scenarios"]["1_0"]
    opts = s["captain_options"]
    assert len(opts) == 5
    assert opts[0]["id"] == 18 and opts[0]["basis"] == 9.0 and opts[0]["proj"] == 3.0
    assert [o["basis"] for o in opts] == sorted((o["basis"] for o in opts), reverse=True)
    assert s["vice"]["id"] == 32 and s["vice"]["basis"] == round(projs[32].captain_basis[10], 1)


def test_chase_captain_suffix(players, projs):
    """The chase suffix appears only when the target is not captaining my captain."""
    scen = [ScenarioResult(1, 0, _solution([], 100.0), False, [])]
    other = [_rival(ME, 2), _rival(1, 1, [_pick(32, 1, True)])]
    reason = _build(players, projs, scen, rivals=other)["scenarios"]["1_0"]["captain"]["reason"]
    assert reason.endswith("N1 isn't captaining him")
    same = [_rival(ME, 2), _rival(1, 1, [_pick(31, 1, True)])]
    reason = _build(players, projs, scen, rivals=same)["scenarios"]["1_0"]["captain"]["reason"]
    assert "captaining" not in reason


def test_hit_note_net_is_scenario_level(players, projs, make_proj):
    """The hit re-chooses the free transfer too: net is the raw_total difference, not the pair gain."""
    _boost(projs, make_proj, 11, 8.0)
    _boost(projs, make_proj, 12, 9.0)
    _boost(projs, make_proj, 13, 6.0)
    free = ScenarioResult(1, 0, _solution([(6, 11)], 110.0), False, [])
    paid = ScenarioResult(1, 4, _solution([(6, 12), (7, 13)], 113.2, 4), False, [])
    note = _build(players, projs, [free, paid])["scenarios"]["1_0"]["hit_note"]
    assert note == "A -4 for P7→P12 gains +7.2 over 5 GWs, net +3.2."


def test_hit_note_null_unless_hit_scenario_nets_more(players, projs, make_proj):
    """No note when the -4 scenario nets nothing (even rounded) or paid no hit at all."""
    _boost(projs, make_proj, 11, 8.0)
    _boost(projs, make_proj, 12, 9.0)
    free = ScenarioResult(1, 0, _solution([(6, 11)], 110.0), False, [])
    flat = ScenarioResult(1, 4, _solution([(6, 11), (7, 12)], 110.04, 4), False, [])
    assert _build(players, projs, [free, flat])["scenarios"]["1_0"]["hit_note"] is None
    swap = ScenarioResult(1, 4, _solution([(6, 12)], 115.0, 0), False, [])
    assert _build(players, projs, [free, swap])["scenarios"]["1_0"]["hit_note"] is None


def test_hit_note_pairs_only_the_extra_moves(players, projs, make_proj):
    """Extras are the set difference of outs/ins; re-zipping all pairs would mis-pair them."""
    _boost(projs, make_proj, 12, 4.5)
    _boost(projs, make_proj, 13, 10.0)
    free = ScenarioResult(1, 0, _solution([(6, 12)], 110.0), False, [])
    paid = ScenarioResult(1, 4, _solution([(6, 12), (7, 13)], 130.0, 4), False, [])
    note = _build(players, projs, [free, paid])["scenarios"]["1_0"]["hit_note"]
    assert note is not None and "P7→P13" in note and "over 5 GWs" in note


def test_priority_sells_skip_sold_and_unknown(players, projs):
    """A player the scenario already sells, or one missing from the pool, is not listed."""
    scen = [ScenarioResult(1, 0, _solution([(6, 11)], 110.0), False, []),
            ScenarioResult(2, 0, _solution([], 100.0), False, [])]
    payload = _build(players, projs, scen, sells={6: 4, 7: 3, 999: 2})
    assert [s["player"]["id"] for s in payload["scenarios"]["1_0"]["priority_sells"]] == [7]
    assert [s["player"]["id"] for s in payload["scenarios"]["2_0"]["priority_sells"]] == [6, 7]


def test_rival_plural_agreement(players, projs, make_proj):
    """'2 of 3 rivals' is plural."""
    _boost(projs, make_proj, 11, 8.0)
    rivals = [_rival(ME, 1), _rival(1, 2, [_pick(11, 1)]), _rival(2, 3, [_pick(11, 1)]),
              _rival(3, 4, [_pick(31, 1)])]
    scen = [ScenarioResult(1, 0, _solution([(6, 11)], 110.0), False, [])]
    payload = _build(players, projs, scen, mode=Mode("defend", 1, 99, rivals[1], 1), rivals=rivals)
    assert payload["scenarios"]["1_0"]["transfers"][0]["reason"].endswith("owned by 2 of 3 rivals")
