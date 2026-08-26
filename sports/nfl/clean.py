"""Clean and join the NFL raw layer.

Produces three tables:

* `games`        — one row per game, canonical team codes, pregame context.
* `team_games`   — two rows per game (one per team, home and away flipped), the
  long shape that rolling form features need.
* `player_games` — weekly player box score + snap share + injury designation.

Point-in-time note: this layer keeps outcome columns (scores, EPA, yards) next
to the pregame context on purpose. Nothing here is a feature yet. The feature
layer is the only place allowed to read those columns, and only through the
shifted helpers in `core.features`.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from core.config import SportConfig
from core.errors import DataSourceError
from core.io import read_table, write_table
from core.naming import slugify
from sports.nfl.teams import canonical_team, unknown_teams

log = logging.getLogger(__name__)

# Kickoffs at or after this local hour count as primetime.
PRIMETIME_HOUR = 19
PRIMETIME_WEEKDAYS = {"Thursday", "Monday", "Saturday"}

# What the book had posted before kickoff. `spread_line` is positive when the
# home team is favoured, so the home side covers when home_margin > spread_line.
MARKET_COLUMNS = [
    "spread_line", "total_line",
    "home_moneyline", "away_moneyline",
    "home_spread_odds", "away_spread_odds",
    "over_odds", "under_odds",
]


def _require(config: SportConfig, name: str) -> pd.DataFrame:
    return read_table(
        config.path("raw", f"{name}.parquet"),
        hint="Run `python run_backfill.py --sport nfl` first.",
    )


def clean_games(config: SportConfig) -> pd.DataFrame:
    sched = _require(config, "schedules").copy()

    for side in ("home", "away"):
        sched[f"{side}_team"] = sched[f"{side}_team"].map(canonical_team)
    bad = unknown_teams(pd.concat([sched["home_team"], sched["away_team"]]).dropna())
    if bad:
        raise DataSourceError(f"schedule contains unrecognised team codes: {bad}")

    sched["kickoff"] = pd.to_datetime(sched["gameday"], errors="coerce")
    if sched["kickoff"].isna().any():
        raise DataSourceError("schedule rows with unparseable gameday; refusing to guess dates")

    hour = pd.to_datetime(sched["gametime"], format="%H:%M", errors="coerce").dt.hour
    sched["is_primetime"] = (
        (hour >= PRIMETIME_HOUR) | sched["weekday"].isin(PRIMETIME_WEEKDAYS)
    ).astype(int)
    sched["is_divisional"] = sched.get("div_game", 0).fillna(0).astype(int)
    sched["is_playoff"] = (sched["game_type"] != "REG").astype(int)
    sched["is_dome"] = sched["roof"].isin(["dome", "closed"]).astype(int)
    sched["is_turf"] = (~sched["surface"].fillna("").str.contains("grass")).astype(int)
    sched["neutral_site"] = (sched["location"].fillna("Home") != "Home").astype(int)

    # Outcomes. `result` is home margin; `total` is combined points.
    sched["home_margin"] = pd.to_numeric(sched["result"], errors="coerce")
    sched["total_points"] = pd.to_numeric(sched["total"], errors="coerce")
    sched["home_win"] = np.where(
        sched["home_margin"].isna(), np.nan, (sched["home_margin"] > 0).astype(float)
    )
    # A tie is neither a home win nor an away win; drop it from the binary
    # target rather than assigning it arbitrarily to one side.
    sched.loc[sched["home_margin"] == 0, "home_win"] = np.nan

    # The market's own numbers. These are neither features nor outcomes: they
    # are what a well-informed observer thought before kickoff, which makes
    # them legitimate to know at predict time and the right benchmark to be
    # scored against. They are kept out of the model matrix in
    # `game_feature_columns` and used only through `core.market`.
    for column in MARKET_COLUMNS:
        if column in sched.columns:
            sched[column] = pd.to_numeric(sched[column], errors="coerce")

    keep = [
        "game_id", "season", "game_type", "week", "kickoff", "weekday",
        "home_team", "away_team", "home_score", "away_score",
        "home_rest", "away_rest", "is_primetime", "is_divisional", "is_playoff",
        "is_dome", "is_turf", "neutral_site", "temp", "wind",
        "home_margin", "total_points", "home_win",
        *MARKET_COLUMNS,
    ]
    games = sched[[c for c in keep if c in sched.columns]].copy()
    return games.sort_values(["kickoff", "game_id"]).reset_index(drop=True)


def clean_team_games(config: SportConfig, games: pd.DataFrame) -> pd.DataFrame:
    """One row per team per game, with that team's own and allowed production."""
    epa = _require(config, "team_week_epa").copy()
    epa["posteam"] = epa["posteam"].map(canonical_team)
    epa["defteam"] = epa["defteam"].map(canonical_team)

    long_rows = []
    for side, other in (("home", "away"), ("away", "home")):
        block = games.copy()
        block["team"] = block[f"{side}_team"]
        block["opponent"] = block[f"{other}_team"]
        block["is_home"] = 1 if side == "home" else 0
        block["points_for"] = block[f"{side}_score"]
        block["points_against"] = block[f"{other}_score"]
        block["rest_days"] = block[f"{side}_rest"]
        block["margin"] = block["points_for"] - block["points_against"]
        block["won"] = np.where(
            block["margin"].isna(), np.nan, (block["margin"] > 0).astype(float)
        )
        long_rows.append(block)

    team_games = pd.concat(long_rows, ignore_index=True)

    offense = epa.rename(columns={"posteam": "team"}).drop(columns=["defteam", "season", "week"])
    team_games = team_games.merge(offense, on=["game_id", "team"], how="left")

    # The same aggregate from the opponent's perspective is this team's defence.
    defense = epa.rename(columns={"defteam": "team"}).drop(columns=["posteam", "season", "week"])
    defense = defense.rename(
        columns={
            c: f"def_{c}"
            for c in defense.columns
            if c not in ("game_id", "team")
        }
    )
    team_games = team_games.merge(defense, on=["game_id", "team"], how="left")

    completed = team_games["points_for"].notna()
    missing_epa = completed & team_games["epa_per_play"].isna()
    if missing_epa.any():
        # Playoff/pre-season edge rows can lack pbp coverage. Report, don't patch.
        log.warning(
            "%s completed team-games have no play-by-play aggregate (kept as NaN, "
            "their rolling features will be gated by min_prior_games)",
            int(missing_epa.sum()),
        )

    return team_games.sort_values(["team", "kickoff"]).reset_index(drop=True)


def clean_player_games(config: SportConfig, games: pd.DataFrame) -> pd.DataFrame:
    """Weekly player production joined to snap share and injury status."""
    weekly = _require(config, "weekly_players").copy()
    weekly["team"] = weekly["team"].map(canonical_team)
    weekly["opponent"] = weekly["opponent_team"].map(canonical_team)
    weekly["player_key"] = weekly["player_id"]
    weekly["player_slug"] = weekly["player_display_name"].map(slugify)

    # Attach the game each player-week belongs to, so we inherit kickoff date
    # (needed to sort point-in-time) and pregame context.
    # The weekly frame carries its own game_id, verified identical to the
    # schedule's for every row. Take the schedule's *context* columns only --
    # merging both game_id columns would silently produce game_id_x/game_id_y
    # and leave every later join looking for a column that no longer exists.
    game_keys = games[
        ["season", "week", "kickoff", "home_team", "away_team",
         "is_primetime", "is_divisional", "is_dome", "is_turf", "temp", "wind"]
    ].copy()
    home_map = game_keys.assign(team=game_keys["home_team"], is_home=1)
    away_map = game_keys.assign(team=game_keys["away_team"], is_home=0)
    lookup = pd.concat([home_map, away_map], ignore_index=True).drop(
        columns=["home_team", "away_team"]
    )

    merged = weekly.merge(lookup, on=["season", "week", "team"], how="inner")
    if "game_id" not in merged.columns:
        raise DataSourceError(
            "player-week rows lost their game_id in the schedule join; the "
            "nflverse weekly schema has changed."
        )
    dropped = len(weekly) - len(merged)
    if dropped:
        log.warning(
            "%s player-weeks had no matching scheduled game (usually pre-season "
            "or a team code outside the backfilled seasons) and were dropped",
            dropped,
        )
    if merged.empty:
        raise DataSourceError("no player-weeks joined to a scheduled game; check team codes")

    merged = _attach_snaps(config, merged)
    merged = _attach_injuries(config, merged)

    # Prop-relevant targets, built straight from nflverse box scores.
    merged["scrimmage_yards"] = (
        merged["rushing_yards"].fillna(0) + merged["receiving_yards"].fillna(0)
    )
    merged["total_tds"] = (
        merged["rushing_tds"].fillna(0)
        + merged["receiving_tds"].fillna(0)
        + merged["passing_tds"].fillna(0)
    )
    merged["scrimmage_tds"] = (
        merged["rushing_tds"].fillna(0) + merged["receiving_tds"].fillna(0)
    )
    merged["anytime_td"] = (merged["scrimmage_tds"] > 0).astype(float)

    return merged.sort_values(["player_key", "kickoff"]).reset_index(drop=True)


def _attach_snaps(config: SportConfig, players: pd.DataFrame) -> pd.DataFrame:
    """Join snap share via the gsis_id <-> pfr_id crosswalk.

    The snap table has no gsis_id, so the crosswalk is the only clean key.
    Players it cannot resolve keep a null snap share; the feature layer treats
    that as missing rather than as zero snaps, which would be a fabricated
    (and very wrong) value.
    """
    snaps = _require(config, "snap_counts").copy()
    ids = _require(config, "player_ids")[["gsis_id", "pfr_id"]]

    snaps["team"] = snaps["team"].map(canonical_team)
    snaps = snaps.merge(ids, left_on="pfr_player_id", right_on="pfr_id", how="left")
    snaps = snaps.dropna(subset=["gsis_id"])
    snaps = snaps.rename(columns={"gsis_id": "player_key"})[
        ["season", "week", "player_key", "offense_pct", "offense_snaps", "st_pct"]
    ].drop_duplicates(["season", "week", "player_key"])

    out = players.merge(snaps, on=["season", "week", "player_key"], how="left")
    matched = out["offense_pct"].notna().mean()
    log.info("snap share resolved for %.1f%% of player-weeks", 100 * matched)
    return out


def _attach_injuries(config: SportConfig, players: pd.DataFrame) -> pd.DataFrame:
    """Join the pregame injury designation.

    The injury report is published before kickoff, so it is a legitimate
    pregame feature — unlike almost everything else in the weekly frame.
    """
    injuries = _require(config, "injuries").copy()
    injuries["team"] = injuries["team"].map(canonical_team)
    injuries = injuries.rename(columns={"gsis_id": "player_key"})
    injuries = injuries.dropna(subset=["player_key"])
    injuries = injuries[["season", "week", "player_key", "report_status", "practice_status"]]
    injuries = injuries.drop_duplicates(["season", "week", "player_key"], keep="last")

    out = players.merge(injuries, on=["season", "week", "player_key"], how="left")
    status = out["report_status"].fillna("None").str.strip().str.lower()
    out["injury_out"] = status.isin(["out", "doubtful"]).astype(int)
    out["injury_questionable"] = (status == "questionable").astype(int)
    out["injury_listed"] = (status != "none").astype(int)
    return out


def run(config: SportConfig) -> dict[str, pd.DataFrame]:
    games = clean_games(config)
    team_games = clean_team_games(config, games)
    player_games = clean_player_games(config, games)

    write_table(games, config.path("clean", "games.parquet"))
    write_table(team_games, config.path("clean", "team_games.parquet"))
    write_table(player_games, config.path("clean", "player_games.parquet"))
    return {"games": games, "team_games": team_games, "player_games": player_games}
