"""CLI entrypoints for CPS."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cps", description="Client & Prospect Intelligence System"
    )
    sub = parser.add_subparsers(dest="command")

    ui = sub.add_parser("ui", help="Serve the display-only insight UI")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--reload", action="store_true")

    args = parser.parse_args()

    if args.command == "ui":
        import uvicorn

        uvicorn.run(
            "cps.api:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return

    print("CPS — Client & Prospect Intelligence System")
    print()
    print("  PYTHONPATH=src uv run python -m cps.cli ui")
    print("  # → http://127.0.0.1:8765")
    print()
    print("  uv run pytest")
    print()


if __name__ == "__main__":
    main()
