"""Canonical Premier League club names.

Three sources spell clubs three ways: football-data.co.uk uses short forms
("Man United", "Nott'm Forest"), Understat uses fuller ones ("Manchester
United", "Nottingham Forest"), and neither is stable across a rename
(Hull/Hull City). Everything is mapped to one canonical name on ingest, and
`unmapped_names` is asserted empty so a newly promoted club fails the run
loudly instead of quietly becoming a second, history-less team.
"""

from __future__ import annotations

from core.naming import build_alias_map

# canonical -> every spelling seen across football-data.co.uk and Understat.
CLUB_ALIASES: dict[str, list[str]] = {
    "Arsenal": ["Arsenal FC"],
    "Aston Villa": ["Villa"],
    "Birmingham": ["Birmingham City"],
    "Blackburn": ["Blackburn Rovers"],
    "Blackpool": [],
    "Bolton": ["Bolton Wanderers"],
    "Bournemouth": ["AFC Bournemouth"],
    "Brentford": [],
    "Brighton": ["Brighton & Hove Albion", "Brighton and Hove Albion"],
    "Burnley": [],
    "Cardiff": ["Cardiff City"],
    "Charlton": ["Charlton Athletic"],
    "Chelsea": [],
    "Coventry": ["Coventry City"],
    "Crystal Palace": ["Palace"],
    "Everton": [],
    "Derby": ["Derby County"],
    "Fulham": [],
    "Huddersfield": ["Huddersfield Town"],
    "Hull": ["Hull City"],
    "Ipswich": ["Ipswich Town"],
    "Leeds": ["Leeds United"],
    "Leicester": ["Leicester City"],
    "Liverpool": [],
    "Luton": ["Luton Town"],
    "Man City": ["Manchester City"],
    "Man United": ["Manchester United", "Man Utd", "Manchester Utd"],
    "Middlesbrough": ["Boro"],
    "Newcastle": ["Newcastle United"],
    "Norwich": ["Norwich City"],
    "Nott'm Forest": ["Nottingham Forest", "Notts Forest", "Nottm Forest"],
    "Sheffield United": ["Sheffield Utd", "Sheffield United FC"],
    "Preston": ["Preston North End"],
    "QPR": ["Queens Park Rangers", "Q.P.R."],
    "Reading": [],
    "Sheffield Weds": ["Sheffield Wednesday", "Sheffield Wed"],
    "Southampton": [],
    "Stoke": ["Stoke City"],
    "Sunderland": ["Sunderland AFC"],
    "Swansea": ["Swansea City"],
    "Tottenham": ["Tottenham Hotspur", "Spurs"],
    "Watford": [],
    "Wigan": ["Wigan Athletic"],
    "West Brom": ["West Bromwich Albion", "West Bromwich"],
    "West Ham": ["West Ham United"],
    "Wolves": ["Wolverhampton Wanderers", "Wolverhampton"],
}

CLUB_ALIAS_MAP: dict[str, str] = build_alias_map(CLUB_ALIASES)
CANONICAL_CLUBS: frozenset[str] = frozenset(CLUB_ALIASES)
