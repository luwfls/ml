import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game_bot.core.window import (
    find_window_by_process_name,
    find_window_by_title,
    get_window_info,
    set_window_topmost,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--title")
    group.add_argument("--process")
    parser.add_argument("--exact", action="store_true")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--topmost", action="store_true")
    parser.add_argument("--notopmost", action="store_true")
    args = parser.parse_args()

    visible_only = not args.include_hidden
    if args.title:
        hwnd = find_window_by_title(args.title, exact=args.exact, visible_only=visible_only)
    else:
        hwnd = find_window_by_process_name(args.process, visible_only=visible_only)

    if args.topmost:
        info = set_window_topmost(hwnd, True)
    elif args.notopmost:
        info = set_window_topmost(hwnd, False)
    else:
        info = get_window_info(hwnd)

    print(info)


if __name__ == "__main__":
    main()
