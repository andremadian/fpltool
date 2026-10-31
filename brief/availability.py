"""Injury and suspension availability rules."""
import re
from datetime import date

from brief.types import Gameweek, Player

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
)}
_DATE_RE = re.compile(r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", re.I)
_BAN_RE = re.compile(r"(\d+)[\s-]*(?:match|game)", re.I)
# A news date that passed at most this many days ago is stale, not next year's.
STALE_NEWS_DAYS = 120


def parse_return_date(news: str, today: date) -> date | None:
    """Parse a return date like '22 Nov' from news; None if it passed within STALE_NEWS_DAYS.

    A date this year still ahead is used as is. One that passed recently is stale
    news (the player missed his return), so the no-date rules apply. Only a date
    long gone (the Dec→Jan case) rolls forward to next year.
    """
    found = _DATE_RE.search(news)
    if not found:
        return None
    day, month = int(found.group(1)), _MONTHS[found.group(2).lower()]
    try:
        this_year = date(today.year, month, day)
    except ValueError:
        this_year = None
    if this_year is not None:
        if this_year >= today:
            return this_year
        if (today - this_year).days <= STALE_NEWS_DAYS:
            return None
    try:
        return date(today.year + 1, month, day)
    except ValueError:
        return None


def _ban_length(news: str) -> int:
    """Return the suspension length in GWs from news (default 1)."""
    found = _BAN_RE.search(news)
    return max(int(found.group(1)), 1) if found else 1


def _no_date_rules(player: Player, size: int) -> list[float]:
    """Multipliers for a player with no usable return date."""
    if player.status == "s":
        out = [0.0] * _ban_length(player.news) + [1.0] * size
        return out[:size]
    chance = player.chance
    if chance is None:
        chance = 0 if player.status in ("i", "d") else 100
    if chance == 0:
        out = [0.0, 0.5] + [1.0] * size
    elif chance < 100:
        out = [chance / 100] + [1.0] * size
    else:
        out = [1.0] * size
    return out[:size]


def availability(
    player: Player, window: list[int], gameweeks: list[Gameweek], today: date
) -> list[float]:
    """Return one availability multiplier per GW in `window`."""
    size = len(window)
    if player.status in ("u", "n"):
        return [0.0] * size
    base = _no_date_rules(player, size)
    return_date = parse_return_date(player.news, today)
    if return_date is None:
        return base
    deadlines = {g.gw: g.deadline.date() for g in gameweeks}
    return [
        base[i] if gw not in deadlines
        else (0.0 if deadlines[gw] < return_date else 1.0)
        for i, gw in enumerate(window)
    ]


def can_buy(player: Player) -> bool:
    """False if the player is too doubtful or unavailable to recommend buying."""
    if player.chance is not None and player.chance <= 50:
        return False
    return player.status not in ("i", "s", "u", "n")


def needs_doubt_note(player: Player) -> bool:
    """True when a 75% player is buyable but deserves a caveat."""
    return player.chance == 75


def is_priority_sell(mults: list[float]) -> bool:
    """True when the player is fully out for three or more GWs."""
    return sum(1 for m in mults if m == 0.0) >= 3
