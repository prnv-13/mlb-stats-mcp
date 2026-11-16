"""MLB Stats API paths, relative to config.MLBApi.BASE_URL."""

TEAMS = "/teams"
PEOPLE = "/people"
PEOPLE_SEARCH = "/people/search"
FREE_AGENTS = "/people/freeAgents"
STATS_LEADERS = "/stats/leaders"
SCHEDULE = "/schedule"
STANDINGS = "/standings"
TRANSACTIONS = "/transactions"


def team_roster(team_id: int) -> str:
    return f"/teams/{team_id}/roster"


def person(player_id: int) -> str:
    return f"/people/{player_id}"


def person_stats(player_id: int) -> str:
    return f"/people/{player_id}/stats"


def game_boxscore(game_pk: int) -> str:
    return f"/game/{game_pk}/boxscore"


def award_recipients(award_id: str) -> str:
    return f"/awards/{award_id}/recipients"
