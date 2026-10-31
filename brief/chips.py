"""Chip evaluation: when Triple Captain, Bench Boost, Free Hit and Wildcard pay off."""
import logging
from dataclasses import dataclass

from brief.model import Projection
from brief.optimise import Solution, optimise
from brief.squad import CHIP_CODES, MySquad
from brief.types import Player

log = logging.getLogger(__name__)

CHIP_THRESHOLDS = {"3xc": 6.0, "bboost": 8.0, "freehit": 10.0, "wildcard": 12.0}


@dataclass(frozen=True)
class ChipAdvice:
    """One chip's value now and at its best slot in the window."""
    chip: str
    gain_now: float
    best_gw: int
    gain_best: float
    play_now: bool
    reason: str


def solve_freehit(
    projs: dict[int, Projection],
    players: dict[int, Player],
    squad: MySquad,
    target: int,
    buyable: set[int] | None = None,
) -> Solution:
    """Best one-GW squad for `target` with unlimited free transfers."""
    return optimise(projs, players, squad, [target], None, 0, buyable=buyable)


def solve_wildcard(
    projs: dict[int, Projection],
    players: dict[int, Player],
    squad: MySquad,
    window: list[int],
    buyable: set[int] | None = None,
) -> Solution:
    """Best squad over the whole window with unlimited free transfers."""
    return optimise(projs, players, squad, window, None, 0, buyable=buyable)


def _pts(projs: dict[int, Projection], pid: int, gw: int) -> float:
    """Projected points for `pid` in `gw` (0 when there is no projection)."""
    proj = projs.get(pid)
    return proj.points.get(gw, 0.0) if proj else 0.0


def _xi_total(sol: Solution, projs: dict[int, Projection], gw: int) -> float:
    """XI points plus the extra captain multiple for `gw`."""
    return sum(_pts(projs, p, gw) for p in sol.xi[gw]) + _pts(projs, sol.captain[gw], gw)


def _best_gw(gains: dict[int, float], window: list[int]) -> int:
    """Window GW with the highest gain (earliest on ties)."""
    return max(window, key=lambda g: (gains[g], -g))


def _timing_advice(chip: str, gains: dict[int, float], window: list[int], target: int, reason_now) -> ChipAdvice:
    """Advice for a chip whose value can be compared across window GWs."""
    best = _best_gw(gains, window)
    gain_now, gain_best = gains[target], gains[best]
    play_now = best == target and round(gain_now, 1) >= CHIP_THRESHOLDS[chip]
    reason = reason_now(gain_now, best, gain_best) + (" — play now." if play_now else " — hold.")
    return ChipAdvice(chip, round(gain_now, 1), best, round(gain_best, 1), play_now, reason)


def evaluate_chips(
    available: list[str],
    scenario: Solution,
    projs: dict[int, Projection],
    window: list[int],
    freehit: Solution | None,
    wildcard: Solution | None,
    players: dict[int, Player],
) -> list[ChipAdvice]:
    """Advice for each available chip, in CHIP_CODES order (Free Hit / Wildcard need a solution)."""
    target = window[0]
    out: list[ChipAdvice] = []
    for chip in CHIP_CODES:
        if chip not in available:
            continue
        if chip == "3xc":
            gains = {g: _pts(projs, scenario.captain[g], g) for g in window}
            name = players[scenario.captain[target]].name if scenario.captain[target] in players else "your captain"
            out.append(_timing_advice(chip, gains, window, target, lambda now, gw, best: (
                f"Triple Captain on {name} adds {now:.1f} this GW; best in window GW{gw} (+{best:.1f})."
            )))
        elif chip == "bboost":
            gains = {g: sum(_pts(projs, p, g) for p in scenario.bench_order[g]) for g in window}
            out.append(_timing_advice(chip, gains, window, target, lambda now, gw, best: (
                f"Bench Boost adds {now:.1f} this GW; best GW{gw} (+{best:.1f})."
            )))
        elif chip == "freehit" and freehit is not None:
            gain = round(_xi_total(freehit, projs, target) - _xi_total(scenario, projs, target), 1)
            play_now = gain >= CHIP_THRESHOLDS[chip]
            reason = f"Free Hit squad beats your XI by {gain:.1f} this GW." + (" — play now." if play_now else " — hold.")
            out.append(ChipAdvice(chip, gain, target, gain, play_now, reason))
        elif chip == "wildcard" and wildcard is not None:
            gain = round(wildcard.raw_total - scenario.raw_total, 1)
            play_now = gain >= CHIP_THRESHOLDS[chip]
            reason = (f"Wildcard gains {gain:.1f} over {len(window)} GWs vs your best transfers."
                      + (" — play now." if play_now else " — hold."))
            out.append(ChipAdvice(chip, gain, target, gain, play_now, reason))
    log.info("Evaluated chips: %s", [(a.chip, a.gain_now, a.play_now) for a in out])
    return out
