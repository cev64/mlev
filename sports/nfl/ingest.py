"""NFL raw data backfill from nflverse.

Sources, all via `nfl_data_py`:

* `import_schedules`  — one row per game: teams, date, kickoff, scores, rest
  days, roof/surface/weather, divisional flag.
* `import_pbp_data`   — play-by-play, aggregated here to team-week EPA and
  success rate. The raw play frame is ~50k rows x 380 cols per season, so it is
  streamed and aggregated rather than persisted; only the team-week summary
  lands on disk. Everything the aggregation touches is a completed play from
  the game in question, which is why it is only ever consumed as a *prior*
  rolling value by the feature layer.
* nflverse `stats_player` release — per-player weekly box score, the base for
  prop targets. Read from the release URL directly rather than through
  `nfl_data_py.import_weekly_data`, which still points at the retired
  `player_stats/` path and 404s on seasons from 2025 onward. Same upstream
  project, same data, current location.
* `import_snap_counts` — snap share, joined onto the weekly frame.
* `import_injuries`    — the Wed/Thu/Fri practice report and game-status
  designation. Published before kickoff, so it is legitimately pregame.
* `import_ids`         — the gsis_id <-> pfr_id crosswalk used to attach snap
  counts (the snap table carries no gsis_id).

Every function raises `DataSourceError` on failure; nothing here degrades to a
partial or empty frame.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from core.config import SportConfig
from core.errors import DataSourceError
from core.io import write_table

log = logging.getLogger(__name__)

# Columns pulled from play-by-play. Narrow on purpose: the full frame is
# hundreds of columns and pulling it for ten seasons is gigabytes for no gain.
PBP_COLUMNS = [
    "game_id", "season", "week", "season_type", "posteam", "defteam",
    "home_team", "away_team", "play_type", "epa", "success", "pass", "rush",
    "yards_gained", "down", "wp",
]


def _import(fn, label: str, *args, **kwargs) -> pd.DataFrame:
    """Call an nfl_data_py importer, converting any failure into a loud one."""
    try:
        df = fn(*args, **kwargs)
    except Exception as exc:  # network, upstream schema change, bad season
        raise DataSourceError(
            f"nflverse '{label}' fetch failed: {type(exc).__name__}: {exc}. "
            "Check connectivity to github.com/nflverse and that the requested "
            "seasons exist upstream. Not falling back to partial data."
        ) from exc
    if df is None or df.empty:
        raise DataSourceError(f"nflverse '{label}' returned no rows; refusing to continue.")
    return df


def fetch_schedules(seasons: list[int]) -> pd.DataFrame:
    import nfl_data_py as nfl

    return _import(nfl.import_schedules, "schedules", seasons)


WEEKLY_STATS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.parquet"
)

# The retired `player_stats/` release, which nfl_data_py still targets, used
# slightly different names for three columns. Normalise to the current schema.
LEGACY_WEEKLY_RENAMES = {
    "recent_team": "team",
    "interceptions": "passing_interceptions",
    "sacks": "sacks_suffered",
}


def fetch_weekly_players(seasons: list[int]) -> pd.DataFrame:
    """Per-player weekly box scores, one season file at a time.

    Fails loudly per season: a missing season is a real gap (the current
    campaign may not have a file yet), and silently dropping it would leave the
    prop models trained on a period the caller believes they covered.
    """
    frames = []
    for season in seasons:
        url = WEEKLY_STATS_URL.format(season=season)
        try:
            df = pd.read_parquet(url)
        except Exception as exc:
            raise DataSourceError(
                f"nflverse weekly player stats for {season} unavailable at {url}: "
                f"{type(exc).__name__}: {exc}. If the season has not started, "
                "narrow --seasons rather than continuing without it."
            ) from exc
        if df.empty:
            raise DataSourceError(f"nflverse weekly player stats for {season} came back empty.")
        frames.append(df.rename(columns=LEGACY_WEEKLY_RENAMES))
        log.info("season %s: %s player-weeks", season, len(df))
    return pd.concat(frames, ignore_index=True)


def fetch_snap_counts(seasons: list[int]) -> pd.DataFrame:
    import nfl_data_py as nfl

    return _import(nfl.import_snap_counts, "snap counts", seasons)


def fetch_injuries(seasons: list[int]) -> pd.DataFrame:
    import nfl_data_py as nfl

    return _import(nfl.import_injuries, "injury reports", seasons)


def fetch_player_ids() -> pd.DataFrame:
    import nfl_data_py as nfl

    ids = _import(
        nfl.import_ids, "player id crosswalk", columns=["gsis_id", "pfr_id", "name", "position"]
    )
    return ids.dropna(subset=["gsis_id", "pfr_id"]).drop_duplicates("pfr_id")


def fetch_team_week_epa(seasons: list[int]) -> pd.DataFrame:
    """Aggregate play-by-play into one offensive row per team per game.

    EPA per play and success rate on early downs are the two most predictive
    cheap team-strength signals in football, and both need play-level data to
    compute. Aggregating season by season keeps peak memory to one season.
    """
    import nfl_data_py as nfl

    frames = []
    for season in seasons:
        pbp = _import(
            nfl.import_pbp_data,
            f"play-by-play {season}",
            [season],
            columns=PBP_COLUMNS,
            include_participation=False,
            downcast=True,
        )
        plays = pbp[
            pbp["play_type"].isin(["pass", "run"])
            & pbp["posteam"].notna()
            & pbp["epa"].notna()
        ].copy()
        if plays.empty:
            raise DataSourceError(f"no usable pass/run plays returned for {season}")

        # Garbage time distorts EPA badly; restrict to competitive game states,
        # which is standard practice for team-strength EPA.
        plays["competitive"] = plays["wp"].between(0.05, 0.95, inclusive="both")
        plays["early_down"] = plays["down"].isin([1, 2])

        grouped = plays.groupby(["game_id", "season", "week", "posteam", "defteam"], observed=True)
        agg = grouped.agg(
            plays=("epa", "size"),
            epa_per_play=("epa", "mean"),
            success_rate=("success", "mean"),
            pass_plays=("pass", "sum"),
            rush_plays=("rush", "sum"),
            yards_per_play=("yards_gained", "mean"),
        ).reset_index()

        competitive = plays[plays["competitive"]].groupby(
            ["game_id", "posteam"], observed=True
        )["epa"].mean().rename("epa_per_play_competitive")
        early = plays[plays["early_down"]].groupby(
            ["game_id", "posteam"], observed=True
        )["success"].mean().rename("early_down_success_rate")
        pass_epa = plays[plays["pass"] == 1].groupby(
            ["game_id", "posteam"], observed=True
        )["epa"].mean().rename("pass_epa_per_play")
        rush_epa = plays[plays["rush"] == 1].groupby(
            ["game_id", "posteam"], observed=True
        )["epa"].mean().rename("rush_epa_per_play")

        agg = (
            agg.merge(competitive, on=["game_id", "posteam"], how="left")
            .merge(early, on=["game_id", "posteam"], how="left")
            .merge(pass_epa, on=["game_id", "posteam"], how="left")
            .merge(rush_epa, on=["game_id", "posteam"], how="left")
        )
        agg["pass_rate"] = agg["pass_plays"] / agg["plays"]
        frames.append(agg)
        log.info("season %s: aggregated %s plays into %s team-games", season, len(plays), len(agg))

    return pd.concat(frames, ignore_index=True)


def backfill(config: SportConfig, seasons: list[int], *, force: bool = False) -> dict[str, Path]:
    """Pull every raw NFL source for `seasons` and write it to data/nfl/raw/.

    The schedule pull additionally covers `config.upcoming_season`: the NFL
    publishes the full slate months before Week 1, and those unplayed rows are
    what the weekly scoring job predicts. No other source reaches into that
    season — there is nothing to pull until games are played.
    """
    schedule_seasons = sorted(set(seasons) | ({config.upcoming_season} if config.upcoming_season else set()))
    jobs = {
        "schedules": lambda: fetch_schedules(schedule_seasons),
        "team_week_epa": lambda: fetch_team_week_epa(seasons),
        "weekly_players": lambda: fetch_weekly_players(seasons),
        "snap_counts": lambda: fetch_snap_counts(seasons),
        "injuries": lambda: fetch_injuries(seasons),
        "player_ids": fetch_player_ids,
    }
    written: dict[str, Path] = {}
    for name, job in jobs.items():
        path = config.path("raw", f"{name}.parquet")
        if path.exists() and not force:
            log.info("raw/%s.parquet exists, skipping (use --force to refetch)", name)
            written[name] = path
            continue
        log.info("fetching %s for seasons %s-%s", name, seasons[0], seasons[-1])
        written[name] = write_table(job(), path)
    return written
