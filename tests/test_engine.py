"""End-to-end test of fpl_brief_engine.run with the FPL API and Supabase loaders faked."""
from datetime import datetime, timedelta, timezone

import pytest
import requests

import fpl_brief_engine
from brief import data, fpl_api
from brief.types import Fixture, HistoryRow
from tests.conftest import POSITIONS, PRICES, SQUAD_IDS, club_of

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
TARGET = 10
SEASON_START = datetime(2026, 8, 21, 17, 30, tzinfo=timezone.utc)
MY_ENTRY = 100
LEAGUE_ID = 7
ELEMENT_TYPES = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}


def _deadline(gw: int) -> datetime:
    """Weekly deadlines with GW10's falling just after NOW."""
    return NOW + timedelta(days=1) + timedelta(weeks=gw - TARGET)


def _bootstrap() -> dict:
    """A 38-GW, 8-club, 40-player bootstrap-static."""
    events = [{"id": gw, "deadline_time": _deadline(gw).isoformat().replace("+00:00", "Z"),
               "finished": gw < TARGET} for gw in range(1, 39)]
    events[0]["deadline_time"] = SEASON_START.isoformat().replace("+00:00", "Z")
    teams = [{"id": c, "short_name": f"C{c}"} for c in range(1, 9)]
    elements = []
    for pos, ids in POSITIONS.items():
        for pid in ids:
            elements.append({
                "id": pid, "web_name": f"P{pid}", "team": club_of(pid),
                "element_type": ELEMENT_TYPES[pos], "now_cost": int(PRICES[pos] * 10),
                "status": "i" if pid == 8 else "a",
                "chance_of_playing_next_round": 0 if pid == 8 else None,
                "news": "Knee injury - Expected back 20 Dec" if pid == 8 else "",
            })
    return {"events": events, "teams": teams, "elements": elements}


def _fixtures(sb: object, season: str) -> list[Fixture]:
    """Clubs 1v2, 3v4, 5v6, 7v8 every GW, alternating home side."""
    out = []
    for gw in range(1, 39):
        for home, away in ((1, 2), (3, 4), (5, 6), (7, 8)):
            if gw % 2:
                home, away = away, home
            out.append(Fixture(gw, home, away, True))
            out.append(Fixture(gw, away, home, False))
    return out


def _history(sb: object, season: str) -> list[HistoryRow]:
    """GW1-9 rows for everyone; squad players score more than the rest."""
    rows = []
    for pos, ids in POSITIONS.items():
        for pid in ids:
            strong = pid in SQUAD_IDS
            for gw in range(1, TARGET):
                rows.append(HistoryRow(
                    player_id=pid, gw=gw, minutes=90, total_points=6 if strong else 2,
                    xg=0.4 if strong and pos in ("MID", "FWD") else 0.05,
                    xa=0.2 if strong else 0.02, xgc=1.0, bps=20 if strong else 8, cbit=8,
                    goals=0, assists=0, clean_sheets=0, price=PRICES[pos],
                ))
    return rows


def _picks(ids: list[int], captain: int) -> dict:
    """A picks payload for a 15-man squad."""
    return {"active_chip": None, "entry_history": {"event": TARGET - 1},
            "picks": [{"element": pid, "position": i + 1, "multiplier": 2 if pid == captain else 1,
                       "is_captain": pid == captain, "is_vice_captain": False}
                      for i, pid in enumerate(ids)]}


RIVAL_SQUAD = [3, 4, 11, 12, 13, 14, 15, 23, 24, 25, 26, 27, 34, 35, 36]


def _fetch_picks(entry_id: int, gw: int) -> dict | None:
    """Me and the leader have GW9 picks; one rival has none yet; one errors."""
    if entry_id == 400:
        raise requests.ConnectionError("dropped")
    if gw != TARGET - 1 or entry_id == 300:
        return None
    if entry_id == MY_ENTRY:
        return _picks(SQUAD_IDS, 31)
    return _picks(RIVAL_SQUAD, 34)


@pytest.fixture
def faked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every network and Supabase read the engine makes."""
    monkeypatch.setattr(fpl_api, "fetch_bootstrap", _bootstrap)
    monkeypatch.setattr(fpl_api, "fetch_entry_history", lambda e: {
        "current": [{"event": gw, "bank": 20} for gw in range(1, TARGET)], "chips": []})
    monkeypatch.setattr(fpl_api, "fetch_entry_transfers", lambda e: [])
    monkeypatch.setattr(fpl_api, "fetch_entry_picks", _fetch_picks)
    monkeypatch.setattr(fpl_api, "fetch_league_standings", lambda league: [
        {"entry": 200, "entry_name": "Leaders", "player_name": "Budi", "rank": 1, "total": 600},
        {"entry": 300, "entry_name": "New Guy", "player_name": "Citra", "rank": 2, "total": 580},
        {"entry": MY_ENTRY, "entry_name": "Me FC", "player_name": "Andre", "rank": 3, "total": 570},
        {"entry": 400, "entry_name": "Flaky", "player_name": "Dewi", "rank": 4, "total": 500},
    ])
    monkeypatch.setattr(data, "load_history", _history)
    monkeypatch.setattr(data, "load_fixtures", _fixtures)
    monkeypatch.setattr(data, "load_flags", lambda sb, season: [])
    monkeypatch.setattr(data, "load_tracked_league", lambda sb: (LEAGUE_ID, MY_ENTRY))


def test_run_end_to_end_with_fakes(faked: None) -> None:
    """A rank-3 entry gets a chase brief with 15 scenarios and legal XIs."""
    payload = fpl_brief_engine.run(object(), NOW)

    assert payload["season"] == "2026/27"
    assert payload["gw"] == TARGET
    assert payload["window"] == [10, 11, 12, 13, 14]
    assert len(payload["scenarios"]) == 15
    assert payload["mode"]["kind"] == "chase"
    assert payload["mode"]["target"]["entry_id"] == 300
    assert payload["mode"]["gap"] == 10
    for block in payload["scenarios"].values():
        assert len(block["xi"]) == 11
        assert block["captain"]["id"] in {p["id"] for p in block["xi"]}
    assert sorted(payload["inputs"]["squad_ids"]) == sorted(SQUAD_IDS)
    assert 8 in payload["inputs"]["flagged_ids"]
    rivals = {r["entry_id"]: r for r in payload["rivals"]}
    assert rivals[300]["projected_points"] is None  # no picks yet
    assert rivals[400]["projected_points"] is None  # fetch error is skipped, not fatal
    assert rivals[200]["projected_points"] is not None


def test_injured_squad_player_is_priority_sell(faked: None) -> None:
    """A squad player out until December is a priority sell unless he is sold."""
    payload = fpl_brief_engine.run(object(), NOW)

    block = payload["scenarios"]["1_0"]
    sold = {t["out"]["id"] for t in block["transfers"]}
    listed = {s["player"]["id"] for s in block["priority_sells"]}
    assert 8 in sold | listed


def test_season_complete_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every GW finished means there is no brief to build."""
    boot = _bootstrap()
    for event in boot["events"]:
        event["finished"] = True
    monkeypatch.setattr(fpl_api, "fetch_bootstrap", lambda: boot)

    with pytest.raises(fpl_brief_engine.SeasonComplete):
        fpl_brief_engine.run(object(), NOW)


def test_missing_my_entry_raises(faked: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """If I'm not in the league standings the run fails with a clear message."""
    monkeypatch.setattr(fpl_api, "fetch_league_standings", lambda league: [
        {"entry": 200, "entry_name": "Leaders", "player_name": "Budi", "rank": 1, "total": 600},
    ])

    with pytest.raises(RuntimeError, match="not in league"):
        fpl_brief_engine.run(object(), NOW)


def test_gw1_prices_use_earliest_row() -> None:
    """Purchase price of an original pick is his price in his first history row."""
    rows = [HistoryRow(5, gw, 90, 2, 0, 0, 0, 0, 0, 0, 0, 0, price)
            for gw, price in ((3, 5.2), (1, 5.0), (2, 5.1))]

    assert fpl_brief_engine.gw1_prices(rows) == {5: 5.0}

