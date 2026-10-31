"""My squad state from the FPL API: selling prices, bank, chips."""
from dataclasses import dataclass

from brief.types import Player

CHIP_CODES = ["wildcard", "freehit", "bboost", "3xc"]
FIRST_HALF_LAST_GW = 19  # chips reset between GW1-19 and GW20-38


@dataclass(frozen=True)
class MySquad:
    """My current 15, what each sells for, money in the bank and chips left."""
    player_ids: list[int]
    selling: dict[int, float]
    bank: float
    chips_available: list[str]
    last_picks_gw: int


def selling_price(purchase: float, current: float) -> float:
    """FPL selling price: keep half of any rise (rounded down to 0.1), lose all of a fall."""
    rise_tenths = round((current - purchase) * 10)
    if rise_tenths <= 0:
        return current
    return round(purchase + (rise_tenths // 2) / 10, 1)


def _half(gw: int) -> int:
    """1 for GW1-19, 2 for GW20-38."""
    return 1 if gw <= FIRST_HALF_LAST_GW else 2


def _chips_available(chips: list[dict], target: int) -> list[str]:
    """Chip codes not yet used in the half-season containing `target`."""
    used = {c["name"] for c in chips if _half(c["event"]) == _half(target)}
    return [code for code in CHIP_CODES if code not in used]


def _latest_purchases(transfers: list[dict]) -> dict[int, float]:
    """Price (£m) of each player's most recent purchase."""
    latest: dict[int, tuple[int, float]] = {}
    for t in transfers:
        pid = t["element_in"]
        if pid not in latest or t["event"] > latest[pid][0]:
            latest[pid] = (t["event"], t["element_in_cost"] / 10)
    return {pid: price for pid, (_, price) in latest.items()}


def build_my_squad(
    history: dict,
    transfers: list[dict],
    picks: dict,
    players: dict[int, Player],
    gw1_prices: dict[int, float],
    target: int,
) -> MySquad:
    """Assemble my squad state from the entry history, transfers and picks payloads."""
    player_ids = sorted(p["element"] for p in picks["picks"])
    purchases = _latest_purchases(transfers)
    selling = {}
    for pid in player_ids:
        current = players[pid].price
        purchase = purchases.get(pid, gw1_prices.get(pid, current))
        selling[pid] = selling_price(purchase, current)
    latest_gw = max(history["current"], key=lambda row: row["event"])
    last_picks_gw = picks.get("entry_history", {}).get("event", latest_gw["event"])
    return MySquad(
        player_ids=player_ids,
        selling=selling,
        bank=latest_gw["bank"] / 10,
        chips_available=_chips_available(history.get("chips", []), target),
        last_picks_gw=last_picks_gw,
    )
