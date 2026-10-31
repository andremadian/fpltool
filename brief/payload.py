"""Assemble the JSON payload the PWA reads, with plain-English reasons for every move.

The schema is a contract with the TypeScript types (version 1). Every float is rounded
to one decimal and the result is plain dicts/lists/str/numbers so `json.dumps` works.
"""
import logging
from dataclasses import asdict, dataclass
from datetime import datetime

from brief.availability import needs_doubt_note
from brief.chips import ChipAdvice
from brief.model import Projection
from brief.optimise import Solution
from brief.rivals import Mode, Rival, rival_projection
from brief.squad import MySquad
from brief.types import Player

log = logging.getLogger(__name__)

PAYLOAD_VERSION = 1
HIT_COST = 4  # points a single extra transfer costs



def scenario_key(ft: int, hits: int) -> str:
    """Key of a scenario in the payload, e.g. '2_0'."""
    return f"{ft}_{hits}"


@dataclass(frozen=True)
class ScenarioResult:
    """One solved (free transfers, hits) scenario with its mode flag and chip advice."""
    ft: int
    hits: int
    solution: Solution
    mode_changed: bool
    chips: list[ChipAdvice]


def _r1(value: float) -> float:
    """Round to one decimal."""
    return round(value, 1)


def _pts(projs: dict[int, Projection], pid: int, gw: int) -> float:
    """Projected points of `pid` in `gw` (0 without a projection)."""
    proj = projs.get(pid)
    return proj.points.get(gw, 0.0) if proj else 0.0


def _basis(projs: dict[int, Projection], pid: int, gw: int) -> float:
    """Captain basis of `pid` in `gw` (0 without a projection)."""
    proj = projs.get(pid)
    return proj.captain_basis.get(gw, 0.0) if proj else 0.0


def _window_pts(projs: dict[int, Projection], pid: int, window: list[int]) -> float:
    """Total projected points of `pid` across the window."""
    return sum(_pts(projs, pid, g) for g in window)


def _flag(player: Player) -> dict | None:
    """Availability flag, or None when the player is fully fit."""
    if player.status == "a" and player.chance in (None, 100):
        return None
    return {"status": player.status, "chance": player.chance, "news": player.news}


def _ref(player: Player) -> dict:
    """The PlayerRef block."""
    return {"id": player.id, "name": player.name, "team": player.team_short,
            "pos": player.pos, "price": _r1(player.price)}


def _slot(player: Player, projs: dict[int, Projection], gw: int) -> dict:
    """The PlayerSlot block: ref + target-GW points + flag."""
    return {**_ref(player), "proj": _r1(_pts(projs, player.id, gw)), "flag": _flag(player)}


def _rival_counts(rivals: list[Rival], my_entry: int) -> tuple[int, dict[int, int], dict[int, int]]:
    """(n rivals with picks excluding me, owners per player, captainers per player)."""
    active = [r for r in rivals if r.entry_id != my_entry and r.picks is not None]
    owners: dict[int, int] = {}
    captains: dict[int, int] = {}
    for r in active:
        for pick in r.picks or []:
            owners[pick["element"]] = owners.get(pick["element"], 0) + 1
            if pick.get("is_captain"):
                captains[pick["element"]] = captains.get(pick["element"], 0) + 1
    return len(active), owners, captains


def _target_picks(mode: Mode) -> list[dict] | None:
    """The chase/defend target's picks, if any."""
    return mode.target.picks if mode.target is not None else None


def _rivals(n: int) -> str:
    """'rival' or 'rivals' to agree with `n`."""
    return "rival" if n == 1 else "rivals"


def _transfer_reason(
    p_in: Player, p_out: Player, window: list[int], projs: dict[int, Projection],
    mode: Mode, n: int, owners: dict[int, int],
) -> str:
    """The reason string for one transfer, built only from claims the data supports."""
    text = (f"{p_in.name} projects {_r1(_window_pts(projs, p_in.id, window))} over the next "
            f"{len(window)} GWs vs {_r1(_window_pts(projs, p_out.id, window))} for {p_out.name}")
    if _flag(p_out) is not None:
        text += f" · {p_out.name}: {p_out.news}" if p_out.news else f" · {p_out.name} flagged ({p_out.status})"
    if needs_doubt_note(p_in):
        text += " · 75% doubtful"
    if mode.kind == "defend" and n > 0:
        text += f" · owned by {owners.get(p_in.id, 0)} of {n} {_rivals(n)}"
    elif mode.kind == "chase" and mode.target is not None:
        picks = _target_picks(mode)
        if picks is not None and p_in.id not in {p["element"] for p in picks}:
            text += f" · {mode.target.player_name} doesn't own him"
    return text


def _pair_transfers(
    out_ids: list[int], in_ids: list[int], players: dict[int, Player], window: list[int],
    projs: dict[int, Projection], mode: Mode, n: int, owners: dict[int, int],
) -> list[dict]:
    """Pair outs with ins inside each position (best in vs worst out), ordered by gain."""
    rows: list[dict] = []
    for pos in ("GKP", "DEF", "MID", "FWD"):
        outs = sorted((players[p] for p in out_ids if players[p].pos == pos),
                      key=lambda p: _window_pts(projs, p.id, window))
        ins = sorted((players[p] for p in in_ids if players[p].pos == pos),
                     key=lambda p: -_window_pts(projs, p.id, window))
        for p_out, p_in in zip(outs, ins):
            gain = _window_pts(projs, p_in.id, window) - _window_pts(projs, p_out.id, window)
            rows.append({"out": _ref(p_out), "in": _ref(p_in), "gain_window": _r1(gain),
                         "reason": _transfer_reason(p_in, p_out, window, projs, mode, n, owners),
                         "_gain": gain})
    rows.sort(key=lambda t: -t["_gain"])
    return rows


def _strip(rows: list[dict]) -> list[dict]:
    """Drop the private unrounded gain from transfer rows."""
    return [{k: v for k, v in row.items() if k != "_gain"} for row in rows]


def _hit_note(res: ScenarioResult, extras: dict[tuple[int, int], list[dict]],
              by_key: dict[tuple[int, int], ScenarioResult], window: list[int]) -> str | None:
    """Note on whether a -4 beats this hit-free scenario; None unless the extra move out-gains its cost."""
    if res.hits != 0:
        return None
    hit = by_key.get((res.ft, HIT_COST))
    if hit is None or hit.solution.raw_total <= res.solution.raw_total:
        return None
    pairs = extras[(res.ft, res.hits)]
    if not pairs:
        return None
    best = max(pairs, key=lambda t: t["_gain"])
    gain = best["_gain"]
    if gain <= HIT_COST:
        return None
    return (f"A -{HIT_COST} for {best['out']['name']}→{best['in']['name']} gains "
            f"+{_r1(gain)} over {len(window)} GWs, net +{_r1(gain - HIT_COST)}.")


def _captain_block(
    sol: Solution, gw: int, players: dict[int, Player], projs: dict[int, Projection],
    mode: Mode, n: int, captains: dict[int, int],
) -> dict:
    """The captain PlayerSlot plus its reason."""
    cap = players[sol.captain[gw]]
    others = [p for p in sol.xi[gw] if p != cap.id]
    alt = max(others, key=lambda p: _pts(projs, p, gw)) if others else None
    cap_pts = _r1(_pts(projs, cap.id, gw))
    reason = f"{cap.name} projects {cap_pts}"
    if alt is not None:
        alt_pts = _r1(_pts(projs, alt, gw))
        if _pts(projs, cap.id, gw) >= _pts(projs, alt, gw):
            reason += f" (next best {alt_pts}: {players[alt].name})"
        else:
            reason += f", near-tied with {players[alt].name} on {alt_pts}"
    if mode.kind == "defend":
        k = captains.get(cap.id, 0)
        if k > 0:
            reason += f" · {k}/{n} {_rivals(n)} likely {'captains' if n == 1 else 'captain'} him"
    elif mode.target is not None and mode.target.picks is not None:
        captained = {p["element"] for p in mode.target.picks if p.get("is_captain")}
        if cap.id not in captained:
            reason += f" · {mode.target.player_name} isn't captaining him"
    return {**_slot(cap, projs, gw), "reason": reason}


def _formation(xi: list[int], players: dict[int, Player]) -> str:
    """DEF-MID-FWD counts of the XI."""
    counts = {pos: sum(1 for p in xi if players[p].pos == pos) for pos in ("DEF", "MID", "FWD")}
    return f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"


def _scenario_block(
    res: ScenarioResult, hit_note: str | None, transfers: list[dict], *, window: list[int],
    players: dict[int, Player], projs: dict[int, Projection], mode: Mode, n: int,
    captains: dict[int, int], hold_total: float, priority_sells: dict[int, int],
) -> dict:
    """One scenario's payload block."""
    sol, gw = res.solution, window[0]
    xi = sol.xi[gw]
    cap = sol.captain[gw]
    projected = sum(_pts(projs, p, gw) for p in xi) + _pts(projs, cap, gw)
    sells = []
    for pid, n_out in priority_sells.items():
        if pid not in players:
            log.warning("Priority sell %s is not in the player pool; skipped", pid)
        elif pid not in sol.transfers_out:
            sells.append({"player": _ref(players[pid]),
                          "reason": f"Out for {n_out} of the next {len(window)} GWs"})
    return {
        "transfers": _strip(transfers),
        "hit_cost": sol.hit_cost,
        "net_gain_window": _r1(sol.raw_total - hold_total),
        "hit_note": hit_note,
        "priority_sells": sells,
        "formation": _formation(xi, players),
        "xi": [_slot(players[p], projs, gw) for p in xi],
        "bench": [_slot(players[p], projs, gw) for p in sol.bench_order[gw]],
        "captain": _captain_block(sol, gw, players, projs, mode, n, captains),
        "vice": _slot(players[sol.vice[gw]], projs, gw),
        "projected_points": _r1(projected),
        "mode_changed_answer": res.mode_changed,
        "chips": [_round_chip(c) for c in res.chips],
    }


def _round_chip(chip: ChipAdvice) -> dict:
    """ChipAdvice as a plain dict with numbers rounded."""
    d = asdict(chip)
    d["gain_now"], d["gain_best"] = _r1(d["gain_now"]), _r1(d["gain_best"])
    return d


def _rival_row(r: Rival, mode: Mode, projs: dict[int, Projection], gw: int,
               players: dict[int, Player]) -> dict:
    """One league-table row with projected points and captain."""
    proj = rival_projection(r, projs, gw)
    cap = None
    if r.picks is not None:
        cap_id = next((p["element"] for p in r.picks if p.get("is_captain")), None)
        cap = players[cap_id].name if cap_id in players else None
    return {"entry_id": r.entry_id, "team_name": r.team_name, "player_name": r.player_name,
            "rank": r.rank, "total": r.total,
            "projected_points": None if proj is None else _r1(proj), "captain": cap,
            "is_target": mode.target is not None and r.entry_id == mode.target.entry_id}


def _mode_block(mode: Mode) -> dict:
    """The mode block, with a slim target."""
    t = mode.target
    target = None if t is None else {"entry_id": t.entry_id, "team_name": t.team_name,
                                     "player_name": t.player_name, "rank": t.rank, "total": t.total}
    return {"kind": mode.kind, "my_rank": mode.my_rank, "my_total": mode.my_total,
            "gap": mode.gap, "target": target}


def build_payload(
    *, season: str, window: list[int], generated_at: datetime, mode: Mode, rivals: list[Rival],
    my_entry: int, players: dict[int, Player], projs: dict[int, Projection], squad: MySquad,
    scenarios: list[ScenarioResult], hold_total: float, priority_sells: dict[int, int],
) -> dict:
    """Build the version-1 weekly brief payload."""
    gw = window[0]
    n, owners, captains = _rival_counts(rivals, my_entry)
    paired = {(s.ft, s.hits): _pair_transfers(s.solution.transfers_out, s.solution.transfers_in,
                                              players, window, projs, mode, n, owners)
              for s in scenarios}
    by_key = {(s.ft, s.hits): s for s in scenarios}
    extras: dict[tuple[int, int], list[dict]] = {}
    for s in scenarios:
        hit = by_key.get((s.ft, HIT_COST))
        if s.hits != 0 or hit is None:
            continue
        extra_out = [p for p in hit.solution.transfers_out if p not in s.solution.transfers_out]
        extra_in = [p for p in hit.solution.transfers_in if p not in s.solution.transfers_in]
        extras[(s.ft, s.hits)] = _pair_transfers(extra_out, extra_in, players, window, projs,
                                                 mode, n, owners)
    blocks = {}
    for res in scenarios:
        blocks[scenario_key(res.ft, res.hits)] = _scenario_block(
            res, _hit_note(res, extras, by_key, window), paired[(res.ft, res.hits)], window=window,
            players=players, projs=projs, mode=mode, n=n, captains=captains,
            hold_total=hold_total, priority_sells=priority_sells)
    others = sorted((r for r in rivals if r.entry_id != my_entry), key=lambda r: r.rank)
    return {
        "version": PAYLOAD_VERSION,
        "season": season,
        "gw": gw,
        "generated_at": generated_at.isoformat(),
        "window": list(window),
        "mode": _mode_block(mode),
        "assumption": f"Assumes no transfers made since the GW{gw} deadline.",
        "rivals": [_rival_row(r, mode, projs, gw, players) for r in others],
        "scenarios": blocks,
        "inputs": {
            "bank": _r1(squad.bank),
            "squad_ids": list(squad.player_ids),
            "selling": {str(pid): _r1(v) for pid, v in squad.selling.items()},
            "flagged_ids": [pid for pid in squad.player_ids
                            if pid in players and _flag(players[pid]) is not None],
        },
    }
