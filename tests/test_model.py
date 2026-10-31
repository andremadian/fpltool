"""Tests for the projection model (v4) and set-piece resolution."""
from datetime import date, datetime, timedelta, timezone

import pytest

from brief import model
from brief.model import project_all
from brief.set_pieces import resolve_set_pieces
from brief.types import Fixture, FlagRow, Gameweek, HistoryRow, Player

TODAY = date(2026, 10, 31)
PAST = list(range(1, 11))      # GW1-10 played
WINDOW = [11, 12, 13, 14, 15]  # target GW11 + next 4
TEAMS = {1: "AAA", 2: "BBB", 3: "CCC", 4: "DDD"}


def _gameweeks() -> list[Gameweek]:
    """Weekly deadlines: GW1 on 28 Aug 2026, so GW11 (6 Nov) is the first in the future."""
    start = datetime(2026, 8, 28, 17, 30, tzinfo=timezone.utc)
    return [Gameweek(gw, start + timedelta(weeks=gw - 1)) for gw in range(1, 39)]


def _pair(gw: int, home: int, away: int) -> list[Fixture]:
    """Both sides of one fixture."""
    return [Fixture(gw, home, away, True), Fixture(gw, away, home, False)]


def _fixtures(skip: set[tuple[int, int]] = frozenset(), extra: list[Fixture] = ()) -> list[Fixture]:
    """1 v 2 and 3 v 4 every GW (home side alternates), minus skipped (gw, team) pairs."""
    out: list[Fixture] = []
    for gw in PAST + WINDOW:
        flip = gw % 2 == 0
        out += _pair(gw, 2, 1) if flip else _pair(gw, 1, 2)
        out += _pair(gw, 4, 3) if flip else _pair(gw, 3, 4)
    out = [f for f in out if (f.gw, f.team_id) not in skip and (f.gw, f.opp_id) not in skip]
    return out + list(extra)


def _player(pid: int, team: int, pos: str, price: float = 5.0, name: str | None = None,
            status: str = "a", chance: int | None = None) -> Player:
    """Build a test player."""
    return Player(pid, name or f"P{pid}", team, TEAMS.get(team, "ZZZ"), pos, price, status, chance, "")


def _rows(pid: int, gws: list[int], minutes: int = 90, points: int | list[int] = 2,
          xg: float = 0.0, xa: float = 0.0, xgc: float = 1.2, bps: int = 15, cbit: int = 5,
          goals: int | list[int] = 0) -> list[HistoryRow]:
    """History rows for one player over `gws`; list arguments give per-GW values."""
    rows = []
    for i, gw in enumerate(gws):
        pts = points[i] if isinstance(points, list) else points
        gl = goals[i] if isinstance(goals, list) else goals
        rows.append(HistoryRow(pid, gw, minutes, pts, xg, xa, xgc if minutes else 0.0,
                               bps, cbit, gl, 0, 0, 5.0))
    return rows


def _fillers() -> tuple[dict[int, Player], list[HistoryRow]]:
    """A nailed GKP/DEF/MID/FWD on every team: sets positional medians and team strength."""
    players: dict[int, Player] = {}
    history: list[HistoryRow] = []
    shapes = {"GKP": (3, 0.0, 0.0), "DEF": (3, 0.05, 0.05), "MID": (4, 0.2, 0.15), "FWD": (4, 0.4, 0.1)}
    pid = 900
    for team in TEAMS:
        for pos, (pts, xg, xa) in shapes.items():
            players[pid] = _player(pid, team, pos)
            history += _rows(pid, PAST, points=pts, xg=xg, xa=xa)
            pid += 1
    return players, history


def _project(players: dict[int, Player], history: list[HistoryRow],
             fixtures: list[Fixture] | None = None, flags: list[FlagRow] | None = None):
    """Run project_all over the fillers plus the given players."""
    base_players, base_history = _fillers()
    return project_all(
        {**base_players, **players}, base_history + history,
        fixtures if fixtures is not None else _fixtures(),
        flags or [], _gameweeks(), WINDOW, TODAY,
    )


def test_double_gw_sums_fixtures() -> None:
    """Two identical fixtures in one GW give twice the single-fixture points."""
    # GW12 is normally 2(h) v 1 and 4(h) v 3; add a second identical 2 v 1 meeting.
    fixtures = _fixtures(extra=_pair(12, 2, 1))
    mid = {1: _player(1, 1, "MID")}
    proj = _project(mid, _rows(1, PAST, points=5, xg=0.3, xa=0.2), fixtures)[1]
    single = _project(mid, _rows(1, PAST, points=5, xg=0.3, xa=0.2))[1]
    assert proj.points[12] == pytest.approx(2 * single.points[12])
    assert proj.captain_basis[12] == pytest.approx(2 * single.captain_basis[12])
    assert proj.exp_minutes[12] == pytest.approx(180)


def test_blank_gw_zero() -> None:
    """A team with no fixture in a window GW projects exactly 0 there."""
    fixtures = _fixtures(skip={(13, 1)})
    proj = _project({1: _player(1, 1, "MID")}, _rows(1, PAST, points=5, xg=0.3), fixtures)[1]
    assert proj.points[13] == 0.0
    assert proj.captain_basis[13] == 0.0
    assert proj.exp_minutes[13] == 0.0
    assert proj.points[12] > 0


def test_regression_damps_low_minutes_outlier(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 4.6 DEF with 2 goals off 1.38 xG in 300 mins ranks below a steady 0.5 xGI/90 MID."""
    players = {
        1: _player(1, 2, "DEF", price=4.6),
        2: _player(2, 1, "MID", price=7.0),
    }
    history = (
        _rows(1, [6, 7, 8, 9, 10], minutes=60, points=[2, 9, 2, 10, 2], xg=0.276,
              goals=[0, 1, 0, 1, 0], bps=22)
        + _rows(2, PAST, minutes=90, points=5, xg=0.3, xa=0.2, bps=24)
    )
    proj = _project(players, history)
    assert sum(proj[1].points.values()) < sum(proj[2].points.values())
    # The regression is what does it: with w = 1 for everyone the DEF would rank first.
    monkeypatch.setattr(model, "REGRESSION_MINUTES", 1)
    monkeypatch.setattr(model, "DEFENSIVE_REGRESSION_FACTOR", 1.0)
    unregressed = _project(players, history)
    assert sum(unregressed[1].points.values()) > sum(unregressed[2].points.values())


def test_recency_weighting_beats_single_haul() -> None:
    """One 23-point haul then four 2s projects below a steady 6 a game."""
    players = {1: _player(1, 1, "MID"), 2: _player(2, 1, "MID")}
    gws = [6, 7, 8, 9, 10]
    history = (
        _rows(1, gws, points=[23, 2, 2, 2, 2], xg=0.2, xa=0.1)
        + _rows(2, gws, points=6, xg=0.2, xa=0.1)
    )
    proj = _project(players, history)
    # Equal weighting would favour the hauler (31 points vs 30); decay must not.
    assert proj[1].points[11] < proj[2].points[11]


def test_injured_target_gw_zero() -> None:
    """A 0% player projects 0 in the target GW."""
    players = {1: _player(1, 1, "FWD", status="i", chance=0)}
    proj = _project(players, _rows(1, PAST, points=6, xg=0.5))[1]
    assert proj.points[11] == 0.0
    assert proj.captain_basis[11] == 0.0
    assert proj.points[13] > 0


def test_captain_basis_excludes_observed() -> None:
    """A hot streak on low xG raises points but leaves captain_basis untouched."""
    players = {1: _player(1, 1, "MID"), 2: _player(2, 1, "MID")}
    history = _rows(1, PAST, points=12, xg=0.1) + _rows(2, PAST, points=3, xg=0.1)
    proj = _project(players, history)
    assert proj[1].points[11] > proj[2].points[11]
    assert proj[1].captain_basis[11] == pytest.approx(proj[2].captain_basis[11])


def test_minutes_skip_flagged_gws() -> None:
    """A GW missed while flagged injured does not drag expected minutes down."""
    players = {1: _player(1, 1, "FWD")}
    history = _rows(1, list(range(1, 10)), minutes=90) + _rows(1, [10], minutes=0)
    flags = [FlagRow(1, date(2026, 10, 29), "i", 0)]  # before the GW10 deadline (30 Oct)
    flagged = _project(players, history, flags=flags)[1]
    unflagged = _project(players, history)[1]
    assert flagged.exp_minutes[11] == pytest.approx(90)
    assert unflagged.exp_minutes[11] < 90


def test_leaky_opponent_raises_attack() -> None:
    """Facing a high-xGC opponent lifts expected points; at home more than away."""
    # GW11: 1(h) v 2 and 3(h) v 4. A GKP conceding 2.4 xG a game makes team 2 leaky.
    players = {1: _player(1, 1, "MID"), 2: _player(2, 3, "MID"), 3: _player(3, 2, "GKP")}
    history = (_rows(1, PAST, points=5, xg=0.3) + _rows(2, PAST, points=5, xg=0.3)
               + _rows(3, PAST, points=1, xgc=2.4))
    proj = _project(players, history)
    assert proj[1].captain_basis[11] > proj[2].captain_basis[11]
    # GW12 reverses venues (2(h) v 1): same opponent away is worth less than at home.
    assert proj[1].captain_basis[12] < proj[1].captain_basis[11]


def test_set_piece_resolution_by_club() -> None:
    """Same web_name at two clubs resolves only the one on that club's list."""
    players = {
        10: Player(10, "Hughes", 5, "CRY", "DEF", 5.0, "a", None, ""),
        11: Player(11, "Hughes", 7, "LIV", "DEF", 4.5, "a", None, ""),
        12: Player(12, "Saka", 1, "ARS", "MID", 10.0, "a", None, ""),
    }
    duties = resolve_set_pieces(players)
    assert duties[10] == {"corners": 4}
    assert 11 not in duties
    assert duties[12] == {"pens": 1, "fk": 1, "corners": 1}


def test_set_piece_first_taker_boosts_expected() -> None:
    """A first-choice penalty taker projects above an identical non-taker."""
    players = {
        1: Player(1, "Saka", 1, "ARS", "MID", 10.0, "a", None, ""),
        2: Player(2, "Nobody", 1, "ARS", "MID", 10.0, "a", None, ""),
    }
    history = _rows(1, PAST, points=5, xg=0.3) + _rows(2, PAST, points=5, xg=0.3)
    proj = _project(players, history)
    assert proj[1].captain_basis[11] > proj[2].captain_basis[11]
