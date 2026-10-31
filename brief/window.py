"""Target gameweek and planning-window resolution."""
from datetime import datetime

from brief.types import Gameweek


def target_gw(gameweeks: list[Gameweek], now: datetime) -> int:
    """Return the first GW whose deadline is after `now` (last GW if none)."""
    for gw in sorted(gameweeks, key=lambda g: g.gw):
        if gw.deadline > now:
            return gw.gw
    return max(g.gw for g in gameweeks)


def window_gws(target: int, last_gw: int = 38, size: int = 5) -> list[int]:
    """Return the GWs from `target` onward, capped at `last_gw`."""
    return list(range(target, min(target + size - 1, last_gw) + 1))
