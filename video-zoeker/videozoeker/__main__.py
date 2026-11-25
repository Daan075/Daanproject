"""Start de app: python -m videozoeker"""

from __future__ import annotations

import argparse
import logging
import threading
import webbrowser

import uvicorn

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(description="Video Zoeker")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--no-browser", action="store_true", help="open de browser niet automatisch")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    url = f"http://{'localhost' if args.host in {'127.0.0.1', '0.0.0.0'} else args.host}:{args.port}"
    print(f"\n  Video Zoeker draait op {url}\n  Stoppen: Ctrl+C\n")
    if not config.has_api_key():
        print("  LET OP: er is geen ANTHROPIC_API_KEY ingesteld (zie .env.example).\n")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("videozoeker.server:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
