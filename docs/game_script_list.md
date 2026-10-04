# 游戏脚本调用列表

当前可通过 `tools/run_scripted_flow.py` 直接调用的 Python 游戏脚本共有 **5** 个。

这些名称来自 `game_bot/scripted/runner.py` 里的 `SCRIPT_REGISTRY`。调用时把“脚本名”作为第一个参数传入即可。

## 调用方式

查看当前可用脚本：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list
```

运行指定脚本：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" <脚本名>
```

常用调试参数：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" <脚本名> --dry-run
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" <脚本名> --hwnd 0x00123456
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" <脚本名> --no-prepare
```

## Python 脚本清单

| 序号 | 调用时指定的脚本名 | 用途 | 入口函数 | 文件 |
|---:|---|---|---|---|
| 1 | `giants_repeat_battle` | 回主岛，打开连续战斗，并确保巨人重复战斗已经开始；如果处于结算页，会尝试处理结算并重开。 | `run_giants_repeat_battle` | `game_bot/scripted/scripts/giants_repeat_battle.py` |
| 2 | `judgment_dungeon` | 进入卡伊洛斯地下城，滚动到审判地下城，点击审判地下城战斗入口。 | `run_judgment_dungeon` | `game_bot/scripted/scripts/judgment_dungeon.py` |
| 3 | `main_island_battle_entry` | 回主岛并进入主岛战斗入口。 | `run_main_island_battle_entry` | `game_bot/scripted/scripts/main_island_battle_entry.py` |
| 4 | `npc_arena` | 回主岛，进入竞技场 NPC 挑战页，循环挑战直到检测不到 NPC。 | `run_npc_arena` | `game_bot/scripted/scripts/npc_arena.py` |
| 5 | `world_boss` | 回主岛，进入世界 Boss，自动布阵并执行 3 轮世界 Boss 战斗流程。 | `run_world_boss` | `game_bot/scripted/scripts/world_boss.py` |

## 复制可用命令

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" giants_repeat_battle
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" judgment_dungeon
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" main_island_battle_entry
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" npc_arena
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" world_boss
```

## 旧 YAML workflow 文件

仓库里 `workflows/` 目录下还保留了 **11** 个 YAML workflow。它们不是 `run_scripted_flow.py` 的调用参数，主要给旧 workflow 引擎和 HTML 工作台使用。

| 序号 | workflow 文件 |
|---:|---|
| 1 | `workflows/auto_arena.yaml` |
| 2 | `workflows/continuous_battle_entry.yaml` |
| 3 | `workflows/drag_left_demo.yaml` |
| 4 | `workflows/dungeon_entry.yaml` |
| 5 | `workflows/giants_repeat_battle.yaml` |
| 6 | `workflows/guild_boss.yaml` |
| 7 | `workflows/guild_boss_chief.yaml` |
| 8 | `workflows/main_island_battle_entry.yaml` |
| 9 | `workflows/npc_arena.yaml` |
| 10 | `workflows/return_main_island.yaml` |
| 11 | `workflows/world_boss.yaml` |

## 新增脚本后需要同步的位置

新增 Python 游戏脚本后，记得同步注册到：

- `game_bot/scripted/scripts/__init__.py`
- `game_bot/scripted/runner.py` 的 `SCRIPT_REGISTRY`

注册完成后，`tools/run_scripted_flow.py --list` 才会显示新脚本，也才能通过脚本名调用。
