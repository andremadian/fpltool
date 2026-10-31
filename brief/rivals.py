"""Rival-aware decisions: defend/chase mode, utility weights, near-tie guardrail, captaincy.

The rival bonus only steers *which* near-equal option is picked. It never changes a
displayed number: every Solution's `raw_total` and every projection stay raw.
"""
import logging
from dataclasses import dataclass

from brief.model import Projection
from brief.optimise import Solution, optimise
from brief.squad import MySquad
from brief.types import Player

log = logging.getLogger(__name__)

RIVAL_BONUS = 0.08
NEAR_TIE_PTS = 2.0  # max raw points over the window the rival bonus may cost
CAPTAIN_NEAR_TIE = 0.5  # captain candidates are within this of the top captain_basis


@dataclass(frozen=True)
class Rival:
    """One mini-league entry with this GW's picks (None when no squad is available yet)."""
    entry_id: int
    team_name: str
    player_name: str
    rank: int
    total: int
    picks: list[dict] | None
    chip: str | None


@dataclass(frozen=True)
class Mode:
    """Defend (I lead) or chase (someone is above me), with the rival being targeted."""
    kind: str
    my_rank: int
    my_total: int
    target: Rival | None
    gap: int


def decide_mode(standings: list[Rival], my_entry: int) -> Mode:
    """Defend against the entry below if I'm first, else chase the entry directly above me."""
    ordered = sorted(standings, key=lambda r: r.rank)  # stable: ties keep list order
    idx = next(i for i, r in enumerate(ordered) if r.entry_id == my_entry)
    me = ordered[idx]
    if idx == 0:
        target = ordered[1] if len(ordered) > 1 else None
        gap = target.total - me.total if target else 0
        return Mode("defend", me.rank, me.total, target, gap)
    target = ordered[idx - 1]
    return Mode("chase", me.rank, me.total, target, target.total - me.total)


def _with_picks(rivals: list[Rival], my_entry: int) -> list[Rival]:
    """Rivals other than me who have picks."""
    return [r for r in rivals if r.entry_id != my_entry and r.picks is not None]


def ownership(rivals: list[Rival], my_entry: int) -> dict[int, float]:
    """Share of rivals (excluding me and those without picks) owning each player."""
    active = _with_picks(rivals, my_entry)
    counts: dict[int, int] = {}
    for r in active:
        for pick in r.picks or []:
            counts[pick["element"]] = counts.get(pick["element"], 0) + 1
    return {pid: n / len(active) for pid, n in counts.items()}


def captain_share(rivals: list[Rival], my_entry: int) -> dict[int, float]:
    """Share of rivals (excluding me and those without picks) captaining each player."""
    active = _with_picks(rivals, my_entry)
    counts: dict[int, int] = {}
    for r in active:
        for pick in r.picks or []:
            if pick.get("is_captain"):
                counts[pick["element"]] = counts.get(pick["element"], 0) + 1
    return {pid: n / len(active) for pid, n in counts.items()}


def utility_weights(
    mode: Mode,
    own: dict[int, float],
    bonus: float = RIVAL_BONUS,
    player_ids: set[int] | None = None,
) -> dict[int, float]:
    """Per-player utility multipliers: differentials vs the target (chase) or shared players (defend).

    `player_ids` (optional) is the full player universe, so players no rival owns still get the
    chase differential bonus; without it only players in `own` (or the target's picks) are weighted.
    """
    ids = set(own) | (player_ids or set())
    if mode.kind == "defend":
        return {pid: 1 + bonus * own.get(pid, 0.0) for pid in ids}
    target = mode.target
    if target is None or target.picks is None:
        return {pid: 1 + bonus * (1 - own.get(pid, 0.0)) for pid in ids}
    target_owns = {p["element"] for p in target.picks}
    ids |= target_owns
    return {pid: 1 + bonus * (0 if pid in target_owns else 1) for pid in ids}


def optimise_with_guardrail(
    projs: dict[int, Projection],
    players: dict[int, Player],
    squad: MySquad,
    window: list[int],
    max_transfers: int | None,
    free_transfers: int,
    buyable: set[int] | None,
    weights: dict[int, float],
    near_tie: float = NEAR_TIE_PTS,
) -> tuple[Solution, bool]:
    """Solve raw and with rival utility; keep the utility answer only if it costs <= near_tie raw points."""
    raw = optimise(projs, players, squad, window, max_transfers, free_transfers, buyable=buyable)
    if all(w == 1.0 for w in weights.values()):
        return raw, False
    util = optimise(projs, players, squad, window, max_transfers, free_transfers,
                    utility=weights, buyable=buyable)
    if raw.raw_total - util.raw_total > near_tie:
        return raw, False
    return util, set(util.squad) != set(raw.squad)


def pick_captain(
    xi: list[int],
    projs: dict[int, Projection],
    gw: int,
    mode: Mode,
    own_captain: dict[int, float],
) -> tuple[int, int]:
    """Choose (captain, vice) from the XI; rival mode only breaks near-ties in captain_basis."""
    def basis(pid: int) -> float:
        """Captain basis of `pid` in `gw`."""
        proj = projs.get(pid)
        return proj.captain_basis.get(gw, 0.0) if proj else 0.0

    top = max(basis(p) for p in xi)
    candidates = [p for p in xi if basis(p) >= top - CAPTAIN_NEAR_TIE]
    if mode.kind == "defend":
        captain = max(candidates, key=lambda p: (own_captain.get(p, 0.0), basis(p)))
    else:
        target_captain = None
        if mode.target is not None and mode.target.picks:
            target_captain = next((p["element"] for p in mode.target.picks if p.get("is_captain")), None)
        pool = [p for p in candidates if p != target_captain] or candidates
        captain = min(pool, key=lambda p: (own_captain.get(p, 0.0), -basis(p)))
    vice = max((p for p in xi if p != captain), key=basis)
    return captain, vice


def rival_projection(r: Rival, projs: dict[int, Projection], gw: int) -> float | None:
    """Projected points for a rival's XI this GW (None without picks); raw, no rival bonus."""
    if r.picks is None:
        return None
    total = 0.0
    for pick in r.picks:
        proj = projs.get(pick["element"])
        pts = proj.points.get(gw, 0.0) if proj else 0.0
        mult = pick.get("multiplier")
        if mult is None:
            if pick["position"] <= 11 or r.chip == "bboost":
                mult = 1
            else:
                mult = 0
            if pick.get("is_captain"):
                mult = 3 if r.chip == "3xc" else 2
        total += pts * mult
    return total
