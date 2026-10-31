"""2026/27 set-piece takers and the discounted points boost they earn."""
import logging

from brief.types import Player

log = logging.getLogger(__name__)

# Club short name -> duty -> takers in order (first = primary taker).
# Transcribed verbatim from the user-supplied 2026/27 table (memory note
# fpl-set-piece-takers-2026-27, supplied 2026-09-26).
SET_PIECES: dict[str, dict[str, list[str]]] = {
    "ARS": {"pens": ["Saka", "Gyökeres", "Ødegaard", "Bruno G."],
            "fk": ["Saka", "Eze", "Ødegaard"],
            "corners": ["Saka", "Tzolis", "Bruno G.", "Madueke"]},
    "AVL": {"pens": ["Buendía", "N.Jackson"],
            "fk": ["Buendía"],
            "corners": ["Cash", "McGinn", "Buendía", "Barkley"]},
    "BHA": {"pens": ["Groß", "David", "O'Riley"],
            "fk": ["Groß", "Ayari", "De Cuyper", "Gomez"],
            "corners": ["Groß", "De Cuyper", "F.Kadıoğlu", "Ayari"]},
    "BOU": {"pens": ["Tavernier"],
            "fk": ["Tavernier", "Brooks", "Scott"],
            "corners": ["Tavernier", "Scott", "Brooks"]},
    "BRE": {"pens": ["Thiago", "Schade"],
            "fk": ["Lewis-Potter", "Damsgaard"],
            "corners": ["Damsgaard", "Janelt", "O.Dango"]},
    "CHE": {"pens": ["Estêvão"],
            "fk": ["Neto"],
            "corners": ["Neto", "Rogers", "Estêvão"]},
    "COV": {"pens": ["Torp", "Grimes", "Thomas-Asante"],
            "fk": ["Rudoni", "Torp"],
            "corners": ["Grimes", "Torp", "Tchaouna", "Hamer", "Rudoni"]},
    "CRY": {"pens": ["Sarr"],
            "fk": ["Yeremy"],
            "corners": ["Yeremy", "Wharton", "Kamada", "Hughes"]},
    "EVE": {"pens": ["Barry", "Garner"],
            "fk": ["Garner"],
            "corners": ["Garner", "Dewsbury-Hall", "Hackney"]},
    "FUL": {"pens": ["Gonzalo", "Robinson", "Iwobi"],
            "fk": ["Iwobi"],
            "corners": ["Iwobi", "Bobb", "Sessegnon", "Kevin"]},
    "HUL": {"pens": ["McBurnie"],
            "fk": ["Giles", "Belloumi"],
            "corners": ["Slater", "Belloumi", "Giles"]},
    "IPS": {"pens": ["Clarke", "Emersonn", "Philogene"],
            "fk": ["Núñez", "Davis", "Clarke"],
            "corners": ["Lukić", "Núñez", "Clarke", "Philogene"]},
    "LEE": {"pens": ["Calvert-Lewin", "Nmecha"],
            "fk": ["Stach", "Longstaff", "Aaronson"],
            "corners": ["Stach", "Longstaff", "Tanaka"]},
    "LIV": {"pens": ["Szoboszlai", "Isak", "Gakpo", "Wirtz", "Mac Allister"],
            "fk": ["Szoboszlai", "Wirtz"],
            "corners": ["Szoboszlai", "Gakpo", "Wirtz"]},
    "MCI": {"pens": ["Haaland", "Doku", "Matheus N."],
            "fk": ["Cherki"],
            "corners": ["Cherki", "Anderson"]},
    "MUN": {"pens": ["B.Fernandes", "Mbeumo", "Tielemans"],
            "fk": ["B.Fernandes", "Mbeumo", "Mount"],
            "corners": ["B.Fernandes", "Mbeumo", "Shaw"]},
    "NEW": {"pens": ["Wissa"],
            "fk": ["Hall", "Schär"],
            "corners": ["Hall", "Barnes", "J.Murphy", "L.Miley"]},
    "NFO": {"pens": ["Gibbs-White", "Wood", "Delap", "Igor Jesus"],
            "fk": ["Gibbs-White", "Murillo", "N.Williams", "Hudson-Odoi"],
            "corners": ["McAtee", "N.Williams", "Schlager"]},
    "SUN": {"pens": ["E.Le Fée"],
            "fk": ["N.Angulo", "Xhaka", "E.Le Fée"],
            "corners": ["E.Le Fée", "Xhaka", "Hume"]},
    "TOT": {"pens": ["Solanke", "Marmoush", "Kudus"],
            "fk": ["Kudus", "Tel", "Marmoush"],
            "corners": ["Robertson", "Fernandes", "Sávio", "Tel", "Kudus"]},
}

# Observed xG/xA already contain set-piece output, so the boost is incremental
# and discounted, never a flat bonus (memory note fpl-set-piece-takers-2026-27).
PEN_INCREMENT = 0.55   # share of penalty xG not already in observed xG (note: ~55%)
PEN_RATE = 0.11        # penalties awarded per team-game (controller resolution)
PEN_XG = 0.76          # xG of one penalty (controller resolution)
DEADBALL_INCREMENT = 0.50  # share of dead-ball creation not already in xA (note: ~50%)
DEADBALL_XA = 0.04     # xA per game from first-choice FK or corner duty (controller resolution)


def resolve_set_pieces(players: dict[int, Player]) -> dict[int, dict[str, int]]:
    """Map player id -> {duty: order (1 = first taker)}, matching names within each club."""
    by_club: dict[tuple[str, str], int] = {
        (p.team_short, p.name): p.id for p in players.values()
    }
    duties: dict[int, dict[str, int]] = {}
    for club, table in SET_PIECES.items():
        for duty, names in table.items():
            for order, name in enumerate(names, start=1):
                player_id = by_club.get((club, name))
                if player_id is None:
                    log.warning("Set-piece taker %s (%s %s #%d) not found", name, club, duty, order)
                    continue
                duties.setdefault(player_id, {})[duty] = order
    return duties


def is_first_taker(duties: dict[str, int]) -> bool:
    """True when the player is first choice for at least one set-piece duty."""
    return any(order == 1 for order in duties.values())


def set_piece_extras(duties: dict[str, int]) -> tuple[float, float]:
    """Return (extra xG per 90, extra xA per 90) earned by first-choice duties."""
    extra_xg = PEN_INCREMENT * PEN_RATE * PEN_XG if duties.get("pens") == 1 else 0.0
    deadball_firsts = sum(1 for duty in ("fk", "corners") if duties.get(duty) == 1)
    extra_xa = deadball_firsts * DEADBALL_INCREMENT * DEADBALL_XA
    return extra_xg, extra_xa
