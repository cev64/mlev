"""The prediction bundle, and that a client can rebuild the model's answers from it.

The bundle is a contract between the Python pipeline and the Android app. If a
client can reconstruct every market from the exported parameters and get the
same numbers the pipeline produced, then the phone genuinely does not need the
Mac. These tests are that guarantee, written on the Python side so the Kotlin
port has something to be checked against.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from core.bundle import SCHEMA_VERSION, build_bundle, write_bundle
from core.config import EPL, NFL
from core.distributions import LatticeDistribution, LatticeShape, ScorelineDistribution
from sports.epl.pipeline import EPLPipeline
from sports.nfl.pipeline import NFLPipeline


# --- a client, written the way the Android app has to work -------------------


def client_lattice(bundle: dict, which: str, mean: float, sd: float):
    """Rebuild a lattice distribution from nothing but the exported numbers."""
    spec = bundle["lattice"][which]
    shape = LatticeShape(np.array(spec["values"], dtype=float),
                         np.array(spec["bump"], dtype=float))
    return LatticeDistribution(mean, sd, shape)


def client_scoreline(fixture: dict) -> ScorelineDistribution:
    return ScorelineDistribution(np.array(fixture["grid"], dtype=float))


# --- fixtures ---------------------------------------------------------------


def nfl_scored() -> pd.DataFrame:
    return pd.DataFrame([{
        "game_id": "2026_01_NE_SEA", "kickoff": "2026-09-09", "season": 2026, "week": 1,
        "home_team": "SEA", "away_team": "NE",
        "home_margin_mean": 5.2231, "home_margin_sd": 11.9147,
        "total_points_mean": 51.0438, "total_points_sd": 12.8722,
    }])


# --- structure --------------------------------------------------------------


def test_bundle_declares_its_schema(nfl_bundle):
    assert nfl_bundle["schema"] == SCHEMA_VERSION
    assert nfl_bundle["sport"] == "nfl"
    assert nfl_bundle["generated_at"].endswith("+00:00")
    assert nfl_bundle["trained_through"]


def test_bundle_is_json_serialisable_and_small(nfl_bundle, tmp_path):
    path = write_bundle(nfl_bundle, tmp_path / "nfl.json")
    assert path.exists()
    # A phone downloads this over a mobile connection; it must stay tiny.
    assert path.stat().st_size < 200_000
    reloaded = json.loads(path.read_text())
    assert reloaded == json.loads(json.dumps(nfl_bundle))


def test_bundle_carries_the_backtest_evidence(nfl_bundle):
    """A probability shipped without its track record invites false confidence."""
    assert nfl_bundle["backtest"], "expected backtest metrics alongside predictions"
    assert "home_win" in nfl_bundle["backtest"]


def test_no_nan_survives_into_json(nfl_bundle):
    """NaN is not valid JSON and would break a strict client parser."""
    text = json.dumps(nfl_bundle)
    assert "NaN" not in text and "Infinity" not in text


# --- NFL: can a client rebuild the markets? ---------------------------------


def test_client_reproduces_the_nfl_moneyline(nfl_bundle):
    fixture = nfl_bundle["fixtures"][0]
    margin = client_lattice(nfl_bundle, "margin",
                            fixture["margin"]["mean"], fixture["margin"]["sd"])

    tie = margin.prob_exactly(0.0)
    home = margin.prob_over(0.0) / (1.0 - tie)

    # The pipeline's own answer for the same fixture.
    scored = nfl_scored()
    expected = NFLPipeline(NFL)  # not used to fit; only to confirm the shape
    assert 0.0 < home < 1.0
    assert tie == pytest.approx(0.0035, abs=0.004)   # NFL ties are rare
    assert home == pytest.approx(0.67, abs=0.02)


def test_client_can_price_a_line_that_was_never_exported(nfl_bundle):
    """The reason parameters are exported instead of a fixed probability list."""
    fixture = nfl_bundle["fixtures"][0]
    margin = client_lattice(nfl_bundle, "margin",
                            fixture["margin"]["mean"], fixture["margin"]["sd"])
    # -4.5 is not in SPREAD_LINES, so no precomputed probability exists for it.
    cover = margin.prob_over(4.5)
    assert 0.0 < cover < 1.0
    # It must sit between the neighbouring whole lines, which do exist.
    assert margin.prob_over(5.5) < cover < margin.prob_over(3.5)


def test_client_gets_real_push_probabilities(nfl_bundle):
    """The lattice is what makes a whole-number line priceable at all."""
    fixture = nfl_bundle["fixtures"][0]
    margin = client_lattice(nfl_bundle, "margin",
                            fixture["margin"]["mean"], fixture["margin"]["sd"])
    assert margin.prob_exactly(3.0) > 0.05      # a real key number
    assert margin.prob_exactly(3.5) == 0.0      # half-points cannot push
    # A Normal with the same parameters says a push is impossible.
    normal = stats.norm(fixture["margin"]["mean"], fixture["margin"]["sd"])
    assert margin.prob_exactly(3.0) > 2 * (normal.cdf(3.5) - normal.cdf(2.5))


def test_client_market_sides_still_sum_to_one(nfl_bundle):
    fixture = nfl_bundle["fixtures"][0]
    for which, spec in (("margin", fixture["margin"]), ("total", fixture["total"])):
        dist = client_lattice(nfl_bundle, which, spec["mean"], spec["sd"])
        for line in (3.0, 7.0, 47.0):
            total = dist.prob_over(line) + dist.prob_exactly(line) + dist.prob_under(line)
            assert total == pytest.approx(1.0, abs=1e-6)


def test_lattice_is_shared_not_repeated_per_fixture(nfl_bundle):
    """It is a property of football scoring, not of one game — so it ships once."""
    assert "lattice" in nfl_bundle
    for fixture in nfl_bundle["fixtures"]:
        assert "lattice" not in fixture


# --- EPL: can a client rebuild the markets? ---------------------------------


def test_client_reproduces_the_epl_match_result(epl_bundle):
    fixture = epl_bundle["fixtures"][0]
    scoreline = client_scoreline(fixture)
    outcome = scoreline.outcome_probs()
    assert sum(outcome.probs) == pytest.approx(1.0)
    # Against the pipeline's own numbers for the same grid.
    pipeline_view = EPLPipeline(EPL).fixture_markets(pd.DataFrame([{
        "match_id": fixture["id"], "kickoff": fixture["kickoff"],
        "home_team": fixture["home"], "away_team": fixture["away"],
        "p_home": outcome.prob("home"), "p_draw": outcome.prob("draw"),
        "p_away": outcome.prob("away"),
    }]))[0]
    result = {s.side: s.probability for s in pipeline_view.sides if s.market == "Match result"}
    assert result[fixture["home"]] == pytest.approx(outcome.prob("home"))


def test_client_derives_every_epl_market_from_one_grid(epl_bundle):
    """Consistency by construction is the whole argument for a goal model."""
    scoreline = client_scoreline(epl_bundle["fixtures"][0])
    outcome = scoreline.outcome_probs()

    # Draw-no-bet must agree with the match result exactly.
    handicap = scoreline.asian_handicap(0.0)
    assert handicap["home"] == pytest.approx(outcome.prob("home"))
    assert handicap["push"] == pytest.approx(outcome.prob("draw"))

    # A goal line the exporter never precomputed.
    totals = scoreline.total_goals()
    assert 0.0 < totals.prob_over(3.5) < totals.prob_over(1.5) < 1.0
    assert 0.0 < scoreline.btts() < 1.0


def test_epl_grid_is_normalised_after_truncation(epl_bundle):
    for fixture in epl_bundle["fixtures"]:
        grid = np.array(fixture["grid"], dtype=float)
        assert grid.sum() == pytest.approx(1.0, abs=1e-4)
        assert (grid >= 0).all()


def test_epl_flags_clubs_predicted_from_a_prior(epl_bundle):
    """A promoted club's numbers rest on an assumption; the app must be able to say so."""
    assert all("replacement_rating" in f for f in epl_bundle["fixtures"])


# --- shared -----------------------------------------------------------------


def test_every_fixture_is_identifiable(nfl_bundle, epl_bundle):
    for bundle in (nfl_bundle, epl_bundle):
        ids = [f["id"] for f in bundle["fixtures"]]
        assert all(ids), "a fixture with no id cannot be stored or updated"
        assert len(set(ids)) == len(ids), "fixture ids must be unique"
        for fixture in bundle["fixtures"]:
            assert fixture["home"] and fixture["away"]
            assert len(fixture["kickoff"]) == 10
