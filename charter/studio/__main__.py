"""``python -m charter.studio <audio.mp3> [--port 8765]`` — launch the previewer.

Opens a browser to a Clone-Hero-style highway that previews the auto-charted
drums for a 10-20 s window, with live settings so you can tune per song.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .server import serve


def main() -> None:
    ap = argparse.ArgumentParser(prog="charter.studio", description=__doc__)
    ap.add_argument("audio", nargs="?", default="mp3/clay.mp3",
                    help="audio file to chart/preview (default: mp3/clay.mp3)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser")
    args = ap.parse_args()

    path = Path(args.audio)
    if not path.is_file():
        raise SystemExit(f"audio file not found: {path}")
    serve(str(path), host=args.host, port=args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    main()
