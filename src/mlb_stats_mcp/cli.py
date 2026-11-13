"""Command-line entry point: `mlb-stats-mcp [--transport stdio|http] [--host H] [--port P]`."""

from __future__ import annotations

import argparse
import logging
import os

from .config import Transport
from .server import build_server


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mlb-stats-mcp",
        description="MCP server for MLB stats (players, games, standings, leaders).",
    )
    parser.add_argument(
        "--transport",
        choices=[Transport.STDIO, Transport.HTTP],
        default=os.environ.get(Transport.ENV_TRANSPORT, Transport.STDIO),
        help="stdio for local clients (default); http to host it as a remote server.",
    )
    parser.add_argument(
        "--host", default=os.environ.get(Transport.ENV_HOST, Transport.DEFAULT_HOST)
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get(Transport.ENV_PORT, Transport.DEFAULT_PORT)),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)  # hide one log line per MLB request
    server = build_server()

    if args.transport == Transport.HTTP:
        # Stateless + JSON responses let any instance serve any request, so it scales out.
        server.run(
            "streamable-http",
            host=args.host,
            port=args.port,
            stateless_http=True,
            json_response=True,
        )
    else:
        server.run()
