#!/usr/bin/env python3
"""Append a timestamped snapshot of current game-line odds to CSV.

    python fetch_odds_data.py --sport americanfootball_nfl
    python fetch_odds_data.py --sport soccer_epl --markets h2h totals

Needs ODDS_API_KEY in the environment or in a local .env (see .env.example).

**This script is deliberately not wired into the modelling pipeline.** Comparing
model output to book prices and computing EV is a later phase, once the models
themselves are proven out. Nothing in `core/` or `sports/` imports this module
or reads what it writes; it keeps running purely so the odds history is
accumulating by the time that phase starts. Snapshots land in
`data/odds/<sport>.csv` — outside the per-sport pipeline directories, so a
pipeline glob can never pick them up by accident.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from core.config import DATA_ROOT

API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
DEFAULT_MARKETS = ("h2h", "spreads", "totals")
FIELDNAMES = [
    "captured_at", "sport", "event_id", "commence_time",
    "home_team", "away_team", "bookmaker", "market", "outcome",
    "price", "point",
]

log = logging.getLogger(__name__)


def load_api_key() -> str:
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.strip().startswith("ODDS_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'\"")
                    break
    if not key:
        raise SystemExit(
            "ODDS_API_KEY is not set. Copy .env.example to .env and add your key, "
            "or export it in the shell."
        )
    return key


def fetch_odds(sport: str, markets: list[str], regions: str, api_key: str) -> list[dict]:
    response = requests.get(
        API_URL.format(sport=sport),
        params={
            "apiKey": api_key,
            "regions": regions,
            "markets": ",".join(markets),
            "oddsFormat": "decimal",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise SystemExit(
            f"The Odds API returned {response.status_code}: {response.text[:200]}"
        )
    remaining = response.headers.get("x-requests-remaining")
    if remaining is not None:
        log.info("odds api requests remaining: %s", remaining)
    return response.json()


def flatten(events: list[dict], sport: str) -> list[dict]:
    captured_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for event in events:
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    rows.append(
                        {
                            "captured_at": captured_at,
                            "sport": sport,
                            "event_id": event.get("id"),
                            "commence_time": event.get("commence_time"),
                            "home_team": event.get("home_team"),
                            "away_team": event.get("away_team"),
                            "bookmaker": bookmaker.get("key"),
                            "market": market.get("key"),
                            "outcome": outcome.get("name"),
                            "price": outcome.get("price"),
                            "point": outcome.get("point"),
                        }
                    )
    return rows


def append_snapshot(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sport", default="americanfootball_nfl")
    parser.add_argument("--markets", nargs="+", default=list(DEFAULT_MARKETS))
    parser.add_argument("--regions", default="us,uk")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    events = fetch_odds(args.sport, args.markets, args.regions, load_api_key())
    rows = flatten(events, args.sport)
    if not rows:
        log.warning("no odds returned for %s — nothing appended", args.sport)
        return 0

    out = args.out or DATA_ROOT / "odds" / f"{args.sport}.csv"
    append_snapshot(rows, out)
    log.info("appended %s rows for %s events -> %s", len(rows), len(events), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
