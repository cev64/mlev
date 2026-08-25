"""Dixon-Coles bivariate Poisson goal model.

Why a goal model rather than three classifiers, per the spec: soccer's markets
(1X2, Asian handicap, over/under, both-teams-to-score, correct score) are all
functions of the same thing — the joint distribution of the two scorelines.
Model that once and every market is derived from it and is guaranteed mutually
consistent. Fit three separate classifiers and you can end up quoting a 1X2
that disagrees with your own over/under.

The model, following Dixon & Coles (1997):

    home goals ~ Poisson(lambda),  lambda = exp(base + attack_h + defence_a + gamma)
    away goals ~ Poisson(mu),      mu     = exp(base + attack_a + defence_h)

`base` is the league's overall scoring level and `gamma` the home effect. Both
are unpenalised; ridge applies only to the team ratings. Without a separate
`base`, the only way to express "teams score about 1.4 goals a game" is through
the attack and defence ratings, and the ridge penalty then pulls the whole
league's scoring rate toward one goal per game rather than just shrinking clubs
toward each other.

plus two departures from independent Poisson that matter empirically:

1. **The low-score correction `rho`.** Independent Poisson understates 0-0 and
   1-1 and overstates 0-1 and 1-0. `tau` reweights exactly those four cells.
2. **Exponential time decay.** A match from three seasons ago says less about
   a club than one from last month, so each match is weighted
   `exp(-xi * days_ago)`.

Ridge regularisation serves double duty: it shrinks thin-history clubs toward
average, and it resolves the model's inherent degeneracy (adding a constant to
every attack rating and subtracting it from every defence rating leaves every
prediction unchanged) by selecting the minimum-norm solution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import optimize
from scipy import stats

from core.distributions import ScorelineDistribution
from core.errors import ModelNotFittedError

log = logging.getLogger(__name__)

MAX_GOALS = 10
# Dixon & Coles used ~0.0065/day; 0.0039 is a ~180-day half-life, which suits a
# 38-match league season better than their mid-90s English-league fit.
DEFAULT_DECAY = 0.0039


def tau(
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    lam: np.ndarray,
    mu: np.ndarray,
    rho: float,
) -> np.ndarray:
    """Dixon-Coles low-score correction on the four cells it applies to."""
    out = np.ones_like(lam, dtype=float)
    h0, a0 = home_goals == 0, away_goals == 0
    h1, a1 = home_goals == 1, away_goals == 1
    out = np.where(h0 & a0, 1.0 - lam * mu * rho, out)
    out = np.where(h0 & a1, 1.0 + lam * rho, out)
    out = np.where(h1 & a0, 1.0 + mu * rho, out)
    out = np.where(h1 & a1, 1.0 - rho, out)
    # tau multiplies a probability, so it must stay positive; the optimiser can
    # wander into rho values where it does not.
    return np.clip(out, 1e-10, None)


@dataclass
class DixonColesModel:
    """Attack/defence ratings fitted by penalised maximum likelihood.

    `use_xg=True` fits a second set of ratings on expected goals and blends the
    two rate predictions. Goals are a noisy realisation of chance quality, so
    xG-based ratings converge faster; `xg_weight` controls how much to lean on
    them, and the walk-forward backtest is what settles the value.
    """

    decay: float = DEFAULT_DECAY
    ridge: float = 0.05
    use_xg: bool = True
    xg_weight: float = 0.5
    max_goals: int = MAX_GOALS

    teams_: list[str] = field(default_factory=list)
    attack_: dict[str, float] = field(default_factory=dict)
    defence_: dict[str, float] = field(default_factory=dict)
    xg_attack_: dict[str, float] = field(default_factory=dict)
    xg_defence_: dict[str, float] = field(default_factory=dict)
    base_: float = 0.0
    xg_base_: float = 0.0
    home_advantage_: float = 0.0
    xg_home_advantage_: float = 0.0
    rho_: float = 0.0
    replacement_attack_: float = 0.0
    replacement_defence_: float = 0.0
    _fitted: bool = False

    # --- fitting ------------------------------------------------------------

    def fit(self, matches: pd.DataFrame) -> "DixonColesModel":
        """Fit on completed matches: needs home/away team, goals, kickoff."""
        required = {"home_team", "away_team", "home_goals", "away_goals", "kickoff"}
        missing = required - set(matches.columns)
        if missing:
            raise KeyError(f"DixonColesModel.fit is missing columns: {sorted(missing)}")

        played = matches.dropna(subset=["home_goals", "away_goals"]).copy()
        if len(played) < 100:
            raise ValueError(
                f"only {len(played)} completed matches; too few to fit team ratings"
            )

        self.teams_ = sorted(set(played["home_team"]) | set(played["away_team"]))
        index = {team: i for i, team in enumerate(self.teams_)}
        home_idx = played["home_team"].map(index).to_numpy()
        away_idx = played["away_team"].map(index).to_numpy()

        # Time decay is measured back from the most recent training match, so
        # the weighting is relative to the edge of the training window and
        # never peeks at when the test matches happen.
        reference = played["kickoff"].max()
        days_ago = (reference - played["kickoff"]).dt.days.to_numpy(dtype=float)
        weights = np.exp(-self.decay * days_ago)

        goals_home = played["home_goals"].to_numpy(dtype=float)
        goals_away = played["away_goals"].to_numpy(dtype=float)

        params = self._optimise(
            home_idx, away_idx, goals_home, goals_away, weights, with_rho=True
        )
        n = len(self.teams_)
        self.attack_ = dict(zip(self.teams_, params[:n]))
        self.defence_ = dict(zip(self.teams_, params[n : 2 * n]))
        self.base_ = float(params[2 * n])
        self.home_advantage_ = float(params[2 * n + 1])
        self.rho_ = float(params[2 * n + 2])

        if self.use_xg:
            self._fit_xg(played, home_idx, away_idx, weights)

        # A promoted club has no rating. Rather than inventing one, use the
        # weakest quartile of the clubs we *do* know: that is what a newly
        # promoted side has historically resembled. Recorded explicitly so the
        # prediction layer can flag which matches rest on it.
        attacks = np.array(list(self.attack_.values()))
        defences = np.array(list(self.defence_.values()))
        self.replacement_attack_ = float(np.quantile(attacks, 0.25))
        self.replacement_defence_ = float(np.quantile(defences, 0.75))

        self._fitted = True
        log.info(
            "Dixon-Coles: %s clubs, %s matches, home advantage %.3f, rho %.3f",
            len(self.teams_), len(played), self.home_advantage_, self.rho_,
        )
        return self

    def _fit_xg(self, played, home_idx, away_idx, weights) -> None:
        if "home_xg" not in played.columns or played["home_xg"].isna().all():
            log.warning("use_xg=True but no xG column present; falling back to goals only")
            self.use_xg = False
            return
        usable = played["home_xg"].notna() & played["away_xg"].notna()
        if usable.mean() < 0.5:
            log.warning("xG covers only %.0f%% of training matches; skipping xG ratings",
                        100 * usable.mean())
            self.use_xg = False
            return
        params = self._optimise(
            home_idx[usable.to_numpy()],
            away_idx[usable.to_numpy()],
            played.loc[usable, "home_xg"].to_numpy(dtype=float),
            played.loc[usable, "away_xg"].to_numpy(dtype=float),
            weights[usable.to_numpy()],
            with_rho=False,
        )
        n = len(self.teams_)
        self.xg_attack_ = dict(zip(self.teams_, params[:n]))
        self.xg_defence_ = dict(zip(self.teams_, params[n : 2 * n]))
        self.xg_base_ = float(params[2 * n])
        self.xg_home_advantage_ = float(params[2 * n + 1])

    def _optimise(
        self, home_idx, away_idx, y_home, y_away, weights, *, with_rho: bool
    ) -> np.ndarray:
        n = len(self.teams_)
        # Start at the observed scoring level so the optimiser begins somewhere
        # plausible: equal ratings, the league mean, a small home effect.
        mean_rate = max(float(np.average(np.r_[y_home, y_away])), 1e-3)
        x0 = np.concatenate(
            [np.zeros(2 * n), [np.log(mean_rate)], [0.2], [0.0] if with_rho else []]
        )

        def negative_log_likelihood(params: np.ndarray) -> float:
            attack, defence = params[:n], params[n : 2 * n]
            base = params[2 * n]
            gamma = params[2 * n + 1]
            lam = np.exp(base + attack[home_idx] + defence[away_idx] + gamma)
            mu = np.exp(base + attack[away_idx] + defence[home_idx])
            lam = np.clip(lam, 1e-8, 25.0)
            mu = np.clip(mu, 1e-8, 25.0)

            # Poisson log-likelihood without the log-factorial term, which does
            # not depend on the parameters. Valid for continuous y as well,
            # which is what lets the same routine fit xG.
            ll = y_home * np.log(lam) - lam + y_away * np.log(mu) - mu
            if with_rho:
                rho = params[2 * n + 2]
                ll = ll + np.log(tau(y_home, y_away, lam, mu, rho))
            penalty = self.ridge * (np.sum(attack**2) + np.sum(defence**2))
            return float(-np.sum(weights * ll) + penalty)

        # base and gamma are unpenalised: ridge should shrink clubs toward the
        # league average, not shrink the league average itself.
        bounds = [(-3.0, 3.0)] * (2 * n) + [(-3.0, 2.0), (-1.0, 1.5)]
        if with_rho:
            # rho outside roughly (-0.3, 0.3) drives tau negative for realistic
            # scoring rates, which makes the likelihood undefined.
            bounds.append((-0.25, 0.25))

        result = optimize.minimize(
            negative_log_likelihood, x0, method="L-BFGS-B", bounds=bounds,
            options={"maxiter": 800},
        )
        if not result.success and result.status != 1:  # status 1 = hit maxiter
            raise ValueError(f"Dixon-Coles MLE failed to converge: {result.message}")
        return result.x

    # --- prediction ---------------------------------------------------------

    def _rates(self, home_team: str, away_team: str) -> tuple[float, float]:
        """Expected goals for each side, blending the goal and xG ratings."""
        att_h = self.attack_.get(home_team, self.replacement_attack_)
        def_h = self.defence_.get(home_team, self.replacement_defence_)
        att_a = self.attack_.get(away_team, self.replacement_attack_)
        def_a = self.defence_.get(away_team, self.replacement_defence_)
        log_lam = self.base_ + att_h + def_a + self.home_advantage_
        log_mu = self.base_ + att_a + def_h

        if self.use_xg and self.xg_attack_:
            xatt_h = self.xg_attack_.get(home_team, self.replacement_attack_)
            xdef_h = self.xg_defence_.get(home_team, self.replacement_defence_)
            xatt_a = self.xg_attack_.get(away_team, self.replacement_attack_)
            xdef_a = self.xg_defence_.get(away_team, self.replacement_defence_)
            xlog_lam = self.xg_base_ + xatt_h + xdef_a + self.xg_home_advantage_
            xlog_mu = self.xg_base_ + xatt_a + xdef_h
            w = self.xg_weight
            log_lam = (1 - w) * log_lam + w * xlog_lam
            log_mu = (1 - w) * log_mu + w * xlog_mu

        return float(np.exp(np.clip(log_lam, -5, 3))), float(np.exp(np.clip(log_mu, -5, 3)))

    def scoreline(self, home_team: str, away_team: str) -> ScorelineDistribution:
        """The joint scoreline distribution every EPL market is derived from."""
        if not self._fitted:
            raise ModelNotFittedError("call fit() before scoreline()")
        lam, mu = self._rates(home_team, away_team)
        goals = np.arange(self.max_goals + 1)
        home_pmf = stats.poisson.pmf(goals, lam)
        away_pmf = stats.poisson.pmf(goals, mu)
        grid = np.outer(home_pmf, away_pmf)

        # Apply the low-score correction to its four cells.
        hh, aa = np.meshgrid(goals, goals, indexing="ij")
        grid = grid * tau(hh, aa, np.full(grid.shape, lam), np.full(grid.shape, mu), self.rho_)
        return ScorelineDistribution(grid)

    def is_known(self, team: str) -> bool:
        """False for a club with no fitted rating (newly promoted)."""
        return team in self.attack_

    def ratings_table(self) -> pd.DataFrame:
        """Fitted club ratings, strongest attack first. Useful for a sanity read."""
        if not self._fitted:
            raise ModelNotFittedError("call fit() before ratings_table()")
        return pd.DataFrame(
            {
                "team": self.teams_,
                "attack": [self.attack_[t] for t in self.teams_],
                "defence": [self.defence_[t] for t in self.teams_],
            }
        ).sort_values("attack", ascending=False).reset_index(drop=True)
