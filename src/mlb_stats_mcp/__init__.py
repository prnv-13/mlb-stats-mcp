"""MLB Stats MCP server."""

from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mlb-stats-mcp",
        description="MCP server for MLB stats (players, games, standings, leaders).",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="stdio for local clients (default); http to host it as a remote server.",
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()

    from .server import mcp

    if args.transport == "http":
        # Stateless + JSON responses scale horizontally on any hosting platform.
        mcp.run(
            "streamable-http",
            host=args.host,
            port=args.port,
            stateless_http=True,
            json_response=True,
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
