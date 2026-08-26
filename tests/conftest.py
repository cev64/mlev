"""Shared fixtures for the bundle tests.

Bundles are built by `export_bundle.py`, which involves a model fit, so they are
loaded once per session rather than rebuilt per test.

`MLEV_BUNDLE_DIR`, when set, is authoritative — if you point it somewhere you
mean there, and quietly falling back elsewhere would let a test pass against a
stale bundle you were not looking at. Unset, it searches `dist/` (where the
exporter and the publishing workflow write) then `/tmp/dist`.

What counts as a failure needs care. A sport can be legitimately between
fixtures — the Premier League feed only lists matches a few days out — and an
empty export for one sport is a fact about the calendar, not a broken pipeline.
So:

* no bundles at all, in CI -> fail. The export produced nothing and the publish
  step would otherwise go green having verified nothing.
* one sport missing while another exported -> skip that sport's tests.
* locally, missing bundles always skip; you may simply not have exported yet.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

RUNNING_IN_CI = os.environ.get("CI", "").lower() in {"1", "true", "yes"}


def _candidate_dirs() -> list[Path]:
    explicit = os.environ.get("MLEV_BUNDLE_DIR")
    if explicit:
        return [Path(explicit)]
    return [Path("dist"), Path("/tmp/dist")]


def _any_bundle_exists() -> bool:
    """Did the export produce anything at all?"""
    return any(
        directory.exists() and any(directory.glob("*.json"))
        for directory in _candidate_dirs()
    )


def _load(name: str) -> dict:
    searched = []
    for directory in _candidate_dirs():
        path = directory / name
        searched.append(str(path))
        if path.exists():
            return json.loads(path.read_text())

    where = ", ".join(searched)
    if RUNNING_IN_CI and not _any_bundle_exists():
        pytest.fail(
            f"No bundles were exported at all (looked in {where}). "
            "The export step produced nothing, so there is nothing to verify."
        )
    pytest.skip(
        f"{name} not found in {where} — that sport is between fixtures, or you "
        "have not run `python export_bundle.py --out dist` yet."
    )


@pytest.fixture(scope="session")
def nfl_bundle() -> dict:
    return _load("nfl.json")


@pytest.fixture(scope="session")
def epl_bundle() -> dict:
    return _load("epl.json")
