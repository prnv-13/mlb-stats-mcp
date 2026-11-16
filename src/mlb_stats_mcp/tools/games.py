"""Game tools: schedule and box scores."""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError
from typing_extensions import NotRequired, TypedDict

from ..config import CacheTTL, MLBApi
from ..mlb import endpoints, get_client
from .common import JSON, dig, today
from .teams import resolve_team

FINAL_GAME_STATE = "Final"  # status.abstractGameState once a game is over
SIDES = ("away", "home")
LINE_SCORE_TOTALS = ("runs", "hits", "errors")


# --------------------------------------------------------------- result types --


class ScheduledTeam(TypedDict):
    team: str | None
    score: int | None
    record: str | None  # wins-losses, e.g. "92-70"
    probable_pitcher: str | None


class ScheduledGame(TypedDict):
    game_pk: int | None
    date: str | None
    start_time_utc: str | None
    status: str | None
    game_type: str | None
    series: str | None
    venue: str | None
    away: ScheduledTeam
    home: ScheduledTeam


# "from" is a Python keyword, so the window's keys need TypedDict's functional form.
_ScheduleWindow = TypedDict("_ScheduleWindow", {"from": str, "to": str})


class Schedule(_ScheduleWindow):
    """Games from one date to another, inclusive."""

    count: int
    games: list[ScheduledGame]
    note: NotRequired[str]


class GameState(TypedDict):
    inning: str | None  # e.g. "7th"
    half: str | None  # "Top" or "Bottom"
    outs: int | None


class TeamTotals(TypedDict):
    runs: int | None
    hits: int | None
    errors: int | None


class GameTotals(TypedDict):
    away: TeamTotals
    home: TeamTotals


class InningRuns(TypedDict):
    inning: int | None
    away: int | None
    home: int | None


class BoxScoreLine(TypedDict):
    name: str | None
    position: str | None
    line: str | None  # MLB's one-line summary, e.g. "2-4 | HR, 2 RBI"


class TeamBoxScore(TypedDict):
    team: str | None
    batters: list[BoxScoreLine]
    pitchers: list[BoxScoreLine]


class Game(TypedDict):
    """A game's line score and box score, live or final."""

    game_pk: int
    status: str | None
    state: GameState
    totals: GameTotals
    innings: list[InningRuns]
    away: TeamBoxScore
    home: TeamBoxScore


# ----------------------------------------------------------------- formatting --


def _format_schedule_side(side: JSON) -> ScheduledTeam:
    record = side.get("leagueRecord") or {}
    return {
        "team": dig(side, "team", "name"),
        "score": side.get("score"),
        "record": f"{record.get('wins')}-{record.get('losses')}" if record else None,
        "probable_pitcher": dig(side, "probablePitcher", "fullName"),
    }


def _format_scheduled_game(game: JSON) -> ScheduledGame:
    return {
        "game_pk": game.get("gamePk"),
        "date": game.get("officialDate"),
        "start_time_utc": game.get("gameDate"),
        "status": dig(game, "status", "detailedState"),
        "game_type": game.get("gameType"),
        "series": game.get("seriesDescription"),
        "venue": dig(game, "venue", "name"),
        **{side: _format_schedule_side(dig(game, "teams", side) or {}) for side in SIDES},
    }


def _format_player_line(player: JSON, stat_group: str) -> BoxScoreLine | None:
    """One box-score row, or None if the player has no stats in this group."""
    stats = dig(player, "stats", stat_group)
    if not stats:
        return None
    return {
        "name": dig(player, "person", "fullName"),
        "position": dig(player, "position", "abbreviation"),
        "line": stats.get("summary"),
    }


def _format_team_box(team_box: JSON) -> TeamBoxScore:
    players = team_box.get("players", {})

    def lines(player_ids: list[int], stat_group: str) -> list[BoxScoreLine]:
        # The box score keys each player as "ID<player id>".
        rows = (_format_player_line(players.get(f"ID{pid}", {}), stat_group) for pid in player_ids)
        return [row for row in rows if row]

    return {
        "team": dig(team_box, "team", "name"),
        "batters": lines(team_box.get("batters", []), "batting"),
        "pitchers": lines(team_box.get("pitchers", []), "pitching"),
    }


def _format_inning(inning: JSON) -> InningRuns:
    return {
        "inning": inning.get("num"),
        **{side: dig(inning, side, "runs") for side in SIDES},
    }


def _games_in(schedule: JSON) -> list[JSON]:
    return [game for day in schedule.get("dates", []) for game in day.get("games", [])]


async def _scheduled_game(game_pk: int) -> JSON:
    """The game's schedule entry: its status, plus its line score (hydrated in the same call)."""
    schedule = await get_client().get(
        endpoints.SCHEDULE, {"gamePk": game_pk, "hydrate": "linescore"}, ttl=CacheTTL.LIVE_GAME
    )
    games = _games_in(schedule)
    if not games:
        raise ToolError(f"No game with game_pk {game_pk}. Use get_schedule to find one.")
    return games[0]


# ---------------------------------------------------------------------- tools --


async def get_schedule(
    date: str | None = None,
    end_date: str | None = None,
    team: str | None = None,
) -> Schedule:
    """Get MLB games (with scores and probable pitchers) for a date or date range.

    Args:
        date: Date as YYYY-MM-DD; defaults to today (US Eastern).
        end_date: Optional end of range (YYYY-MM-DD). Keep ranges short (a few weeks at most).
        team: Optional team filter: name, abbreviation or id.
    """
    start = date or today()
    last_day = end_date or start
    team_id = (await resolve_team(team))["id"] if team else None

    params: JSON = {"sportId": MLBApi.SPORT_ID_MLB, "teamId": team_id, "hydrate": "probablePitcher"}
    if end_date:
        params.update(startDate=start, endDate=end_date)
    else:
        params["date"] = start

    # ISO dates compare chronologically as strings. Past days won't change.
    is_past = last_day < today()
    schedule = await get_client().get(
        endpoints.SCHEDULE,
        params,
        ttl=CacheTTL.ROSTER if is_past else CacheTTL.TODAYS_SCHEDULE,
    )
    games = [_format_scheduled_game(game) for game in _games_in(schedule)]

    result: Schedule = {"from": start, "to": last_day, "count": len(games), "games": games}
    if not games:
        result["note"] = "No games scheduled in this window (it may be the off-season or an off day)."
    return result


async def get_game(game_pk: int) -> Game:
    """Get a game's live or final line score plus each team's batting and pitching box score.

    Args:
        game_pk: Game id from get_schedule.
    """
    game = await _scheduled_game(game_pk)
    status = game.get("status") or {}
    line_score = game.get("linescore") or {}
    is_final = status.get("abstractGameState") == FINAL_GAME_STATE
    box_score = await get_client().get(
        endpoints.game_boxscore(game_pk), ttl=CacheTTL.STATIC if is_final else CacheTTL.LIVE_GAME
    )

    return {
        "game_pk": game_pk,
        "status": status.get("detailedState"),
        "state": {
            "inning": line_score.get("currentInningOrdinal"),
            "half": line_score.get("inningHalf"),
            "outs": line_score.get("outs"),
        },
        "totals": {
            side: {stat: dig(line_score, "teams", side, stat) for stat in LINE_SCORE_TOTALS}
            for side in SIDES
        },
        "innings": [_format_inning(inning) for inning in line_score.get("innings", [])],
        **{side: _format_team_box(dig(box_score, "teams", side) or {}) for side in SIDES},
    }
