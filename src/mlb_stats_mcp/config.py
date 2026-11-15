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
    ROSTER: Final = SECONDS_PER_HOUR  # also player bios, past schedules, past transactions
    RECENT_TRANSACTIONS: Final = 5 * SECONDS_PER_MINUTE  # moves are posted throughout the day
    AWARDS: Final = SECONDS_PER_HOUR  # new winners are added during awards week each November
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
    DEFAULT_TRANSACTIONS: Final = 50
    MAX_TRANSACTIONS: Final = 200
    DEFAULT_AWARD_SEASONS: Final = 1
    MAX_AWARD_SEASONS: Final = 100  # MVPs date back to 1931
    MIN_COMPARE_PLAYERS: Final = 2
    MAX_COMPARE_PLAYERS: Final = 5


class GameType:
    """MLB game type codes, as used by the stats endpoints' gameType parameter."""

    REGULAR_SEASON: Final = "R"
    POSTSEASON_ROUNDS: Final = ("F", "D", "L", "W")  # wild card, division, LCS, World Series
    NAMES: Final[dict[str, str]] = {
        "R": "regular_season",
        "F": "wild_card",
        "D": "division_series",
        "L": "championship_series",
        "W": "world_series",
    }


class Matchups:
    """Batter-vs-pitcher history."""

    # Head-to-head numbers swing wildly over a few at-bats. Below this many plate
    # appearances the tool tells the model the sample is too small to mean much.
    MIN_MEANINGFUL_PLATE_APPEARANCES: Final = 50


class Transactions:
    """Roster moves: signings, trades, waivers, injured list and so on."""

    # With no dates given, a team or league-wide search covers the last week.
    DEFAULT_WINDOW_DAYS: Final = 7
    # A league-wide search returns ~20 moves a day, so it is limited to one month.
    # Searches for one team or player can span any range.
    MAX_LEAGUE_WIDE_WINDOW_DAYS: Final = 31

    # Tool-facing kinds → MLB transaction type codes (see /api/v1/transactionTypes).
    # Watch out: the API's "DFA" means *declared free agency*; designated for assignment is "DES".
    TYPE_CODES_BY_KIND: Final[dict[str, frozenset[str]]] = {
        "signings": frozenset({"SFA", "SGN", "IFA", "NC"}),
        "trades": frozenset({"TR"}),
        "free_agency": frozenset({"DFA"}),
        "waivers_and_dfa": frozenset({"DES", "WA", "CLW", "OUT"}),
        "releases": frozenset({"REL", "URL"}),
        "status_changes": frozenset({"SC", "RE"}),  # injured list placements and activations
        "call_ups_and_options": frozenset({"CU", "OPT", "SE", "CP", "ASG"}),
    }


class Awards:
    """MLB award ids, keyed by the award names tools accept, then by league code.

    League awards (MVP, Cy Young, ...) have one id per league; awards given across
    all of MLB (World Series MVP, ...) have a single "MLB" id.
    """

    IDS_BY_NAME: Final[dict[str, dict[str, str]]] = {
        "mvp": {"AL": "ALMVP", "NL": "NLMVP"},
        "cy_young": {"AL": "ALCY", "NL": "NLCY"},
        "rookie_of_the_year": {"AL": "ALROY", "NL": "NLROY"},
        "manager_of_the_year": {"AL": "ALMOY", "NL": "NLMOY"},
        "comeback_player": {"AL": "ALCPOY", "NL": "NLCPOY"},
        "hank_aaron": {"AL": "ALHAA", "NL": "NLHAA"},
        "silver_slugger": {"AL": "ALSS", "NL": "NLSS"},
        "gold_glove": {"AL": "ALGG", "NL": "NLGG"},
        "platinum_glove": {"AL": "ALPG", "NL": "NLPG"},
        "all_star": {"AL": "ALAS", "NL": "NLAS"},
        "lcs_mvp": {"AL": "ALCSMVP", "NL": "NLCSMVP"},
        "world_series_mvp": {"MLB": "WSMVP"},
        "all_star_game_mvp": {"MLB": "ASMVP"},
        "roberto_clemente": {"MLB": "MLBRC"},
        "all_mlb_first_team": {"MLB": "MLBAFIRST"},
        "all_mlb_second_team": {"MLB": "MLBSECOND"},
    }
