"""Tests for my-squad state: selling prices, bank, chips."""
from brief.squad import build_my_squad, selling_price
from brief.types import Player


def _player(pid: int, price: float) -> Player:
    """A minimal fit player at `price`."""
    return Player(pid, f"P{pid}", 1, "C1", "MID", price, "a", None, "")


def test_selling_price_rounds_down() -> None:
    """Half the rise is kept, rounded down to 0.1; a fall is passed on in full."""
    assert selling_price(5.0, 5.3) == 5.1
    assert selling_price(5.0, 4.8) == 4.8
    assert selling_price(4.4, 4.6) == 4.5


def test_chips_by_half() -> None:
    """A chip used in GW3 is gone for the first half and back for the second."""
    history = {"current": [{"event": 9, "bank": 15}], "chips": [{"name": "wildcard", "event": 3}]}
    picks = {"picks": [], "entry_history": {"event": 9}}
    first = build_my_squad(history, [], picks, {}, {}, target=10)
    second = build_my_squad(history, [], picks, {}, {}, target=20)
    assert first.chips_available == ["freehit", "bboost", "3xc"]
    assert second.chips_available == ["wildcard", "freehit", "bboost", "3xc"]


def test_build_my_squad_prices_bank_and_gw() -> None:
    """Latest purchase wins, else the GW1 price, else current; bank from the latest GW."""
    players = {1: _player(1, 6.0), 2: _player(2, 8.3), 3: _player(3, 5.0)}
    picks = {"picks": [{"element": 2, "position": 2}, {"element": 1, "position": 1},
                       {"element": 3, "position": 3}]}
    history = {"current": [{"event": 8, "bank": 3}, {"event": 9, "bank": 12}], "chips": []}
    transfers = [
        {"element_in": 2, "element_in_cost": 75, "element_out": 9, "event": 4},
        {"element_in": 2, "element_in_cost": 80, "element_out": 9, "event": 7},
    ]
    squad = build_my_squad(history, transfers, picks, players, {1: 5.5}, target=10)
    assert squad.player_ids == [1, 2, 3]
    assert squad.selling == {1: 5.7, 2: 8.1, 3: 5.0}
    assert squad.bank == 1.2
    assert squad.last_picks_gw == 9
