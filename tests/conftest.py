"""Shared pytest setup: make the repo root importable, plus a synthetic FPL world.

The synthetic world is a 40-player pool across 8 clubs, a legal 15-man squad
within budget, and projections over a 5-GW window. Squad players out-project
every non-squad player, so the default world never wants a transfer; tests
override single projections with `make_proj` to create a reason to move.
"""
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brief.model import Projection  # noqa: E402
from brief.squad import MySquad  # noqa: E402
from brief.types import Player  # noqa: E402

WINDOW = [10, 11, 12, 13, 14]
POSITIONS = {"GKP": range(1, 6), "DEF": range(6, 18), "MID": range(18, 31), "FWD": range(31, 41)}
PRICES = {"GKP": 4.5, "DEF": 5.0, "MID": 7.0, "FWD": 8.0}
SQUAD_IDS = [1, 2, 6, 7, 8, 9, 10, 18, 19, 20, 21, 22, 31, 32, 33]
BANK = 2.0


def club_of(player_id: int) -> int:
    """Club id 1-8 for a synthetic player."""
    return player_id % 8 + 1


def _squad_points(player_id: int, pos: str) -> float:
    """Per-GW projection for a squad player: clearly above every non-squad player."""
    if pos == "GKP":
        return 4.0 if player_id == 1 else 3.0
    base = {"DEF": 4.0, "MID": 5.0, "FWD": 5.5}[pos]
    return base + 0.05 * (SQUAD_IDS.index(player_id) % 5)


@pytest.fixture
def window() -> list[int]:
    """The 5-GW planning window."""
    return list(WINDOW)


@pytest.fixture
def players() -> dict[int, Player]:
    """40 fit players across 8 clubs: 5 GKP, 12 DEF, 13 MID, 10 FWD."""
    pool = {}
    for pos, ids in POSITIONS.items():
        for pid in ids:
            club = club_of(pid)
            pool[pid] = Player(pid, f"P{pid}", club, f"C{club}", pos, PRICES[pos], "a", None, "")
    return pool


@pytest.fixture
def make_proj(window: list[int]) -> Callable[..., Projection]:
    """Factory: a Projection for `player_id` with `pts` every GW, or a per-GW dict."""
    def _make(player_id: int, pts: float | dict[int, float]) -> Projection:
        """Build one projection; captain basis equals points."""
        points = dict(pts) if isinstance(pts, dict) else {g: float(pts) for g in window}
        return Projection(player_id, points, dict(points), {g: 90.0 for g in window})
    return _make


@pytest.fixture
def projs(players: dict[int, Player], make_proj: Callable[..., Projection]) -> dict[int, Projection]:
    """Projections for all 40 players; squad players out-project the rest."""
    out = {}
    for pid, player in players.items():
        if pid in SQUAD_IDS:
            out[pid] = make_proj(pid, _squad_points(pid, player.pos))
        else:
            out[pid] = make_proj(pid, 2.0 + 0.01 * pid)
    return out


@pytest.fixture
def my_squad(players: dict[int, Player]) -> MySquad:
    """A legal 15-man squad (93.0 at selling value) with 2.0 in the bank."""
    selling = {pid: players[pid].price for pid in SQUAD_IDS}
    return MySquad(list(SQUAD_IDS), selling, BANK, ["wildcard", "freehit", "bboost", "3xc"], 9)
