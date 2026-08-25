"""Team and player name normalization across sources.

Each source spells teams differently: nflverse uses abbreviations that have
themselves changed over time (SD -> LAC, OAK -> LV, STL -> LA),
football-data.co.uk uses short English names ("Man United"), and Understat uses
its own ("Manchester United"). Every module in the project converts to a single
canonical key on ingest so the joins are on stable values.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def slugify(name: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace.

    Used as the fallback matcher when a name is not in an explicit alias map,
    and as the canonical player key where no shared player ID exists.
    """
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _PUNCT.sub(" ", text.lower())
    return _WS.sub(" ", text).strip()


def normalize_series(series: pd.Series, alias_map: dict[str, str]) -> pd.Series:
    """Map a column of raw names to canonical keys via `alias_map`.

    The map is keyed on slugified names so a source can spell a team
    "Man United", "Man Utd" or "Manchester Utd" and still land in one place.
    Unmapped names fall through to their slug rather than being dropped —
    `unmapped_names` is how you find them.
    """
    slugs = series.map(slugify)
    return slugs.map(lambda s: alias_map.get(s, s))


def unmapped_names(series: pd.Series, alias_map: dict[str, str]) -> list[str]:
    """Names in `series` that no alias covers. Callers assert this is empty."""
    slugs = {slugify(v) for v in series.dropna().unique()}
    return sorted(s for s in slugs if s and s not in alias_map)


def build_alias_map(canonical_to_aliases: dict[str, list[str]]) -> dict[str, str]:
    """Invert {canonical: [spellings]} into {slug: canonical} for lookup."""
    out: dict[str, str] = {}
    for canonical, aliases in canonical_to_aliases.items():
        for alias in [canonical, *aliases]:
            out[slugify(alias)] = canonical
    return out
