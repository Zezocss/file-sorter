"""Command-line entry point for explicit local folder access."""

import argparse
from pathlib import Path
import uvicorn
from .app import create_app
from .settings import default_state_directory


def main() -> None:
    """Parse permitted roots/state/port and start one loopback-bound service process."""
    parser = argparse.ArgumentParser(description="Local File Sorter — preview and organize files in your browser.")
    parser.add_argument("--root", action="append", required=True, help="Permitted absolute folder; repeat for multiple folders/drives.")
    parser.add_argument("--state-dir", type=Path, default=default_state_directory(), help="Application state directory (must be outside sortable files).")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a port between 1024 and 65535.")
    try:
        app = create_app(args.root, args.state_dir, args.port)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Open http://127.0.0.1:{args.port} in your browser. Press Ctrl+C to stop.")
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
