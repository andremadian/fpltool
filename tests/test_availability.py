"""Tests for injury availability rules."""
from datetime import date, datetime, timedelta, timezone

from brief.availability import (
    availability,
    can_buy,
    is_priority_sell,
    needs_doubt_note,
    parse_return_date,
)
from brief.types import Gameweek, Player

WINDOW = [1, 2, 3, 4, 5]
TODAY = date(2026, 10, 31)


def _gws() -> list[Gameweek]:
    """Weekly deadlines from 1 Nov 2026 at 11:00 UTC."""
    start = datetime(2026, 11, 1, 11, tzinfo=timezone.utc)
    return [Gameweek(i + 1, start + timedelta(weeks=i)) for i in range(5)]


def _p(status: str = "a", chance: int | None = None, news: str = "") -> Player:
    """Build a test player."""
    return Player(1, "Test", 1, "TST", "MID", 7.0, status, chance, news)


def test_available_player_full() -> None:
    assert availability(_p(), WINDOW, _gws(), TODAY) == [1, 1, 1, 1, 1]


def test_chance_75_target_only() -> None:
    assert availability(_p("d", 75), WINDOW, _gws(), TODAY) == [0.75, 1, 1, 1, 1]


def test_chance_0_no_date() -> None:
    assert availability(_p("i", 0), WINDOW, _gws(), TODAY) == [0, 0.5, 1, 1, 1]


def test_return_date_blocks_until_date() -> None:
    p = _p("i", 0, "Knee injury - Expected back 22 Nov")
    assert availability(p, WINDOW, _gws(), TODAY) == [0, 0, 0, 1, 1]


def test_suspension_one_gw() -> None:
    assert availability(_p("s"), WINDOW, _gws(), TODAY) == [0, 1, 1, 1, 1]


def test_suspension_length_from_news() -> None:
    p = _p("s", None, "Suspended for 3 matches")
    assert availability(p, WINDOW, _gws(), TODAY) == [0, 0, 0, 1, 1]


def test_left_or_loaned_zero() -> None:
    assert availability(_p("u"), WINDOW, _gws(), TODAY) == [0] * 5
    assert availability(_p("n"), WINDOW, _gws(), TODAY) == [0] * 5


def test_missing_gameweek_uses_no_date_rules() -> None:
    p = _p("i", 0, "Expected back 22 Nov")
    assert availability(p, WINDOW, _gws()[:3], TODAY) == [0, 0, 0, 1, 1]


def test_parse_return_date_formats_and_rollover() -> None:
    assert parse_return_date("Expected back 22 Nov", TODAY) == date(2026, 11, 22)
    assert parse_return_date("Back 22 November", TODAY) == date(2026, 11, 22)
    assert parse_return_date("Expected back 3 Jan", date(2026, 12, 20)) == date(2027, 1, 3)
    assert parse_return_date("Hamstring injury", TODAY) is None


def test_parse_return_date_recent_past_is_stale() -> None:
    """A date up to 120 days ago is stale news, not next year's return: no date at all."""
    assert parse_return_date("Expected back 20 Oct", TODAY) is None
    assert parse_return_date("Expected back 3 Jul", TODAY) is None  # exactly 120 days ago
    assert parse_return_date("Expected back 2 Jul", TODAY) == date(2027, 7, 2)  # 121 days: Dec→Jan-style roll


def test_stale_return_date_uses_no_date_rules() -> None:
    """A 0% player whose news date has passed falls back to the no-date rules."""
    p = _p("i", 0, "Knee injury - Expected back 20 Oct")
    assert availability(p, WINDOW, _gws(), TODAY) == [0, 0.5, 1, 1, 1]


def test_cannot_buy_50() -> None:
    assert not can_buy(_p("d", 50))
    assert not can_buy(_p("i"))
    assert can_buy(_p())


def test_can_buy_75_with_note() -> None:
    p = _p("d", 75)
    assert can_buy(p)
    assert needs_doubt_note(p)


def test_priority_sell_three_out() -> None:
    assert is_priority_sell([0, 0, 0, 1, 1])
    assert not is_priority_sell([0, 0, 0.5, 1, 1])
