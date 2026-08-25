"""Point-in-time feature helpers shared by both sports.

Non-negotiable #1: *no lookahead leakage, anywhere in the pipeline*. Nearly all
of the leakage risk in this project lives in one operation — "what has this team
/ player done recently?" — so it is implemented exactly once, here, rather than
being re-derived per sport.

The invariant every function below preserves: **the value on row i uses only
rows strictly before i within its group**. That is the `.shift(1)` before every
`.rolling()`/`.expanding()`/`.ewm()`. A rolling mean computed without that shift
includes the current game's own result, which is the classic way a backtest
reports a Brier score it could never reproduce live.
"""

from __future__ import annotations

import pandas as pd

from core.errors import LeakageError


def _sorted_group(
    df: pd.DataFrame, group_cols: list[str], sort_cols: list[str]
) -> pd.core.groupby.DataFrameGroupBy:
    missing = [c for c in [*group_cols, *sort_cols] if c not in df.columns]
    if missing:
        raise KeyError(f"missing columns for point-in-time roll: {missing}")
    return df.sort_values([*group_cols, *sort_cols]).groupby(group_cols, sort=False)


def rolling_prior_mean(
    df: pd.DataFrame,
    value_col: str,
    *,
    group_cols: list[str],
    sort_cols: list[str],
    window: int,
    min_periods: int = 1,
) -> pd.Series:
    """Mean of `value_col` over the previous `window` rows in each group.

    Excludes the current row. Returns a Series aligned to `df`'s original index.
    """
    grouped = _sorted_group(df, group_cols, sort_cols)
    out = grouped[value_col].transform(
        lambda s: s.shift(1).rolling(window, min_periods=min_periods).mean()
    )
    return out.reindex(df.index)


def rolling_prior_sum(
    df: pd.DataFrame,
    value_col: str,
    *,
    group_cols: list[str],
    sort_cols: list[str],
    window: int,
    min_periods: int = 1,
) -> pd.Series:
    """Sum of `value_col` over the previous `window` rows in each group."""
    grouped = _sorted_group(df, group_cols, sort_cols)
    out = grouped[value_col].transform(
        lambda s: s.shift(1).rolling(window, min_periods=min_periods).sum()
    )
    return out.reindex(df.index)


def rolling_prior_std(
    df: pd.DataFrame,
    value_col: str,
    *,
    group_cols: list[str],
    sort_cols: list[str],
    window: int,
    min_periods: int = 3,
) -> pd.Series:
    """Prior-window standard deviation — feeds the variance side of a prop."""
    grouped = _sorted_group(df, group_cols, sort_cols)
    out = grouped[value_col].transform(
        lambda s: s.shift(1).rolling(window, min_periods=min_periods).std()
    )
    return out.reindex(df.index)


def ewm_prior_mean(
    df: pd.DataFrame,
    value_col: str,
    *,
    group_cols: list[str],
    sort_cols: list[str],
    halflife: float,
) -> pd.Series:
    """Recency-weighted prior mean.

    The spec asks for recency-weighted points for/against; a half-life is a
    cleaner knob than a hard window because it degrades smoothly rather than
    dropping a game off a cliff.
    """
    grouped = _sorted_group(df, group_cols, sort_cols)
    out = grouped[value_col].transform(
        lambda s: s.shift(1).ewm(halflife=halflife, min_periods=1).mean()
    )
    return out.reindex(df.index)


def expanding_prior_mean(
    df: pd.DataFrame,
    value_col: str,
    *,
    group_cols: list[str],
    sort_cols: list[str],
    min_periods: int = 1,
) -> pd.Series:
    """Season-to-date mean, excluding the current row."""
    grouped = _sorted_group(df, group_cols, sort_cols)
    out = grouped[value_col].transform(
        lambda s: s.shift(1).expanding(min_periods=min_periods).mean()
    )
    return out.reindex(df.index)


def prior_game_count(
    df: pd.DataFrame, *, group_cols: list[str], sort_cols: list[str]
) -> pd.Series:
    """How many prior rows each group has. Used to gate thin-history rows."""
    grouped = _sorted_group(df, group_cols, sort_cols)
    out = grouped.cumcount()
    return out.reindex(df.index)


def days_since_prior(
    df: pd.DataFrame,
    date_col: str,
    *,
    group_cols: list[str],
    sort_cols: list[str],
    cap: float = 30.0,
) -> pd.Series:
    """Rest days since the group's previous row, capped (offseason/int'l break)."""
    grouped = _sorted_group(df, group_cols, sort_cols)
    deltas = grouped[date_col].transform(lambda s: s.diff().dt.days)
    return deltas.reindex(df.index).clip(upper=cap)


def assert_no_lookahead(
    features: pd.DataFrame,
    *,
    feature_cols: list[str],
    outcome_cols: list[str],
) -> None:
    """Guard that outcome columns have not leaked into the feature block.

    Catches the cheap mistakes — an outcome column left in the model matrix, or
    a feature that is a perfect copy of one. It is a tripwire, not a proof; the
    real guarantee comes from every feature being built with the shifted
    helpers above, and from the walk-forward split in core.backtest.
    """
    overlap = sorted(set(feature_cols) & set(outcome_cols))
    if overlap:
        raise LeakageError(
            f"outcome columns present in the feature matrix: {overlap}"
        )
    numeric = features.select_dtypes("number")
    for outcome in outcome_cols:
        if outcome not in numeric.columns:
            continue
        target = numeric[outcome]
        if target.nunique(dropna=True) < 2:
            continue
        for col in feature_cols:
            if col not in numeric.columns:
                continue
            pair = numeric[[col, outcome]].dropna()
            if len(pair) < 20 or pair[col].nunique() < 2:
                continue
            corr = pair[col].corr(pair[outcome])
            if pd.notna(corr) and abs(corr) > 0.999:
                raise LeakageError(
                    f"feature {col!r} is collinear with outcome {outcome!r} "
                    f"(|r| = {abs(corr):.4f}) — it is almost certainly leaking."
                )


def drop_thin_history(
    features: pd.DataFrame, *, count_cols: list[str], min_prior_games: int
) -> pd.DataFrame:
    """Drop rows whose rolling features rest on too little history.

    A team's first game in the dataset has no prior form; keeping those rows
    trains the model on noise and inflates early-season error. We drop rather
    than impute — imputing here would be fabricating data.
    """
    mask = pd.Series(True, index=features.index)
    for col in count_cols:
        mask &= features[col].fillna(0) >= min_prior_games
    return features.loc[mask].copy()
