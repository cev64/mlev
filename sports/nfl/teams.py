"""Canonical NFL team codes.

nflverse is mostly consistent, but franchise relocations mean the *same*
franchise appears under different abbreviations depending on the season and the
source table (SD/LAC, OAK/LV, STL/LA). Rolling team form has to follow the
franchise across the move, so everything is mapped to one code on ingest.
"""

from __future__ import annotations

# Historical / alternate spelling -> canonical code.
TEAM_ALIASES: dict[str, str] = {
    "SD": "LAC",   # San Diego -> Los Angeles Chargers (2017)
    "SDG": "LAC",
    "OAK": "LV",   # Oakland -> Las Vegas Raiders (2020)
    "RAI": "LV",
    "STL": "LA",   # St. Louis -> Los Angeles Rams (2016)
    "LAR": "LA",   # nflverse uses LA; some tables use LAR
    "SL": "LA",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
    "JAC": "JAX",
    "WSH": "WAS",
    "WFT": "WAS",
}

CANONICAL_TEAMS: frozenset[str] = frozenset(
    {
        "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
        "DET", "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA",
        "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
        "TEN", "WAS",
    }
)

# Divisions, for the divisional-game flag when the schedule does not carry one.
DIVISIONS: dict[str, str] = {
    "BUF": "AFC East", "MIA": "AFC East", "NE": "AFC East", "NYJ": "AFC East",
    "BAL": "AFC North", "CIN": "AFC North", "CLE": "AFC North", "PIT": "AFC North",
    "HOU": "AFC South", "IND": "AFC South", "JAX": "AFC South", "TEN": "AFC South",
    "DEN": "AFC West", "KC": "AFC West", "LAC": "AFC West", "LV": "AFC West",
    "DAL": "NFC East", "NYG": "NFC East", "PHI": "NFC East", "WAS": "NFC East",
    "CHI": "NFC North", "DET": "NFC North", "GB": "NFC North", "MIN": "NFC North",
    "ATL": "NFC South", "CAR": "NFC South", "NO": "NFC South", "TB": "NFC South",
    "ARI": "NFC West", "LA": "NFC West", "SF": "NFC West", "SEA": "NFC West",
}


def canonical_team(code: str | None) -> str | None:
    """Map any nflverse spelling to the canonical franchise code."""
    if code is None or not isinstance(code, str) or not code.strip():
        return None
    upper = code.strip().upper()
    return TEAM_ALIASES.get(upper, upper)


def unknown_teams(codes) -> list[str]:
    """Codes that survive canonicalisation but are not real franchises."""
    mapped = {canonical_team(c) for c in codes}
    return sorted(c for c in mapped if c and c not in CANONICAL_TEAMS)
