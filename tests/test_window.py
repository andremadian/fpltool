"""Tests for target GW and window resolution."""
from datetime import datetime, timezone

from brief.types import Gameweek
from brief.window import target_gw, window_gws


def test_target_gw_first_future_deadline() -> None:
    """The target is the first GW whose deadline is still ahead."""
    gws = [
        Gameweek(1, datetime(2026, 10, 25, 11, tzinfo=timezone.utc)),
        Gameweek(2, datetime(2026, 11, 1, 11, tzinfo=timezone.utc)),
        Gameweek(3, datetime(2026, 11, 8, 11, tzinfo=timezone.utc)),
    ]
    now = datetime(2026, 10, 31, 9, tzinfo=timezone.utc)
    assert target_gw(gws, now) == 2


def test_window_capped_at_38() -> None:
    """The window never runs past GW38."""
    assert window_gws(36) == [36, 37, 38]
    assert window_gws(10) == [10, 11, 12, 13, 14]
