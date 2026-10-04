# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project context

This is a Windows-only Python automation assistant for the game 魔灵召唤. The game now runs in the MuMu Android emulator: Windows APIs remain responsible for window control, capture, and template recognition, while keyboard/mouse input is sent through the ADB backend in `game_bot.core.input`.

This repository is a migration/rewrite from `D:\work\monster-job`. Scripts and workflows must use the input facade and must not execute `adb.exe` directly. `dm.dll` remains only as an explicit legacy fallback. ADB coordinates must be mapped from the live Windows client size to Android's active logical display; do not send Windows client coordinates directly.

## Development environment

- Use the checked-in virtual environment Python: `D:\work\monster-job32\venv\Scripts\python.exe`.
- This project intentionally uses 32-bit Python because the registered `dm.dll` is x86.
- `dm.dll` has already been registered in the system and can be created through COM as `dm.dmsoft`.
- `pywin32` is available in the project virtual environment.

Quick `dm.dll` smoke test:

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" -c "import win32com.client; dm = win32com.client.Dispatch('dm.dmsoft'); print(dm.Ver())"
```

Expected version currently observed: `3.1233`.

## Window size convention

- The preferred game client area size is stored in `config/settings.yaml` under `game.window_size` and should be read from that config by window preparation code.
- The current configured size is `1115x627`.
- Do not hardcode window dimensions in workflow/editor/runtime code. If the preferred size changes, update `config/settings.yaml` and this note.
- The HTML template page should display captured screenshots at their real pixel size, not scaled up or down, so templates are made at the same size used during workflow execution.

## Common commands

Compile current project modules:

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" -m py_compile "D:\work\monster-job32\game_bot\core\models.py" "D:\work\monster-job32\game_bot\core\geometry.py" "D:\work\monster-job32\game_bot\core\process.py" "D:\work\monster-job32\game_bot\core\window.py" "D:\work\monster-job32\game_bot\core\capture.py" "D:\work\monster-job32\game_bot\core\dm.py" "D:\work\monster-job32\game_bot\core\input.py" "D:\work\monster-job32\game_bot\config\loader.py" "D:\work\monster-job32\game_bot\vision\template.py" "D:\work\monster-job32\game_bot\vision\templates.py" "D:\work\monster-job32\game_bot\workflow\models.py" "D:\work\monster-job32\game_bot\workflow\loader.py" "D:\work\monster-job32\game_bot\workflow\context.py" "D:\work\monster-job32\game_bot\workflow\recorder.py" "D:\work\monster-job32\game_bot\workflow\engine.py" "D:\work\monster-job32\game_bot\workflow\nodes.py" "D:\work\monster-job32\game_bot\web\window_bridge.py" "D:\work\monster-job32\tools\window_probe.py" "D:\work\monster-job32\tools\window_workbench.py"
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

The codebase is still early-stage. The current migrated foundation is:

- `game_bot/core/models.py`: shared immutable dataclasses for geometry and window metadata (`Point`, `Size`, `Rect`, `WindowInfo`). Keep these small because later screenshot, recognition, and workflow modules should share them.
- `game_bot/core/geometry.py`: basic geometry helpers.
- `game_bot/core/process.py`: Win32 process-name lookup used by window discovery.
- `game_bot/core/window.py`: Win32 window discovery and manipulation. It supports title/process lookup, window/client rect inspection, foreground activation, movement, resizing, docking, topmost toggling, and screen size.
- `game_bot/core/capture.py`: migrated Win32/GDI/mss screenshot implementation. `dm` capture is intentionally disabled; use `auto`, `window`, or `desktop`.
- `game_bot/core/adb.py` and `game_bot/core/input.py`: ADB transport, coordinate mapping, and default keyboard/mouse API. `game_bot/core/dm.py` is the explicit legacy fallback.
- `game_bot/vision/template.py` and `game_bot/vision/templates.py`: migrated OpenCV template matching and template file management.
- `game_bot/workflow/*`: migrated workflow model, loader, runtime context, recorder, engine, and nodes.
- `game_bot/web/window_bridge.py`: lightweight local API bridge for the independent Vue/Vite workbench. It exposes window, screenshot, template, workflow, and run-log APIs.
- `frontend/`: independent Vue 2 + Element UI + Vite workbench frontend.
- `tools/window_probe.py`: direct CLI utility for manually verifying window lookup and topmost behavior during migration.
- `tools/window_workbench.py`: starts the local workbench API backend, or serves the built frontend entry when not using `--api-only`.

The intended high-level direction is a workflow-oriented automation tool:

1. Locate the target game window.
2. Capture or inspect the emulator window through the current Win32 capture stack.
3. Run image/recognition logic in Windows client coordinates.
4. Map client coordinates to Android's active logical display and execute input through the ADB wrapper.
5. Compose the above into reusable workflows.

## Migration rules

- Source project for migration: `D:\work\monster-job`.
- Do not blindly copy old input code. Keyboard and mouse capabilities must be implemented through `game_bot.core.input` and its configured ADB backend.
- Do not use `pywinauto`, `keybd_event`, `SendInput`, window-message input, or raw ADB calls outside `game_bot.core.adb` unless the user explicitly changes the input strategy.
- Screenshot, template recognition, workflow loading/running, and similar non-input capabilities preserve the current Windows implementation; ADB is for input only unless requested.
- Use the live client size and Android active logical frame for coordinate conversion. `wm size` may report portrait physical dimensions while input is landscape.
- Keep dm.dll only as an explicitly selected legacy backend; never silently fall back from ADB failures.
- Avoid adding new framework layers before the corresponding migrated capability exists.

## Input backend convention

Keyboard/mouse callers use `game_bot.core.input`; only `game_bot.core.adb` may invoke `adb.exe`. The default backend comes from `config/settings.yaml` and is `adb`; `dm` is an explicit compatibility option. ADB touch supports tap and swipe, not portable right-click semantics. Convert all client points through the live client-to-Android mapper before sending input.
