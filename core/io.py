"""Parquet/CSV helpers that fail loudly instead of returning empty frames."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from core.errors import MissingDataError

log = logging.getLogger(__name__)


def write_table(df: pd.DataFrame, path: Path, *, also_csv: bool = False) -> Path:
    """Write a frame to parquet, optionally mirroring to CSV for eyeballing."""
    if df.empty:
        raise ValueError(f"refusing to write an empty frame to {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    log.info("wrote %s rows x %s cols -> %s", len(df), df.shape[1], path)
    if also_csv:
        csv_path = path.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        log.info("mirrored -> %s", csv_path)
    return path


def read_table(path: Path, *, hint: str = "") -> pd.DataFrame:
    """Read a frame, raising MissingDataError with a usable next step."""
    if not path.exists():
        suffix = f" {hint}" if hint else ""
        raise MissingDataError(f"{path} does not exist.{suffix}")
    df = pd.read_parquet(path)
    if df.empty:
        raise MissingDataError(f"{path} exists but is empty; re-run the step that builds it.")
    return df


def write_predictions(df: pd.DataFrame, path: Path) -> Path:
    """Predictions are written as CSV — they are meant to be read by a human."""
    if df.empty:
        raise ValueError(f"refusing to write an empty prediction set to {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info("wrote %s predictions -> %s", len(df), path)
    return path
