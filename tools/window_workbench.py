import argparse
import sys
import webbrowser
from pathlib import Path
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from game_bot.web.window_bridge import start_window_workbench_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = PROJECT_ROOT / "dist" / "workbench" / "index.html"
DEFAULT_FRONTEND_URL = "http://127.0.0.1:5173"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML, help="Built frontend HTML entry to serve when not using --api-only.")
    parser.add_argument("--api-only", action="store_true", help="Run only the workbench API backend for the Vite frontend.")
    parser.add_argument("--frontend-url", default=DEFAULT_FRONTEND_URL, help="Frontend URL to print/open when using --api-only.")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--serve-forever", action="store_true")
    args = parser.parse_args()

    server = start_window_workbench_server(args.html, host=args.host, port=args.port)
    url = args.frontend_url if args.api_only else server.url()
    print(f"Window workbench API: {server.url()}")
    if args.api_only:
        print(f"Vue frontend: {url}")
    else:
        print(f"Window workbench: {url}")
    if server.startup_window:
        print(f"Prepared game window: {server.startup_window['title']} ({server.startup_window['hwnd']})")
    elif server.startup_error:
        print(f"Warning: game window was not prepared: {server.startup_error}")
    if not args.no_browser:
        webbrowser.open(url)

    try:
        if args.serve_forever or args.api_only:
            while True:
                sleep(3600)
        else:
            input("Press Enter to stop the server...\n")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
