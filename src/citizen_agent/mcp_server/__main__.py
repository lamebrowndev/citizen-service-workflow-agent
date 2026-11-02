"""``csa-mcp`` entry point: stdio by default, optional streamable HTTP."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from citizen_agent.config import configure, load_settings
from citizen_agent.domain.services import CitizenServices
from citizen_agent.domain.store import Store

from .server import build_server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="csa-mcp",
        description="Run the Civitas citizen services MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="Transport to serve (default: stdio).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP bind port.")
    args = parser.parse_args(argv)

    settings = load_settings()
    if not settings.db_path.is_file():
        print(
            f"Database not found at {settings.db_path}. Run `make seed`.",
            file=sys.stderr,
        )
        return 2

    configure(settings)
    services = CitizenServices(Store(settings.db_path), settings.token_secret.encode("utf-8"))
    server = build_server(services)

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
