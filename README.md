# MLB Stats MCP

An [MCP](https://modelcontextprotocol.io) server that gives Claude (or any MCP client) live and
historical Major League Baseball data: players, season and career stats, schedules, live box
scores, standings and league leaders.

It uses the public MLB Stats API (`statsapi.mlb.com`), so there are no API keys or sign-up.

<!-- mcp-name: io.github.prnv-13/mlb-stats-mcp -->

Ask things like:

- "How did Aaron Judge's 2026 compare to his career averages?"
- "Who's pitching for the Dodgers tonight, and what are their ERAs?"
- "Show me the AL standings and who's leading the wild card."
- "Top 10 home run hitters in the NL this season."
- "Who won the Cy Young this year, and who has the Mets signed this offseason?"
- "How has Aaron Judge hit against Tarik Skubal?" / "Judge or Ohtani: who had the better 2026?"

## Tools

| Tool | What it does |
|---|---|
| `search_players` | Name → `player_id`, position, current team |
| `get_player_info` | Bio: age, height, bats/throws, debut, birthplace |
| `get_player_stats` | Hitting / pitching / fielding, by season, career or year-by-year |
| `get_player_game_log` | Game-by-game stats, most recent first, for recent form and streaks |
| `get_matchup` | A batter's career line against one pitcher, total and by season, optional postseason |
| `compare_players` | 2-5 players side by side for a season or career, with the leader in each stat |
| `get_league_leaders` | Leaders for any stat category, AL / NL / MLB |
| `get_standings` | Division standings with games back, streak, run differential |
| `list_teams` | All 30 teams with ids, league, division, ballpark |
| `get_team_roster` | Active, 40-man or full-season roster |
| `get_schedule` | Games for a date or range, with scores and probable pitchers |
| `get_game` | Line score by inning plus batting and pitching box score |
| `get_transactions` | Signings, trades, waivers, DFAs, releases, injured list moves and call-ups, by team, player or date range |
| `get_award_winners` | MVP, Cy Young, Rookie of the Year, Gold Glove, Silver Slugger and more, for one season or many |
| `get_player_awards` | Every major award a player has won, with the seasons |

Team arguments accept `"Yankees"`, `"NYY"`, `"New York Yankees"` or `"147"`.

### Results

Every tool returns one JSON object, sent two ways in the MCP result: as JSON text in
`content`, which the model reads, and as `structuredContent` for programs. Each tool's
`outputSchema` (in `tools/list`) lists every field it returns and its type, so clients can
validate results or generate types. Fields MLB doesn't have for a player or game are `null`.
Some tools add a `note` field, for example when nothing matched or a sample is small.

### Caching and retries

Responses are cached in memory, and each kind of data keeps its own lifetime, so repeated
questions don't hit MLB again. A cached call takes about 1 ms, compared with about 1.2 s for a
fresh one.

| Data | Cached for |
|---|---|
| Live games | 15 s |
| Today's schedule | 1 min |
| Standings, leaders, current-season stats, this week's transactions | 5 min |
| Rosters, player bios, award winners, past transactions | 1 h |
| Teams, finished games, past seasons | 24 h |

The cache keeps at most 1,000 entries and evicts the least recently used. Errors are never cached.
Timeouts, connection errors and HTTP 429 or 5xx responses are retried up to 3 times with
exponential backoff and jitter, and a `Retry-After` header is honored. Other 4xx errors fail right
away.

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). It fetches Python for you.

### Claude Code

```bash
claude mcp add mlb-stats -- uvx mlb-stats-mcp
```

### Claude Desktop, Cursor, Windsurf, VS Code and others

Add this to the client's MCP config. For Claude Desktop, that's Settings → Developer → Edit Config:

```json
{
  "mcpServers": {
    "mlb-stats": {
      "command": "uvx",
      "args": ["mlb-stats-mcp"]
    }
  }
}
```

### Remote (no install)

If someone hosts the server (see below), clients can connect to the URL directly:

```bash
claude mcp add --transport http mlb-stats https://YOUR-HOST/mcp
```

In Claude.ai, go to Settings → Connectors → Add custom connector and paste the same URL.

## Development

```bash
git clone https://github.com/prnv-13/mlb-stats-mcp
cd mlb-stats-mcp
uv sync

uv run pytest                                # offline unit tests (MLB API is faked)
uv run scripts/smoke_test.py                 # calls every tool over stdio against the live API
uv run mlb-stats-mcp --transport http        # serves http://127.0.0.1:8000/mcp
npx @modelcontextprotocol/inspector          # GUI for poking at tools
claude mcp add mlb-dev -- uv run --directory "$PWD" mlb-stats-mcp   # use your local copy in Claude Code
```

Layout:

```
src/mlb_stats_mcp/
  config.py        every constant: URLs, timeouts, cache TTLs, retry policy, limits,
                   transaction type codes, award ids
  cli.py           entry point: stdio (default) or --transport http
  server.py        build_server(): server identity, instructions, tool registration
  mlb/             data layer, the only code that talks to MLB
    client.py      MLBClient: caching + retries around HTTP
    cache.py       TTLCache: generic TTL + LRU cache
    endpoints.py   API paths
    errors.py      MLBApiError
  tools/           the MCP tools, one module per area
    teams.py  players.py  leaders.py  games.py  standings.py
    transactions.py  awards.py  matchups.py
    common.py      shared types, annotations, date and season helpers
                   (each tool module declares its result types as TypedDicts)
tests/             offline pytest suite, mirrors src/ (mlb/, tools/)
scripts/smoke_test.py   end-to-end test, works on stdio or an HTTP URL
Dockerfile              for hosting the HTTP version
```

Requests flow one way: `cli` → `server` → `tools/*` → `mlb.MLBClient` → statsapi.mlb.com.
To add a tool, write an async function in the right `tools/` module. Its parameter hints and
docstring become the input schema. Declare its result as a `TypedDict` from
`typing_extensions` and use that as the return type, so the tool gets an output schema.
Then add it to `ALL_TOOLS` in `tools/__init__.py`. The test helper checks that each result's
`structuredContent` matches its text, which catches a key missing from the TypedDict (the SDK
drops undeclared keys from `structuredContent`).

## Publishing guide

There are two ways people can use your MCP. You can do both.

### 1. Publish a package so anyone can run `uvx mlb-stats-mcp`

1. Create accounts on [pypi.org](https://pypi.org) and [test.pypi.org](https://test.pypi.org), then
   create an API token on each (Account settings → API tokens).
2. Build:
   ```bash
   uv build            # creates dist/*.whl and dist/*.tar.gz
   ```
3. Do a test run on TestPyPI:
   ```bash
   uv publish --publish-url https://test.pypi.org/legacy/ --token pypi-XXXX
   uvx --index-url https://test.pypi.org/simple/ --index-strategy unsafe-best-match mlb-stats-mcp --help
   ```
4. Publish for real:
   ```bash
   uv publish --token pypi-XXXX
   ```
5. For each new release, bump `version` in `pyproject.toml`, run `uv build`, then `uv publish`.

To skip handling tokens, set up [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
on PyPI and publish from a GitHub Action instead.

### 2. Host it so people only need a URL

The server runs as a stateless Streamable HTTP server, so any container host works. Examples are
Render, Railway, Fly.io and Google Cloud Run (many have free tiers). The Dockerfile reads `PORT`
from the platform.

```bash
docker build -t mlb-stats-mcp .
docker run -p 8000:8000 mlb-stats-mcp
# → http://localhost:8000/mcp
```

On Render or Railway, connect the GitHub repo and pick "Docker". Users then add
`https://your-app.onrender.com/mcp`.

The server needs no auth because it only reads public data. If you open it to the internet,
consider putting rate limiting in front of it, and keep in mind that heavy traffic hits MLB's
API from your server's IP address.

### 3. Get listed so people can find it

- **Official MCP Registry** ([registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io)):
  ```bash
  brew install mcp-publisher
  mcp-publisher init        # generates server.json from this repo
  mcp-publisher login github
  mcp-publisher publish
  ```
  The registry checks that you own the PyPI package by looking for the `mcp-name:` comment near
  the top of this README.
- **Community lists:** open a PR to
  [awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers), and submit to
  directories such as Smithery, Glama and mcp.so.

## Data and terms

The data comes from MLB Advanced Media's Stats API. It's © MLB and is offered for individual,
non-commercial, non-bulk use. This project isn't affiliated with MLB. Don't use it to build a paid
product or to bulk-scrape the API.

## License

MIT
