import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from game_bot.scripted.loop_script import (
    DEFAULT_TEMPLATE_MATCH_THRESHOLD,
    load_template_loop_script,
    run_template_loop_script_by_name,
)
from game_bot.scripted.runner import find_default_game_window, prepare_game_window
from game_bot.scripted.runtime import ScriptPause


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a lightweight template loop script.")
    parser.add_argument("name", help="Template loop script name or YAML filename")
    parser.add_argument("--validate", action="store_true", help="Validate without running")
    parser.add_argument("--hwnd", type=lambda value: int(value, 0), help="Window handle in decimal or hex")
    parser.add_argument("--dry-run", action="store_true", help="Do not send input actions")
    parser.add_argument("--no-prepare", action="store_true", help="Skip window topmost/size preparation")
    parser.add_argument("--background", action="store_true", help="Keep the game window in background and prefer dm capture")
    parser.add_argument("--run-start-flows-first", action="store_true", help="Run configured entry state flows before loop matching")
    parser.add_argument("--no-log-file", action="store_true", help="Do not tee runtime output to the flow .log file")
    args = parser.parse_args()

    definition = load_template_loop_script(args.name)
    if args.validate:
        print(f"id={definition.id}")
        print(f"path={definition.path}")
        print(f"log_path={definition.log_path}")
        print(f"start_flows={','.join(definition.start_flows)}")
        print(f"loop_dirs={','.join(definition.loop_dirs)}")
        print(f"end_template={definition.end_template or '-'}")
        print(f"default_threshold={DEFAULT_TEMPLATE_MATCH_THRESHOLD}")
        print(f"scales={','.join(str(scale) for scale in definition.scales)}")
        print(f"save_debug={definition.save_debug}")
        print(f"completion_count={definition.completion_count}")
        return 0

    hwnd = args.hwnd if args.hwnd is not None else find_default_game_window()
    if not args.no_prepare:
        info = prepare_game_window(hwnd)
        hwnd = info.hwnd
        print(f"prepared hwnd={info.hwnd} title={info.title} client={info.client_size.width}x{info.client_size.height}")

    try:
        context = run_template_loop_script_by_name(
            definition.path,
            hwnd,
            dry_run=args.dry_run,
            background_mode=args.background,
            run_start_flows_first=args.run_start_flows_first,
            log_to_file=not args.no_log_file,
        )
    except ScriptPause as exc:
        print(f"paused: {exc.reason}")
        return 2

    print(f"completed script={context.script_id} run_id={context.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
