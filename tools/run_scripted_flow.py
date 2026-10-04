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
    is_template_loop_script_file,
    load_template_loop_script,
)
from game_bot.scripted.runner import find_default_game_window, list_scripts, prepare_game_window, run_script_by_name
from game_bot.scripted.runtime import ScriptPause
from game_bot.vision.templates import list_template_groups


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or inspect scripted Monster Job flows.")
    parser.add_argument("name", nargs="?", help="Scripted flow name")
    parser.add_argument("--list", action="store_true", help="List available scripted flows")
    parser.add_argument("--list-template-groups", action="store_true", help="List available template groups")
    parser.add_argument("--validate", metavar="NAME", help="Validate a template-loop YAML without running it")
    parser.add_argument("--hwnd", type=lambda value: int(value, 0), help="Window handle in decimal or hex")
    parser.add_argument("--dry-run", action="store_true", help="Do not send input actions")
    parser.add_argument("--no-prepare", action="store_true", help="Skip window topmost/size preparation")
    parser.add_argument("--background", action="store_true", help="Keep the game window in background and prefer dm capture")
    args = parser.parse_args()

    if args.list:
        for item in list_scripts():
            print(item)
        return 0

    if args.list_template_groups:
        for group in list_template_groups(include_root=True):
            display_name = group.name or "."
            print(f"{display_name}\t{group.template_count}\t{group.relative_path}")
        return 0

    if args.validate:
        validate_target = Path(args.validate) if Path(args.validate).suffix else Path("state_scripts") / f"{args.validate}.yaml"
        if not is_template_loop_script_file(validate_target):
            parser.error("state_script YAML 已弃用；请改用 template-loop 配置（start_flows + loop_dirs）")
        definition = load_template_loop_script(args.validate)
        print(f"id={definition.id}")
        print(f"path={definition.path}")
        print(f"type=template_loop")
        print(f"start_flows={','.join(definition.start_flows) if definition.start_flows else '-'}")
        print(f"loop_dirs={','.join(definition.loop_dirs) if definition.loop_dirs else '-'}")
        print(f"end_template={definition.end_template or '-'}")
        print(f"default_threshold={DEFAULT_TEMPLATE_MATCH_THRESHOLD}")
        print(f"scales={','.join(str(scale) for scale in definition.scales)}")
        print(f"save_debug={definition.save_debug}")
        print(f"completion_count={definition.completion_count}")
        return 0

    if not args.name:
        parser.error("name is required unless --list, --list-template-groups, or --validate is used")

    hwnd = args.hwnd if args.hwnd is not None else find_default_game_window()
    if not args.no_prepare:
        info = prepare_game_window(hwnd)
        hwnd = info.hwnd
        print(f"prepared hwnd={info.hwnd} title={info.title} client={info.client_size.width}x{info.client_size.height}")

    try:
        context = run_script_by_name(args.name, hwnd, dry_run=args.dry_run, background_mode=args.background)
    except ScriptPause as exc:
        print(f"paused: {exc.reason}")
        return 2

    print(f"completed script={context.script_id} run_id={context.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
