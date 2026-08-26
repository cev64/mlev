"""Shared fixtures. The bundles are built once — each involves a model fit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

BUNDLE_DIR = Path("/tmp/dist")


def _load(name: str) -> dict:
    path = BUNDLE_DIR / name
    if not path.exists():
        pytest.skip(
            f"{path} not present — run `python export_bundle.py --out {BUNDLE_DIR}` "
            "to generate the bundles these tests read."
        )
    return json.loads(path.read_text())


@pytest.fixture(scope="session")
def nfl_bundle() -> dict:
    return _load("nfl.json")


@pytest.fixture(scope="session")
def epl_bundle() -> dict:
    return _load("epl.json")
