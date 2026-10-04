# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

This is a Windows-only Python automation assistant for the game 魔灵召唤. The active automation direction is Python scripted automation under `game_bot/scripted/`, with lightweight template-loop YAML flows for template-driven repeat operations.

Deprecated game-operation paths:

- Do not create new `workflows/*.yaml` game-operation flows.
- Do not implement new game logic in `game_bot/workflow/*`.
- Do not use or revive `game_bot/scripted/state_script.py`; the state-script YAML approach has been removed.
- Use `game_bot/scripted/loop_script.py` template-loop flows for YAML-driven template automation.
- Use Python components/scripts under `game_bot/scripted/` for reusable behavior and more custom operations.

This repository is a migration/rewrite from `D:\work\monster-job`. The current target runs inside the MuMu Android emulator. Keyboard and mouse input must use the ADB backend exposed through `game_bot.core.input`; scripts and components must not invoke `adb.exe` directly. Screenshot, template recognition, Windows emulator-window control, and config loading should keep using the current project implementations unless explicitly requested. The existing `dm.dll` backend is retained only as an explicit legacy fallback.

## Development environment

- Use the checked-in virtual environment Python: `D:\work\monster-job32\venv\Scripts\python.exe`.
- ADB input does not require 32-bit Python or COM. The checked-in environment remains 32-bit for compatibility with the retained x86 `dm.dll` fallback and existing Windows modules.
- MuMu ADB executable: `D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe`.
- Current verified ADB serial: `emulator-5554`.
- `dm.dll` remains registered and `pywin32` remains available for explicit legacy fallback diagnostics.

Quick ADB smoke tests:

```powershell
& "D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe" -s "emulator-5554" devices
& "D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe" -s "emulator-5554" shell wm size
```

The observed physical size is portrait `1440x2560`, while the active input frame is landscape `2560x1440`. Do not use the physical portrait dimensions directly for input coordinates.

## Window size convention

- The target emulator host window is configured under `game.window_title` (currently `Android Device`) and `game.window_mode: android_emulator`.
- `game.window_size` is the preferred Windows emulator **client-area** size and is used only for host-window preparation; it is not the Android input resolution.
- `game.window_rect` controls the Windows desktop anchor/position of the emulator host window.
- The HTML template page should display captured screenshots at their real pixel size, not scaled up or down, so templates are made at the same size used during scripted execution.
- When the preferred size changes, update `config/settings.yaml`, this note, and all template JSON `window_client_size` metadata. Do not resize PNG assets for a metadata-only migration.

## ADB input coordinate convention

- Screenshots, template matches, template click regions, and scripted action points remain in Windows emulator **client-area pixels**.
- Before an ADB tap or swipe, `game_bot.core.input` must read the live client size and map the point to the Android **active logical display frame**. Do not use configured `game.window_size` as a substitute for live geometry.
- Baseline full-viewport mapping treats coordinates as pixel centers: `adb_x = round((client_x + 0.5) * logical_width / client_width - 0.5)` and likewise for Y, followed by bounds clamping.
- Query the active logical frame/orientation from Android input/display diagnostics. `adb shell wm size` may report portrait physical dimensions even while the game is landscape.
- Verified example: live client `1018x632`, Android logical frame `2560x1440`, client point `(572,591)` maps to ADB point `(1439,1347)`.
- If emulator chrome, letterboxing, or safe-area insets appear inside the captured client, map through an explicit viewport; never hardcode guessed offsets.

## Common commands

Compile the active Python/scripted stack:

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" -m py_compile "D:\work\monster-job32\game_bot\core\models.py" "D:\work\monster-job32\game_bot\core\geometry.py" "D:\work\monster-job32\game_bot\core\process.py" "D:\work\monster-job32\game_bot\core\window.py" "D:\work\monster-job32\game_bot\core\capture.py" "D:\work\monster-job32\game_bot\core\dm.py" "D:\work\monster-job32\game_bot\core\adb.py" "D:\work\monster-job32\game_bot\core\input.py" "D:\work\monster-job32\game_bot\config\loader.py" "D:\work\monster-job32\game_bot\vision\template.py" "D:\work\monster-job32\game_bot\vision\templates.py" "D:\work\monster-job32\game_bot\scripted\context.py" "D:\work\monster-job32\game_bot\scripted\runtime.py" "D:\work\monster-job32\game_bot\scripted\runner.py" "D:\work\monster-job32\game_bot\scripted\components\popups.py" "D:\work\monster-job32\game_bot\scripted\loop_script.py" "D:\work\monster-job32\game_bot\scripted\component_registry.py" "D:\work\monster-job32\game_bot\scripted\loop_manager.py" "D:\work\monster-job32\tools\run_scripted_flow.py" "D:\work\monster-job32\tools\run_template_loop_script.py" "D:\work\monster-job32\tools\window_probe.py" "D:\work\monster-job32\tools\window_workbench.py"
```

List available Python scripts:

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list
```

Run a scripted game operation:

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" judgment_dungeon
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" giants_repeat_battle
```

Dry-run a script without sending input:

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" judgment_dungeon --dry-run
```

Run the Python workbench API backend for the independent frontend:

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\window_workbench.py" --api-only --no-browser --port 8765
```

Start the independent Vue/Vite frontend separately:

```powershell
corepack yarn dev
```

Probe a window by title and print its handle, position, size, and client rect:

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\window_probe.py" --title "窗口标题的一部分"
```

Probe a hidden or shell window with exact title matching:

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\window_probe.py" --title "Program Manager" --exact --include-hidden
```

Set or cancel topmost for a matched window:

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\window_probe.py" --title "窗口标题的一部分" --topmost
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\window_probe.py" --title "窗口标题的一部分" --notopmost
```

There is not yet a formal test runner, lint command, packaging config, or application entrypoint in this repository.

## Current architecture

The current active foundation is:

- `game_bot/core/models.py`: shared immutable dataclasses for geometry, window metadata, matches, and input/action results.
- `game_bot/core/geometry.py`: basic geometry helpers.
- `game_bot/core/process.py`: Win32 process-name lookup used by window discovery.
- `game_bot/core/window.py`: Win32 window discovery and manipulation. It supports title/process lookup, window/client rect inspection, foreground activation, movement, resizing, docking, topmost toggling, and screen size.
- `game_bot/core/capture.py`: migrated Win32/GDI/mss screenshot implementation. `dm` capture is intentionally disabled; use `auto`, `window`, or `desktop`.
- `game_bot/core/adb.py` and `game_bot/core/input.py`: ADB transport, active-display discovery, client-to-Android coordinate mapping, and the default keyboard/mouse API. `game_bot/core/dm.py` remains an explicit legacy backend.
- `game_bot/vision/template.py` and `game_bot/vision/templates.py`: migrated OpenCV template matching and template file management.
- `game_bot/scripted/context.py`: per-run script state, screenshots/debug paths, last match, and variables.
- `game_bot/scripted/runtime.py`: script runtime facade for focus, wait, template matching, clicks, drags, keys, logging, and controlled pauses.
- `game_bot/scripted/components/*`: reusable Python business components such as navigation, popup handling, dungeon/battle entry, and popup recovery.
- `game_bot/scripted/scripts/*`: complete runnable Python game scripts for custom operations that need Python control flow.
- `game_bot/scripted/loop_script.py`: active template-loop YAML engine. It runs entry components, scans configured template groups each round, chooses a matched template by template priority first and match score second, then executes template sidecar actions.
- `game_bot/scripted/loop_manager.py`: manages template-loop processes for the local workbench.
- `game_bot/scripted/runner.py`: script registry, default game-window lookup, window preparation, and unified execution for Python scripts plus template-loop YAML scripts.
- `tools/run_scripted_flow.py`: unified CLI entrypoint for scripted operations and template-loop YAML validation/execution.
- `tools/run_template_loop_script.py`: direct CLI entrypoint for template-loop YAML scripts.
- `game_bot/web/window_bridge.py`: local workbench API backend for the independent Vue/Vite frontend. The “状态流程”/flow controls are backed by `/api/template-loop-flows` and `loop_manager`; they are template-loop controls, not the removed state-script engine.
- `game_bot/workflow/*` and `workflows/*.yaml`: legacy workflow engine and YAML definitions. Treat these as deprecated reference material unless the user explicitly asks for compatibility work or removal.

The intended high-level direction is Python scripted automation plus template-loop flows:

1. Locate and prepare the target game window through `game_bot.scripted.runner`.
2. Capture or inspect the window through the current capture stack.
3. Run template recognition through `game_bot.vision`.
4. Compose reusable behavior as Python functions under `game_bot/scripted/components`.
5. Use template-loop YAML under `state_scripts/*.yaml` for simple repeated template-driven operations (`start_components`, `loop_dirs`, optional `end_template`).
6. Use full Python scripts under `game_bot/scripted/scripts` when behavior needs richer control flow than template-loop actions.
7. Execute keyboard/mouse operations through `ScriptRuntime`, which delegates to the configured ADB backend in `game_bot.core.input`.

## Migration rules

- Source project for migration: `D:\work\monster-job`.
- Workflow engine and `workflows/*.yaml` are deprecated for game operations. Do not create new legacy workflow files for gameplay automation.
- Do not extend `game_bot/workflow/*` for new gameplay automation unless the user explicitly asks for legacy compatibility or cleanup.
- The removed `state_script.py` state-script YAML engine must not be revived.
- Template-loop YAML under `state_scripts/*.yaml` is still active for template-driven repeat operations.
- Config YAML files under `config/` are still allowed for settings, targets, popups, regions, and policy.
- Do not blindly copy old input code. Keyboard and mouse capabilities must be implemented through `game_bot.core.input` and its ADB backend; low-level ADB commands belong only in `game_bot.core.adb`.
- Do not use `pywinauto`, `keybd_event`, `SendInput`, or window-message input paths unless the user explicitly changes the input strategy.
- Screenshot, template recognition, window discovery, and config loading should keep using the current project stack; ADB is for input only unless explicitly requested.
- Keep Windows-specific assumptions explicit. The host remains Windows and controls/captures the emulator window, while input targets Android through a configured ADB serial.
- Keep dm.dll as an explicit legacy backend only; do not silently fall back from a broken ADB connection or unknown coordinate mapping.
- Avoid adding new framework layers before the corresponding scripted capability exists.

## Scripted maintenance rules

- Put reusable behavior in `game_bot/scripted/components/`.
- Put complete custom Python game tasks in `game_bot/scripted/scripts/`, and register them in both `game_bot/scripted/scripts/__init__.py` and `game_bot/scripted/runner.py`.
- Put template-loop YAML flows in `state_scripts/*.yaml` using `start_components`, `loop_dirs`, optional `end_template`, and template sidecar JSON actions.
- In template-loop matching, sidecar `priority` is authoritative before match score; higher priority matched templates execute first.
- Use `ScriptPause(reason)` for controlled stops. Keep `reason` stable and descriptive.
- Use `runtime.expect_template(...)` when a missing template should pause Python scripts.
- Use `runtime.match_first(...)` when a Python script can branch or recover from a missing template.
- Use `runtime.click_match(...)`, `runtime.drag_match(...)`, and `runtime.press_key(...)` for input. Do not call `adb.exe`, ADB shell input commands, or COM directly from scripts/components.
- Template sidecar JSON click regions are honored by the runtime and template-loop actions. Keep template click regions accurate when creating or editing templates.

## Documentation

- `docs/adb_input_backend.md`: ADB transport, coordinate mapping, input semantics, limitations, and verification notes.
- `docs/scripted_automation_migration.md`: migration policy and how to move away from legacy workflow YAML.
- `docs/scripted_components_guide.md`: component/script authoring guide.
- `docs/kairos_component_note.md`: current notes for the shared Kairos dungeon component.
- `docs/archive/*`: legacy state-script design notes, kept only as historical reference.

## Input backend convention

- Game scripts and components use `ScriptRuntime`; lower-level callers use `game_bot.core.input`.
- `config/settings.yaml` selects the backend. The default is `adb`; `dm` is retained only for explicit legacy compatibility.
- Only `game_bot.core.adb` may invoke `adb.exe`. It must pass the configured serial on every command and reject ambiguous device selection.
- ADB touch input supports left tap and swipe. Right click has no portable Android equivalent and must fail explicitly. Key hold duration and dm drag `steps` are not equivalent under standard ADB input commands.
- Scroll is implemented as a touch swipe. `up` and `down` describe content movement, not finger movement.
- Never send a client/window/template coordinate directly to ADB; always use the live coordinate mapper described above.
