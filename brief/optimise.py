"""MILP squad / XI / captain optimiser over the planning window (scipy.optimize.milp).

Binary variables per pool player p and window GW g:
    s_p    p is in the 15-man squad
    x_pg   p starts in GW g
    c_pg   p captains in GW g
plus one integer h = paid (hit) transfers. The objective maximises, per GW,
    u_p * (pts*x + pts*c + bench_weight*pts*(s - x)) - 4h.
The vice-captain carries no objective weight, so it is picked after the solve:
the best `captain_basis` in the XI other than the captain.
"""
import logging
import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from brief.model import Projection
from brief.squad import MySquad
from brief.types import Player

log = logging.getLogger(__name__)

SQUAD_QUOTA = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_RANGE = {"GKP": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
XI_SIZE = 11
MAX_PER_CLUB = 3
HIT_COST = 4
# Pool pre-filter: besides my own 15, only the best N buyable players per position
# (by total window points) enter the MILP. Keeps each solve well under ~3s on the
# real ~670-player pool; nobody outside a position's top 40 is a realistic buy.
POOL_PER_POSITION = 40
# Deterministic tie-break: each incoming player costs a hair (scaled by id), so
# identical inputs give identical answers and exact ties keep current players.
INCOMING_TIEBREAK = 1e-6


@dataclass(frozen=True)
class Solution:
    """The optimal squad and, per window GW, XI, captain, vice and bench order."""
    squad: list[int]
    xi: dict[int, list[int]]
    captain: dict[int, int]
    vice: dict[int, int]
    bench_order: dict[int, list[int]]
    transfers_out: list[int]
    transfers_in: list[int]
    hit_cost: int
    raw_total: float


def _points(projs: dict[int, Projection], pid: int, gw: int) -> float:
    """Projected points for `pid` in `gw` (0 when there is no projection)."""
    proj = projs.get(pid)
    return proj.points.get(gw, 0.0) if proj else 0.0


def _captain_basis(projs: dict[int, Projection], pid: int, gw: int) -> float:
    """Captaincy basis for `pid` in `gw` (0 when there is no projection)."""
    proj = projs.get(pid)
    return proj.captain_basis.get(gw, 0.0) if proj else 0.0


def _build_pool(
    projs: dict[int, Projection],
    players: dict[int, Player],
    squad_ids: set[int],
    window: list[int],
    buyable: set[int] | None,
) -> list[int]:
    """My squad plus the top POOL_PER_POSITION buyable non-squad players per position."""
    pool = set(squad_ids)
    for pos in SQUAD_QUOTA:
        candidates = []
        for pid, player in players.items():
            if pid in squad_ids or player.pos != pos:
                continue
            if buyable is not None and pid not in buyable:
                continue
            total = sum(_points(projs, pid, g) for g in window)
            if total > 0:
                candidates.append((-total, pid))
        pool.update(pid for _, pid in sorted(candidates)[:POOL_PER_POSITION])
    return sorted(pool)


class _Rows:
    """Accumulates sparse constraint rows lb <= a.x <= ub."""

    def __init__(self) -> None:
        """Start with no rows."""
        self.r: list[int] = []
        self.c: list[int] = []
        self.v: list[float] = []
        self.lb: list[float] = []
        self.ub: list[float] = []

    def add(self, coeffs: dict[int, float], lb: float, ub: float) -> None:
        """Append one row with the given column coefficients and bounds."""
        row = len(self.lb)
        for col, val in coeffs.items():
            self.r.append(row)
            self.c.append(col)
            self.v.append(val)
        self.lb.append(lb)
        self.ub.append(ub)

    def constraint(self, n_vars: int) -> LinearConstraint:
        """Return the rows as one scipy LinearConstraint."""
        a = coo_matrix((self.v, (self.r, self.c)), shape=(len(self.lb), n_vars)).tocsr()
        return LinearConstraint(a, np.array(self.lb), np.array(self.ub))


def optimise(
    projs: dict[int, Projection],
    players: dict[int, Player],
    squad: MySquad,
    window: list[int],
    max_transfers: int | None,
    free_transfers: int,
    utility: dict[int, float] | None = None,
    bench_weight: float = 0.12,
    buyable: set[int] | None = None,
) -> Solution:
    """Solve for the best squad, XIs and captains over `window` (None transfers = unlimited, no hits)."""
    started = time.monotonic()
    utility = utility or {}
    squad_ids = set(squad.player_ids)
    pool = _build_pool(projs, players, squad_ids, window, buyable)
    n, n_gw = len(pool), len(window)
    s_col = {p: i for i, p in enumerate(pool)}
    x_col = {(p, g): n + gi * n + i for gi, g in enumerate(window) for i, p in enumerate(pool)}
    c_col = {(p, g): n + (n_gw + gi) * n + i for gi, g in enumerate(window) for i, p in enumerate(pool)}
    h_col = n + 2 * n_gw * n
    n_vars = h_col + 1

    # Objective (milp minimises, so negate the value we maximise).
    cost = np.zeros(n_vars)
    for p in pool:
        u = utility.get(p, 1.0)
        for g in window:
            pts = _points(projs, p, g)
            cost[s_col[p]] -= u * bench_weight * pts
            cost[x_col[p, g]] -= u * (1 - bench_weight) * pts
            cost[c_col[p, g]] -= u * pts
        if p not in squad_ids:
            cost[s_col[p]] += INCOMING_TIEBREAK * p
    cost[h_col] = HIT_COST

    rows = _Rows()
    by_pos = {pos: [p for p in pool if players[p].pos == pos] for pos in SQUAD_QUOTA}
    for pos, quota in SQUAD_QUOTA.items():
        rows.add({s_col[p]: 1 for p in by_pos[pos]}, quota, quota)
    for club in {players[p].team_id for p in pool}:
        rows.add({s_col[p]: 1 for p in pool if players[p].team_id == club}, 0, MAX_PER_CLUB)

    budget = sum(squad.selling.values()) + squad.bank
    buy_cost = {p: squad.selling[p] if p in squad_ids else players[p].price for p in pool}
    rows.add({s_col[p]: buy_cost[p] for p in pool}, 0, budget)

    for g in window:
        rows.add({x_col[p, g]: 1 for p in pool}, XI_SIZE, XI_SIZE)
        for pos, (lo, hi) in XI_RANGE.items():
            rows.add({x_col[p, g]: 1 for p in by_pos[pos]}, lo, hi)
        rows.add({c_col[p, g]: 1 for p in pool}, 1, 1)
        for p in pool:
            rows.add({x_col[p, g]: 1, s_col[p]: -1}, -np.inf, 0)
            rows.add({c_col[p, g]: 1, x_col[p, g]: -1}, -np.inf, 0)

    incoming = {s_col[p]: 1 for p in pool if p not in squad_ids}
    if max_transfers is not None:
        rows.add(incoming, 0, max_transfers)
        rows.add({**incoming, h_col: -1}, -np.inf, free_transfers)
    upper = np.ones(n_vars)
    upper[h_col] = 0 if max_transfers is None else sum(SQUAD_QUOTA.values())  # no hits on WC/FH
    result = milp(
        cost,
        constraints=rows.constraint(n_vars),
        integrality=np.ones(n_vars),
        bounds=Bounds(np.zeros(n_vars), upper),
        options={"mip_rel_gap": 0},
    )
    if result.status != 0 or result.x is None:
        raise RuntimeError(f"Squad optimiser failed: {result.message}")
    sol = np.round(result.x).astype(int)

    new_squad = [p for p in pool if sol[s_col[p]] == 1]
    transfers_in = sorted(set(new_squad) - squad_ids)
    transfers_out = sorted(squad_ids - set(new_squad))
    hit_cost = 0 if max_transfers is None else HIT_COST * max(0, len(transfers_in) - free_transfers)

    xi, captain, vice, bench_order = {}, {}, {}, {}
    raw_total = -float(hit_cost)
    for g in window:
        xi[g] = [p for p in new_squad if sol[x_col[p, g]] == 1]
        captain[g] = next(p for p in xi[g] if sol[c_col[p, g]] == 1)
        others = [p for p in xi[g] if p != captain[g]]
        vice[g] = min(others, key=lambda p: (-_captain_basis(projs, p, g), p))
        bench = [p for p in new_squad if p not in xi[g]]
        keepers = [p for p in bench if players[p].pos == "GKP"]
        outfield = sorted((p for p in bench if players[p].pos != "GKP"),
                          key=lambda p: (-_points(projs, p, g), p))
        bench_order[g] = keepers + outfield
        raw_total += sum(_points(projs, p, g) for p in xi[g]) + _points(projs, captain[g], g)

    log.info("Optimiser: pool %d, max_transfers %s, %d in, %.2fs",
             n, max_transfers, len(transfers_in), time.monotonic() - started)
    return Solution(new_squad, xi, captain, vice, bench_order, transfers_out,
                    transfers_in, hit_cost, raw_total)
