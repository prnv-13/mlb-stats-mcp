"""MLB Stats MCP server: tools for players, teams, games, standings and leaders."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import api

mcp = MCPServer(
    name="mlb-stats",
    title="MLB Stats",
    version="0.1.0",
    instructions=(
        "Live and historical Major League Baseball data from the public MLB Stats API. "
        "Use search_players to turn a name into a player_id before calling player tools. "
        "Team arguments accept a name, nickname, abbreviation or numeric id "
        "(e.g. 'Yankees', 'NYY', 'New York Yankees', '147'). "
        "Seasons default to the current year; during the off-season pass the previous year "
        "if the current one has no data. Dates are YYYY-MM-DD."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True)
EASTERN = ZoneInfo("America/New_York")
logging.getLogger("httpx").setLevel(logging.WARNING)

StatGroup = Literal["hitting", "pitching", "fielding"]


def _today() -> str:
    return datetime.now(EASTERN).strftime("%Y-%m-%d")


def _this_year() -> int:
    return datetime.now(EASTERN).year


def _season_ttl(season: int | None) -> float:
    """Past seasons are final, so cache them for a day; the current one changes daily."""
    return api.TTL_DAY if season is not None and season < _this_year() else api.TTL_MEDIUM


# ---------------------------------------------------------------- teams --


async def _teams() -> list[dict[str, Any]]:
    data = await api.get("/teams", ttl=api.TTL_DAY, sportId=1)
    return data.get("teams", [])


async def _resolve_team(team: str) -> dict[str, Any]:
    """Match a team by id, abbreviation, full name, club name or city."""
    key = team.strip().lower()
    teams = await _teams()
    if key.isdigit():
        for t in teams:
            if t["id"] == int(key):
                return t
    for field in ("abbreviation", "name", "teamName", "clubName", "shortName"):
        for t in teams:
            if str(t.get(field, "")).lower() == key:
                return t
    matches = [t for t in teams if key in t.get("name", "").lower()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        names = ", ".join(t["name"] for t in matches)
        raise ToolError(f"'{team}' is ambiguous: {names}. Be more specific.")
    raise ToolError(f"No MLB team matches '{team}'. Call list_teams to see valid teams.")


def _team_summary(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": t["id"],
        "name": t.get("name"),
        "abbreviation": t.get("abbreviation"),
        "league": (t.get("league") or {}).get("name"),
        "division": (t.get("division") or {}).get("name"),
        "venue": (t.get("venue") or {}).get("name"),
    }


@mcp.tool(annotations=READ_ONLY)
async def list_teams() -> list[dict[str, Any]]:
    """List all 30 MLB teams with their ids, abbreviations, league, division and ballpark."""
    data = await api.get("/teams", ttl=api.TTL_DAY, sportId=1, hydrate="league,division")
    teams = sorted(data.get("teams", []), key=lambda t: t.get("name", ""))
    return [_team_summary(t) for t in teams]


@mcp.tool(annotations=READ_ONLY)
async def get_team_roster(
    team: str,
    roster_type: Literal["active", "40Man", "fullSeason"] = "active",
    season: int | None = None,
) -> dict[str, Any]:
    """Get a team's roster.

    Args:
        team: Team name, abbreviation or id, e.g. "Dodgers", "LAD" or "119".
        roster_type: "active" (26-man), "40Man", or "fullSeason" (everyone who played that season).
        season: Season year; defaults to the current one.
    """
    t = await _resolve_team(team)
    data = await api.get(
        f"/teams/{t['id']}/roster", ttl=api.TTL_LONG, rosterType=roster_type, season=season
    )
    players = [
        {
            "player_id": r["person"]["id"],
            "name": r["person"]["fullName"],
            "jersey": r.get("jerseyNumber"),
            "position": (r.get("position") or {}).get("abbreviation"),
            "status": (r.get("status") or {}).get("description"),
        }
        for r in data.get("roster", [])
    ]
    return {"team": t["name"], "roster_type": roster_type, "count": len(players), "players": players}


# -------------------------------------------------------------- players --


@mcp.tool(annotations=READ_ONLY)
async def search_players(name: str, active_only: bool = False) -> list[dict[str, Any]]:
    """Find MLB players by name and return their player_id (needed by other player tools).

    Args:
        name: Full or partial name, e.g. "Ohtani" or "Aaron Judge".
        active_only: Only return currently active players.
    """
    data = await api.get(
        "/people/search", ttl=api.TTL_DAY, names=name, sportIds=1, active="true" if active_only else None
    )
    people = data.get("people", [])
    ids = ",".join(str(p["id"]) for p in people[:15])
    teams: dict[int, str] = {}
    if ids:
        detail = await api.get(
            "/people", ttl=api.TTL_LONG, personIds=ids, hydrate="currentTeam"
        )
        teams = {
            p["id"]: (p.get("currentTeam") or {}).get("name") for p in detail.get("people", [])
        }
    return [
        {
            "player_id": p["id"],
            "name": p.get("fullName"),
            "position": (p.get("primaryPosition") or {}).get("abbreviation"),
            "current_team": teams.get(p["id"]),
            "active": p.get("active"),
            "mlb_debut": p.get("mlbDebutDate"),
        }
        for p in people[:15]
    ]


@mcp.tool(annotations=READ_ONLY)
async def get_player_info(player_id: int) -> dict[str, Any]:
    """Get a player's biography: team, position, age, height, handedness, debut, birthplace.

    Args:
        player_id: MLB player id from search_players.
    """
    data = await api.get(f"/people/{player_id}", ttl=api.TTL_LONG, hydrate="currentTeam")
    people = data.get("people") or []
    if not people:
        raise ToolError(f"No player with id {player_id}")
    p = people[0]
    return {
        "player_id": p["id"],
        "name": p.get("fullName"),
        "current_team": (p.get("currentTeam") or {}).get("name"),
        "position": (p.get("primaryPosition") or {}).get("name"),
        "jersey": p.get("primaryNumber"),
        "age": p.get("currentAge"),
        "birth_date": p.get("birthDate"),
        "birthplace": ", ".join(
            x for x in (p.get("birthCity"), p.get("birthStateProvince"), p.get("birthCountry")) if x
        ),
        "height": p.get("height"),
        "weight_lbs": p.get("weight"),
        "bats": (p.get("batSide") or {}).get("description"),
        "throws": (p.get("pitchHand") or {}).get("description"),
        "mlb_debut": p.get("mlbDebutDate"),
        "active": p.get("active"),
    }


@mcp.tool(annotations=READ_ONLY)
async def get_player_stats(
    player_id: int,
    group: StatGroup = "hitting",
    stat_type: Literal["season", "career", "yearByYear"] = "season",
    season: int | None = None,
) -> dict[str, Any]:
    """Get a player's batting, pitching or fielding stats.

    Args:
        player_id: MLB player id from search_players.
        group: "hitting", "pitching" or "fielding".
        stat_type: "season" (one season), "career" (career totals) or "yearByYear" (every season).
        season: Season year for stat_type="season"; defaults to the current one.
    """
    if stat_type == "season" and season is None:
        season = _this_year()
    data = await api.get(
        f"/people/{player_id}/stats",
        ttl=_season_ttl(season) if stat_type == "season" else api.TTL_MEDIUM,
        stats=stat_type,
        group=group,
        season=season if stat_type == "season" else None,
    )
    splits: list[dict[str, Any]] = []
    for block in data.get("stats", []):
        for s in block.get("splits", []):
            splits.append(
                {
                    "season": s.get("season"),
                    "team": (s.get("team") or {}).get("name"),
                    "league": (s.get("league") or {}).get("name"),
                    "stats": {k: v for k, v in (s.get("stat") or {}).items() if k != "summary"},
                }
            )
    result: dict[str, Any] = {
        "player_id": player_id,
        "group": group,
        "stat_type": stat_type,
        "splits": splits,
    }
    if stat_type == "season":
        result["season"] = season
    if not splits:
        result["note"] = (
            f"No {group} stats found. The player may not have played in {season} "
            "or this stat group may not apply (e.g. pitching stats for a position player)."
            if stat_type == "season"
            else f"No {group} stats found for this player."
        )
    return result


_GAME_LOG_FIELDS = {
    "hitting": [
        "atBats", "runs", "hits", "doubles", "triples", "homeRuns", "rbi",
        "baseOnBalls", "strikeOuts", "stolenBases",
    ],
    "pitching": [
        "inningsPitched", "hits", "runs", "earnedRuns", "baseOnBalls", "strikeOuts",
        "homeRuns", "numberOfPitches", "wins", "losses", "saves",
    ],
}  # fmt: skip


@mcp.tool(annotations=READ_ONLY)
async def get_player_game_log(
    player_id: int,
    group: Literal["hitting", "pitching"] = "hitting",
    season: int | None = None,
    last_n: int = 10,
) -> dict[str, Any]:
    """Get a player's game-by-game stats, most recent game first. Use for recent form, hot or
    cold streaks, and "how did he do last night / this week" questions.

    Args:
        player_id: MLB player id from search_players.
        group: "hitting" or "pitching".
        season: Season year; defaults to the current one.
        last_n: Number of most recent games to return (1-162).
    """
    season = season or _this_year()
    data = await api.get(
        f"/people/{player_id}/stats",
        ttl=_season_ttl(season),
        stats="gameLog",
        group=group,
        season=season,
    )
    splits = [s for block in data.get("stats", []) for s in block.get("splits", [])]
    splits.sort(key=lambda s: (s.get("date", ""), (s.get("game") or {}).get("gameNumber", 1)))
    recent = list(reversed(splits))[: max(1, min(last_n, 162))]
    fields = _GAME_LOG_FIELDS[group]
    games = []
    for s in recent:
        stat = s.get("stat") or {}
        games.append(
            {
                "date": s.get("date"),
                "opponent": (s.get("opponent") or {}).get("name"),
                "home_away": "home" if s.get("isHome") else "away",
                "team_result": "W" if s.get("isWin") else "L",
                "game_pk": (s.get("game") or {}).get("gamePk"),
                "summary": stat.get("summary"),
                "stats": {k: stat[k] for k in fields if k in stat},
            }
        )
    result: dict[str, Any] = {
        "player_id": player_id,
        "group": group,
        "season": season,
        "games_played_in_season": len(splits),
        "games": games,
    }
    if not splits:
        result["note"] = f"No {group} game log for {season}."
    return result


@mcp.tool(annotations=READ_ONLY)
async def get_league_leaders(
    category: str = "homeRuns",
    season: int | None = None,
    group: StatGroup | None = None,
    league: Literal["AL", "NL", "MLB"] = "MLB",
    limit: int = 10,
) -> dict[str, Any]:
    """Get the league leaders for a statistic.

    Args:
        category: Stat category, e.g. homeRuns, battingAverage, runsBattedIn, stolenBases,
            onBasePlusSlugging, hits, earnedRunAverage, strikeouts, wins, saves, walksAndHitsPerInningPitched.
        season: Season year; defaults to the current one.
        group: "hitting" or "pitching". Needed for categories shared by both (e.g. strikeouts
            for pitchers vs. batters). Defaults to the API's choice.
        league: "AL", "NL" or "MLB" (both leagues).
        limit: How many leaders to return (1-50).
    """
    season = season or _this_year()
    league_id = {"AL": 103, "NL": 104}.get(league)
    data = await api.get(
        "/stats/leaders",
        ttl=_season_ttl(season),
        leaderCategories=category,
        season=season,
        statGroup=group,
        leagueId=league_id,
        sportId=1,
        limit=max(1, min(limit, 50)),
    )
    blocks = data.get("leagueLeaders", [])
    if not blocks:
        raise ToolError(f"Unknown leader category '{category}' or no data for {season}.")
    b = blocks[0]
    return {
        "category": b.get("leaderCategory"),
        "group": (b.get("statGroup")),
        "season": season,
        "league": league,
        "leaders": [
            {
                "rank": l.get("rank"),
                "player_id": (l.get("person") or {}).get("id"),
                "name": (l.get("person") or {}).get("fullName"),
                "team": (l.get("team") or {}).get("name"),
                "value": l.get("value"),
            }
            for l in b.get("leaders", [])
        ],
    }


# ---------------------------------------------------------------- games --


def _game_summary(g: dict[str, Any]) -> dict[str, Any]:
    def side(s: dict[str, Any]) -> dict[str, Any]:
        rec = s.get("leagueRecord") or {}
        return {
            "team": (s.get("team") or {}).get("name"),
            "score": s.get("score"),
            "record": f"{rec.get('wins')}-{rec.get('losses')}" if rec else None,
            "probable_pitcher": (s.get("probablePitcher") or {}).get("fullName"),
        }

    return {
        "game_pk": g.get("gamePk"),
        "date": g.get("officialDate"),
        "start_time_utc": g.get("gameDate"),
        "status": (g.get("status") or {}).get("detailedState"),
        "game_type": g.get("gameType"),
        "series": g.get("seriesDescription"),
        "venue": (g.get("venue") or {}).get("name"),
        "away": side(g["teams"]["away"]),
        "home": side(g["teams"]["home"]),
    }


@mcp.tool(annotations=READ_ONLY)
async def get_schedule(
    date: str | None = None,
    end_date: str | None = None,
    team: str | None = None,
) -> dict[str, Any]:
    """Get MLB games (with scores and probable pitchers) for a date or date range.

    Args:
        date: Date as YYYY-MM-DD; defaults to today (US Eastern).
        end_date: Optional end of range (YYYY-MM-DD). Keep ranges short (a few weeks at most).
        team: Optional team filter: name, abbreviation or id.
    """
    start = date or _today()
    team_id = (await _resolve_team(team))["id"] if team else None
    params: dict[str, Any] = {"sportId": 1, "teamId": team_id, "hydrate": "probablePitcher"}
    if end_date:
        params.update(startDate=start, endDate=end_date)
    else:
        params["date"] = start
    # Dates are YYYY-MM-DD, so string comparison is chronological.
    in_past = (end_date or start) < _today()
    data = await api.get("/schedule", ttl=api.TTL_LONG if in_past else api.TTL_SHORT, **params)
    games =[_game_summary(g) for d in data.get("dates", []) for g in d.get("games", [])]
    result: dict[str, Any] = {"from": start, "to": end_date or start, "count": len(games), "games": games}
    if not games:
        result["note"] = "No games scheduled in this window (it may be the off-season or an off day)."
    return result


@mcp.tool(annotations=READ_ONLY)
async def get_game(game_pk: int) -> dict[str, Any]:
    """Get a game's live or final line score plus each team's batting and pitching box score.

    Args:
        game_pk: Game id from get_schedule.
    """
    sched = await api.get("/schedule", ttl=api.TTL_LIVE, gamePk=game_pk)
    games = [g for d in sched.get("dates", []) for g in d.get("games", [])]
    status = (games[0].get("status") or {}) if games else {}
    # A finished game never changes, so cache it for a day; a live one for seconds.
    ttl = api.TTL_DAY if status.get("abstractGameState") == "Final" else api.TTL_LIVE
    line = await api.get(f"/game/{game_pk}/linescore", ttl=ttl)
    box = await api.get(f"/game/{game_pk}/boxscore", ttl=ttl)

    def team_box(side: str) -> dict[str, Any]:
        tb = box["teams"][side]
        players = tb.get("players", {})

        def stat_row(pid: int, group: str) -> dict[str, Any] | None:
            p = players.get(f"ID{pid}") or {}
            s = (p.get("stats") or {}).get(group) or {}
            if not s:
                return None
            return {
                "name": (p.get("person") or {}).get("fullName"),
                "position": (p.get("position") or {}).get("abbreviation"),
                "line": s.get("summary"),
            }

        return {
            "team": tb["team"]["name"],
            "batters": [r for pid in tb.get("batters", []) if (r := stat_row(pid, "batting"))],
            "pitchers": [r for pid in tb.get("pitchers", []) if (r := stat_row(pid, "pitching"))],
        }

    return {
        "game_pk": game_pk,
        "status": status.get("detailedState"),
        "state": {
            "inning": line.get("currentInningOrdinal"),
            "half": line.get("inningHalf"),
            "outs": line.get("outs"),
        },
        "totals": {
            side: {k: line["teams"][side].get(k) for k in ("runs", "hits", "errors")}
            for side in ("away", "home")
        },
        "innings": [
            {
                "inning": i.get("num"),
                "away": (i.get("away") or {}).get("runs"),
                "home": (i.get("home") or {}).get("runs"),
            }
            for i in line.get("innings", [])
        ],
        "away": team_box("away"),
        "home": team_box("home"),
    }


# ------------------------------------------------------------ standings --


@mcp.tool(annotations=READ_ONLY)
async def get_standings(season: int | None = None, league: Literal["AL", "NL", "MLB"] = "MLB") -> dict[str, Any]:
    """Get division standings: wins, losses, win %, games back, streak and run differential.

    Args:
        season: Season year; defaults to the current one.
        league: "AL", "NL" or "MLB" (both).
    """
    season = season or _this_year()
    league_ids = {"AL": "103", "NL": "104", "MLB": "103,104"}[league]
    data = await api.get(
        "/standings",
        ttl=_season_ttl(season),
        leagueId=league_ids,
        season=season,
        hydrate="division,team",
    )
    divisions = []
    for rec in data.get("records", []):
        divisions.append(
            {
                "division": (rec.get("division") or {}).get("name"),
                "teams": [
                    {
                        "rank": t.get("divisionRank"),
                        "team": (t.get("team") or {}).get("name"),
                        "wins": t.get("wins"),
                        "losses": t.get("losses"),
                        "pct": t.get("winningPercentage"),
                        "games_back": t.get("gamesBack"),
                        "wild_card_games_back": t.get("wildCardGamesBack"),
                        "streak": (t.get("streak") or {}).get("streakCode"),
                        "run_differential": t.get("runDifferential"),
                    }
                    for t in rec.get("teamRecords", [])
                ],
            }
        )
    return {"season": season, "divisions": divisions}
