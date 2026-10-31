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



FH_SQUAD = [4, 5, 11, 12, 13, 14, 15, 23, 24, 25, 26, 27, 37, 38, 39]


def _chip_picks(ids: list[int], captain: int, chip: str | None) -> dict:
    """A picks payload as the API returns it with `chip` active (multipliers included)."""
    out = _picks(ids, captain)
    out["active_chip"] = chip
    for pick in out["picks"]:
        if chip == "3xc" and pick["is_captain"]:
            pick["multiplier"] = 3
        if chip == "bboost" and pick["position"] > 11:
            pick["multiplier"] = 1
    return out


def test_build_rivals_resets_last_gw_chips(monkeypatch: pytest.MonkeyPatch) -> None:
    """3xc and bboost from target-1 don't carry into the target GW; a Free Hit is stepped past."""
    def fetch(entry_id: int, gw: int) -> dict | None:
        """Rival 200 on 3xc, 300 on bboost, 400 on Free Hit in GW9 (normal squad in GW8)."""
        if entry_id == 200:
            return _chip_picks(RIVAL_SQUAD, 34, "3xc")
        if entry_id == 300:
            return _chip_picks(RIVAL_SQUAD, 34, "bboost")
        return _chip_picks(FH_SQUAD, 37, "freehit") if gw == 9 else _picks(RIVAL_SQUAD, 34)
    monkeypatch.setattr(fpl_api, "fetch_entry_picks", fetch)
    standings = [{"entry": e, "entry_name": "", "player_name": "", "rank": i, "total": 0}
                 for i, e in enumerate((200, 300, 400, MY_ENTRY), start=1)]

    rivals = fpl_brief_engine.build_rivals(standings, MY_ENTRY, _picks(SQUAD_IDS, 31), TARGET)

    for r in rivals:
        assert r.chip is None
        for pick in r.picks:
            assert pick["multiplier"] == (2 if pick["is_captain"] else 1 if pick["position"] <= 11 else 0)
    by_id = {r.entry_id: r for r in rivals}
    assert sorted(p["element"] for p in by_id[400].picks) == sorted(RIVAL_SQUAD)


def test_rival_projection_ignores_last_gw_chip(faked: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rival who played 3xc in GW9 projects the same for GW10 as one who didn't."""
    plain = fpl_brief_engine.run(object(), NOW)
    monkeypatch.setattr(fpl_api, "fetch_entry_picks", lambda e, gw: (
        _chip_picks(RIVAL_SQUAD, 34, "3xc") if e == 200 else _fetch_picks(e, gw)))

    chipped = fpl_brief_engine.run(object(), NOW)

    def proj(payload: dict) -> float:
        """Rival 200's projected points."""
        return next(r["projected_points"] for r in payload["rivals"] if r["entry_id"] == 200)
    assert proj(chipped) == proj(plain)


def test_my_free_hit_uses_pre_free_hit_squad_and_bank(faked: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """If I Free Hit in GW9, the brief plans from my GW8 squad and GW8 bank."""
    monkeypatch.setattr(fpl_api, "fetch_entry_history", lambda e: {
        "current": [{"event": gw, "bank": 0 if gw == 9 else 20} for gw in range(1, TARGET)],
        "chips": [{"name": "freehit", "event": 9}]})
    monkeypatch.setattr(fpl_api, "fetch_entry_picks", lambda e, gw: (
        (_chip_picks(FH_SQUAD, 37, "freehit") if gw == 9 else _picks(SQUAD_IDS, 31))
        if e == MY_ENTRY else _fetch_picks(e, gw)))

    payload = fpl_brief_engine.run(object(), NOW)

    assert sorted(payload["inputs"]["squad_ids"]) == sorted(SQUAD_IDS)
    assert payload["inputs"]["bank"] == 2.0


def test_target_gw1_is_preseason(faked: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Before the GW1 deadline there is nothing to brief: PreSeason, not a failure."""
    monkeypatch.setattr(fpl_brief_engine, "target_gw", lambda gameweeks, now: 1)

    with pytest.raises(fpl_brief_engine.PreSeason):
        fpl_brief_engine.run(object(), NOW)


def test_no_picks_for_me_is_preseason(faked: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """No locked picks for my entry yet is a pre-season skip."""
    monkeypatch.setattr(fpl_api, "fetch_entry_picks", lambda e, gw: None)

    with pytest.raises(fpl_brief_engine.PreSeason):
        fpl_brief_engine.run(object(), NOW)


class _FakeSb:
    """Records inserts per table; reads return nothing."""

    def __init__(self) -> None:
        """No inserts yet."""
        self.inserts: list[tuple[str, dict]] = []
        self._table = ""

    def table(self, name: str) -> "_FakeSb":
        """Select a table."""
        self._table = name
        return self

    def insert(self, row: dict) -> "_FakeSb":
        """Record an insert."""
        self.inserts.append((self._table, row))
        return self

    def execute(self) -> None:
        """No-op."""


MINI_PAYLOAD = {"season": "2026/27", "gw": TARGET, "window": [10], "scenarios": {}, "rivals": [],
                "mode": {"kind": "defend", "my_rank": 1, "my_total": 500, "gap": -5, "target": None}}


@pytest.fixture
def main_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> tuple[_FakeSb, list[bool]]:
    """main() wired to a fake Supabase, recorded pings and a temp dry-run path."""
    sb, pings = _FakeSb(), []
    monkeypatch.setattr(fpl_brief_engine, "get_supabase_client", lambda: sb)
    monkeypatch.setattr(fpl_brief_engine, "wait_for_supabase", lambda s: None)
    monkeypatch.setattr(fpl_brief_engine, "assert_schema", lambda s, checks=None: None)
    monkeypatch.setattr(fpl_brief_engine, "ping_healthcheck", lambda ok: pings.append(ok))
    monkeypatch.setattr(fpl_brief_engine, "DRY_RUN_PATH", tmp_path / "dry.json")
    return sb, pings


def test_main_failure_logs_failed_and_pings_fail(main_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """A run error records status=failed, pings /fail and exits 1."""
    sb, pings = main_env
    def boom(sb: object, now: datetime) -> dict:
        """Fail like a network error would."""
        raise RuntimeError("FPL down")
    monkeypatch.setattr(fpl_brief_engine, "run", boom)
    monkeypatch.setattr("sys.argv", ["fpl_brief_engine.py"])

    with pytest.raises(SystemExit) as exit_info:
        fpl_brief_engine.main()

    assert exit_info.value.code == 1
    assert [(t, r["status"]) for t, r in sb.inserts] == [("pipeline_runs", "failed")]
    assert "FPL down" in sb.inserts[0][1]["detail"]
    assert pings == [False]


def test_main_success_inserts_brief(main_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal run inserts the brief, logs success with rows_written=1 and pings OK."""
    sb, pings = main_env
    monkeypatch.setattr(fpl_brief_engine, "run", lambda sb, now: MINI_PAYLOAD)
    monkeypatch.setattr("sys.argv", ["fpl_brief_engine.py"])

    fpl_brief_engine.main()

    assert [t for t, _ in sb.inserts] == ["weekly_brief", "pipeline_runs"]
    assert sb.inserts[0][1]["mode"] == "defend"
    assert sb.inserts[1][1]["status"] == "success" and sb.inserts[1][1]["rows_written"] == 1
    assert pings == [True]


def test_main_dry_run_writes_nothing(main_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """--dry-run writes the JSON file only: no insert, no pipeline_runs, no ping."""
    sb, pings = main_env
    monkeypatch.setattr(fpl_brief_engine, "run", lambda sb, now: MINI_PAYLOAD)
    monkeypatch.setattr("sys.argv", ["fpl_brief_engine.py", "--dry-run"])

    fpl_brief_engine.main()

    assert sb.inserts == [] and pings == []
    assert fpl_brief_engine.DRY_RUN_PATH.exists()


def test_main_preseason_is_ok_skip(main_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-season records skipped_preseason and pings OK (no daily /fail spam)."""
    sb, pings = main_env
    def early(sb: object, now: datetime) -> dict:
        """Signal pre-season."""
        raise fpl_brief_engine.PreSeason("2026/27", "before the GW1 deadline")
    monkeypatch.setattr(fpl_brief_engine, "run", early)
    monkeypatch.setattr("sys.argv", ["fpl_brief_engine.py"])

    fpl_brief_engine.main()

    assert [(t, r["status"], r["season"]) for t, r in sb.inserts] == [
        ("pipeline_runs", "skipped_preseason", "2026/27")]
    assert pings == [True]
