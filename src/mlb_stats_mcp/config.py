"""Every tunable value and external identifier the server uses, in one place.

Grouped by topic so a reader can find "how long do we cache standings?" or
"how many times do we retry?" without searching the codebase.
"""

from __future__ import annotations

from typing import Final
from zoneinfo import ZoneInfo

from . import __version__

SECONDS_PER_MINUTE: Final = 60
SECONDS_PER_HOUR: Final = 60 * SECONDS_PER_MINUTE
SECONDS_PER_DAY: Final = 24 * SECONDS_PER_HOUR


class Server:
    """Identity the MCP server reports to clients."""

    NAME: Final = "mlb-stats"
    TITLE: Final = "MLB Stats"
    VERSION: Final = __version__


class Transport:
    """How the server is exposed: stdio for local clients, HTTP for hosting."""

    STDIO: Final = "stdio"
    HTTP: Final = "http"
    DEFAULT_HOST: Final = "127.0.0.1"
    DEFAULT_PORT: Final = 8000

    # Environment variables read by the CLI (hosting platforms set PORT for you).
    ENV_TRANSPORT: Final = "MCP_TRANSPORT"
    ENV_HOST: Final = "HOST"
    ENV_PORT: Final = "PORT"


class MLBApi:
    """The public MLB Stats API."""

    BASE_URL: Final = "https://statsapi.mlb.com/api/v1"
    USER_AGENT: Final = f"mlb-stats-mcp/{__version__}"
    TIMEOUT_SECONDS: Final = 15.0
    SPORT_ID_MLB: Final = 1  # the API also covers minor leagues; 1 is Major League Baseball
    TIMEZONE: Final = ZoneInfo("America/New_York")  # MLB's "official date" follows US Eastern


class League:
    """MLB league ids, keyed by the codes tools accept."""

    AMERICAN_LEAGUE_ID: Final = 103
    NATIONAL_LEAGUE_ID: Final = 104

    IDS_BY_CODE: Final[dict[str, tuple[int, ...]]] = {
        "AL": (AMERICAN_LEAGUE_ID,),
        "NL": (NATIONAL_LEAGUE_ID,),
        "MLB": (AMERICAN_LEAGUE_ID, NATIONAL_LEAGUE_ID),
    }


class CacheTTL:
    """How long each kind of response stays cached, in seconds.

    Picked by how fast the underlying data changes.
    """

    LIVE_GAME: Final = 15
    TODAYS_SCHEDULE: Final = SECONDS_PER_MINUTE
    CURRENT_SEASON: Final = 5 * SECONDS_PER_MINUTE  # standings, leaders, this season's stats
    ROSTER: Final = SECONDS_PER_HOUR  # also player bios and past schedules
    STATIC: Final = SECONDS_PER_DAY  # teams, finished games, past seasons


class Cache:
    MAX_ENTRIES: Final = 1000


class Retry:
    """Retries for transient MLB API failures."""

    MAX_ATTEMPTS: Final = 3
    BASE_DELAY_SECONDS: Final = 0.5
    BACKOFF_MULTIPLIER: Final = 2  # delay doubles after each failed attempt
    JITTER_MIN: Final = 0.8  # randomize each delay to 80-120% so clients don't retry in sync
    JITTER_MAX: Final = 1.2
    MAX_RETRY_AFTER_SECONDS: Final = 10.0  # cap on a server-requested Retry-After wait
    RETRYABLE_STATUS_CODES: Final = frozenset({429, 500, 502, 503, 504})


class Limits:
    """Caps on how much data a single tool call returns."""

    MAX_SEARCH_RESULTS: Final = 15
    DEFAULT_LEADERS: Final = 10
    MAX_LEADERS: Final = 50
    DEFAULT_GAME_LOG_GAMES: Final = 10
    MAX_GAME_LOG_GAMES: Final = 162  # games in a regular season
