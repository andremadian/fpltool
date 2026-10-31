"""Tests for the brief data layer, using fakes (no network, no Supabase)."""
from datetime import date
from decimal import Decimal

from brief import fpl_api
from brief.data import load_fixtures, load_flags, load_history


class FakeQuery:
    """Records order() calls and serves pre-baked pages from range()."""

    def __init__(self, pages: list[list[dict]]):
        self.pages = pages
        self.orders: list[str] = []
        self.ranges: list[tuple[int, int]] = []

    def select(self, *_): return self
    def eq(self, *_): return self
    def order(self, col): self.orders.append(col); return self

    def range(self, a, b):
        self.ranges.append((a, b))
        return self

    def execute(self):
        idx = len(self.ranges) - 1
        data = self.pages[idx] if idx < len(self.pages) else []
        return type("R", (), {"data": data})()


class FakeSB:
    """Fake Supabase client returning one FakeQuery."""

    def __init__(self, pages):
        self.q = FakeQuery(pages)

    def table(self, _): return self.q


def _row(pid: int, gw: int, xgc=None) -> dict:
    return {"player_id": pid, "gw": gw, "minutes": 90, "total_points": 6,
            "goals": 1, "assists": 0, "clean_sheets": 1, "xg": Decimal("0.45"),
            "xa": Decimal("0.1"), "xgi": Decimal("0.55"), "bps": 30, "cbit": None,
            "price": Decimal("6.5"), "xgc": xgc}


def test_load_history_orders_pages() -> None:
    page1 = [_row(1, g) for g in range(1, 1001)]
    page2 = [_row(2, 1, xgc=Decimal("1.2"))]
    sb = FakeSB([page1, page2])
    rows = load_history(sb, "2026/27")
    assert sb.q.orders[:2] == ["player_id", "gw"]
    assert len(rows) == 1001
    assert sb.q.ranges == [(0, 999), (1000, 1999)]
    assert rows[0].xgc == 0.0 and isinstance(rows[0].xgc, float)
    assert isinstance(rows[0].xg, float) and isinstance(rows[0].cbit, int)
    assert rows[-1].xgc == 1.2 and rows[-1].price == 6.5


def test_load_fixtures_two_sides_skips_null_gw() -> None:
    sb = FakeSB([[
        {"id": 1, "gw": 3, "home_team_id": 10, "away_team_id": 11},
        {"id": 2, "gw": None, "home_team_id": 12, "away_team_id": 13},
    ]])
    fx = load_fixtures(sb, "2026/27")
    assert [(f.team_id, f.opp_id, f.home) for f in fx] == [(10, 11, True), (11, 10, False)]


def test_load_flags_parses_dates() -> None:
    sb = FakeSB([[{"player_id": 1, "as_of_date": "2026-10-30", "status": "d",
                   "chance_of_playing_next_round": 50}]])
    flag = load_flags(sb, "2026/27")[0]
    assert flag.as_of_date == date(2026, 10, 30) and flag.chance == 50


def test_players_from_bootstrap() -> None:
    bs = {"teams": [{"id": 1, "short_name": "ARS"}],
          "elements": [
              {"id": 7, "web_name": "Saka", "team": 1, "element_type": 3, "now_cost": 101,
               "status": "a", "chance_of_playing_next_round": None, "news": ""},
              {"id": 8, "web_name": "Old", "team": 1, "element_type": 4, "now_cost": 50}]}
    players = fpl_api.players_from_bootstrap(bs, {7})
    assert list(players) == [7]
    assert players[7].pos == "MID" and players[7].price == 10.1 and players[7].team_short == "ARS"


def test_fetch_entry_picks_404_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(fpl_api, "_sleep", lambda: None)
    monkeypatch.setattr(fpl_api.requests, "get",
                        lambda *a, **k: type("R", (), {"status_code": 404})())
    assert fpl_api.fetch_entry_picks(1, 5) is None


def test_standings_paginates(monkeypatch) -> None:
    monkeypatch.setattr(fpl_api, "_sleep", lambda: None)
    pages = {1: {"standings": {"has_next": True, "results": [
                {"entry": 1, "entry_name": "a", "player_name": "A", "rank": 1, "total": 9, "x": 0}]}},
             2: {"standings": {"has_next": False, "results": [
                {"entry": 2, "entry_name": "b", "player_name": "B", "rank": 2, "total": 8}]}}}

    def fake_get(url, timeout):
        page = int(url.rsplit("=", 1)[1])
        return type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: pages[page]})()

    monkeypatch.setattr(fpl_api.requests, "get", fake_get)
    rows = fpl_api.fetch_league_standings(99)
    assert [r["entry"] for r in rows] == [1, 2] and "x" not in rows[0]
