"""Exception types for the pipeline.

The build spec's non-negotiable is: *fail loudly when a data source is
unavailable, never fabricate data to fill a gap*. Everything in this package
raises one of these rather than returning an empty frame or a silently
imputed default.
"""


class MlevError(Exception):
    """Base class for every error this project raises deliberately."""


class DataSourceError(MlevError):
    """A remote data source was unreachable, or returned something unusable.

    Raised instead of degrading to partial/synthetic data. Callers are meant to
    let this propagate so the operator sees the failure.
    """


class MissingDataError(MlevError):
    """A required local artifact (raw/clean/feature file) does not exist yet."""


class LeakageError(MlevError):
    """A point-in-time invariant was violated.

    Raised by the feature and backtest layers when a feature frame contains a
    row whose inputs could not have been known before kickoff, or when a
    walk-forward split would train on data from at or after the test window.
    """


class ModelNotFittedError(MlevError):
    """predict() was called on a model that has not been fit."""
