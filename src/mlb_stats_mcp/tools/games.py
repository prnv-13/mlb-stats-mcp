"""Game tools: schedule and box scores."""

from __future__ import annotations

from ..config import CacheTTL, MLBApi
from ..mlb import endpoints, get_client
from .common import JSON, dig, today
from .teams import resolve_team

FINAL_GAME_STATE = "Final"  # status.abstractGameState once a game is over
SIDES = ("away", "home")
LINE_SCORE_TOTALS = ("runs", "hits", "errors")


# ----------------------------------------------------------------- formatting --


def _format_schedule_side(side: JSON) -> JSON:
    record = side.get("leagueRecord") or {}
    return {
        "team": dig(side, "team", "name"),
        "score": side.get("score"),
        "record": f"{record.get('wins')}-{record.get('losses')}" if record else None,
        "probable_pitcher": dig(side, "probablePitcher", "fullName"),
    }


def _format_scheduled_game(game: JSON) -> JSON:
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


def _format_player_line(player: JSON, stat_group: str) -> JSON | None:
    """One box-score row, or None if the player has no stats in this group."""
    stats = dig(player, "stats", stat_group)
    if not stats:
        return None
    return {
        "name": dig(player, "person", "fullName"),
        "position": dig(player, "position", "abbreviation"),
        "line": stats.get("summary"),
    }


def _format_team_box(team_box: JSON) -> JSON:
    players = team_box.get("players", {})

    def lines(player_ids: list[int], stat_group: str) -> list[JSON]:
        # The box score keys each player as "ID<player id>".
        rows = (_format_player_line(players.get(f"ID{pid}", {}), stat_group) for pid in player_ids)
        return [row for row in rows if row]

    return {
        "team": dig(team_box, "team", "name"),
        "batters": lines(team_box.get("batters", []), "batting"),
        "pitchers": lines(team_box.get("pitchers", []), "pitching"),
    }


def _format_inning(inning: JSON) -> JSON:
    return {
        "inning": inning.get("num"),
        **{side: dig(inning, side, "runs") for side in SIDES},
    }


def _games_in(schedule: JSON) -> list[JSON]:
    return [game for day in schedule.get("dates", []) for game in day.get("games", [])]


async def _game_status(game_pk: int) -> JSON:
    schedule = await get_client().get(
        endpoints.SCHEDULE, {"gamePk": game_pk}, ttl=CacheTTL.LIVE_GAME
    )
    games = _games_in(schedule)
    return (games[0].get("status") or {}) if games else {}


# ---------------------------------------------------------------------- tools --


async def get_schedule(
    date: str | None = None,
    end_date: str | None = None,
    team: str | None = None,
) -> JSON:
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

    result: JSON = {"from": start, "to": last_day, "count": len(games), "games": games}
    if not games:
        result["note"] = "No games scheduled in this window (it may be the off-season or an off day)."
    return result


async def get_game(game_pk: int) -> JSON:
    """Get a game's live or final line score plus each team's batting and pitching box score.

    Args:
        game_pk: Game id from get_schedule.
    """
    status = await _game_status(game_pk)
    is_final = status.get("abstractGameState") == FINAL_GAME_STATE
    ttl = CacheTTL.STATIC if is_final else CacheTTL.LIVE_GAME

    client = get_client()
    line_score = await client.get(endpoints.game_linescore(game_pk), ttl=ttl)
    box_score = await client.get(endpoints.game_boxscore(game_pk), ttl=ttl)

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
