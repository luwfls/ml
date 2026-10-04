# Python 脚本组件指南

## 目标

`game_bot/scripted/` 是当前游戏操作的唯一主线编排层。

它用 Python 组件和脚本替代旧的 workflow engine 和 `workflows/*.yaml`。
后续新增游戏操作、修复玩法逻辑、迁移旧流程时，都应优先维护这里。

旧 YAML 工作流只作为遗留参考，不再新增。

## 目录分工

1. `game_bot/scripted/context.py`
   - 保存单次运行状态
   - 包括窗口句柄、`run_id`、截图路径、调试图路径、最近一次模板匹配、自定义变量
2. `game_bot/scripted/runtime.py`
   - 提供脚本动作门面
   - 包括聚焦窗口、等待、模板匹配、点击、拖拽、按键、日志、受控暂停
3. `game_bot/scripted/components/`
   - 放可复用业务组件
   - 组件表达业务意图，而不是表达单个 YAML 节点
4. `game_bot/scripted/scripts/`
   - 放最终可执行脚本
   - 一个脚本对应一个可以通过 CLI 运行的玩法任务
5. `game_bot/scripted/runner.py`
   - 脚本注册表
   - 默认窗口查找和窗口准备
   - 统一运行入口
6. `tools/run_scripted_flow.py`
   - 命令行入口

## Runtime 动作

脚本和组件应通过 `ScriptRuntime` 执行动作。

常用方法：

- `runtime.focus()`
  - 聚焦目标窗口
- `runtime.wait(duration_ms, note=...)`
  - 等待并记录日志
- `runtime.match_first(templates, threshold=..., step_name=...)`
  - 匹配模板，找不到也返回 probe
  - 适合分支和恢复逻辑
- `runtime.expect_template(templates, threshold=..., step_name=..., failure_reason=...)`
  - 匹配模板，找不到就抛 `ScriptPause(failure_reason)`
  - 适合必需状态
- `runtime.click_match(probe, delay_after_ms=..., note=...)`
  - 点击匹配结果
  - 会优先使用模板 JSON 中的 `click_region` / `click_regions`
- `runtime.drag_match(probe, direction=..., distance=..., delay_after_ms=..., note=...)`
  - 从匹配结果位置拖拽
  - 仍然走 dm-backed input
- `runtime.press_key(key, delay_after_ms=..., note=...)`
  - 发送按键
- `runtime.log(message)`
  - 输出脚本日志

不要从脚本或组件直接调用 `dm.dll` COM。
输入动作统一通过 `ScriptRuntime` 或 `game_bot.core.input`。

## 当前组件

### 导航组件

文件：`game_bot/scripted/components/navigation.py`

- `return_main_island(runtime, max_attempts=8)`
  - 尝试回到主岛
  - 处理中间可能出现的绿地点击、退出游戏否、ESC 恢复
  - 会结合弹窗组件做恢复
- `enter_main_island_battle(runtime)`
  - 先确保回主岛
  - 再点击主岛战斗入口

### 弹窗组件

文件：`game_bot/scripted/components/popups.py`

- `dismiss_configured_popup(runtime, step_prefix="popup_probe")`
  - 从 `config/popups.yaml` 读取弹窗规则
  - 逐条匹配模板
  - 当前命中后执行 `ESC`

注意：`config/popups.yaml` 属于配置 YAML，仍然可用。
弃用的是 `workflows/*.yaml` 这种游戏流程编排 YAML。

### 战斗和地下城组件

文件：`game_bot/scripted/components/battle.py`

- `enter_continuous_battle(runtime)`
  - 打开连续战斗入口
  - 如果当前没有连续战斗入口，会先点击次元之门
- `enter_kairos_dungeon(runtime)`
  - 回主岛
  - 点击次元之门
  - 点击连续战斗
  - 处理连续战斗遗留结算页
  - 点击卡伊洛斯地下城
- `start_giant_battle(runtime)`
  - 进入卡伊洛斯地下城
  - 点击巨人
  - 点击开始战斗
  - 确认进入战斗中
- `settle_repeat_battle_and_restart(runtime)`
  - 处理连续战斗结算
  - 出售所选、确认出售、再来一次、确认战斗中
- `ensure_giants_repeat_battle_running(runtime)`
  - 优先正常启动巨人战斗
  - 如果已在战斗中则直接返回
  - 如果在结算页则处理结算并重开

## 当前脚本

### `main_island_battle_entry`

文件：`game_bot/scripted/scripts/main_island_battle_entry.py`

用于回主岛并进入主岛战斗入口。

### `giants_repeat_battle`

文件：`game_bot/scripted/scripts/giants_repeat_battle.py`

用于：

1. 回主岛
2. 打开连续战斗
3. 确保巨人重复战斗已经开始
4. 如果处于结算页，则处理结算并自动重开

### `judgment_dungeon`

文件：`game_bot/scripted/scripts/judgment_dungeon.py`

用于：

1. 调用 `enter_kairos_dungeon(runtime)` 进入地下城选择页
2. 识别 `templates/icons/死亡地下城.png`
3. 从死亡地下城匹配位置向上拖拽
4. 识别并点击 `templates/icons/审判地下城/审判地下城.png`
5. 识别并点击 `templates/icons/审判地下城/审判地下城_战斗.png`

### `npc_arena`

文件：`game_bot/scripted/scripts/npc_arena.py`

用于：

1. 回主岛
2. 进入主岛战斗
3. 点击竞技场地图
4. 点击进入和挑战
5. 循环检测 NPC 是否存在
6. 若存在则进入战斗并点击开始
7. 若不存在则结束脚本

### `world_boss`

文件：`game_bot/scripted/scripts/world_boss.py`

用于：

1. 回主岛
2. 进入主岛战斗入口
3. 点击世界首领
4. 自动布置并开始战斗
5. 执行三轮世界首领
6. 最后退出到战斗菜单就绪状态

## 如何运行

列出脚本：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list
```

运行脚本：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" judgment_dungeon
```

dry-run：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" judgment_dungeon --dry-run
```

指定窗口句柄：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" judgment_dungeon --hwnd 0x480864
```

默认行为：

- 自动从 `config/settings.yaml` 读取窗口标题或进程名
- 自动准备窗口大小和置顶
- 遇到 `ScriptPause(reason)` 时打印暂停原因并返回退出码 `2`

## 新增组件的推荐写法

组件应该表达业务意图。

推荐：

```python
def enter_judgment_dungeon(runtime: ScriptRuntime) -> None:
    enter_kairos_dungeon(runtime)
    click_judgment_dungeon(runtime)
```

不推荐：

```python
def step_001(runtime: ScriptRuntime) -> None:
    ...
```

组件适合抽出来的情况：

- 多个脚本会复用
- 包含恢复、重试、弹窗处理
- 业务名清楚，例如“进入卡伊洛斯地下城”
- 单独验证有价值

组件可以不抽的情况：

- 只有某一个脚本使用
- 逻辑短且没有复用价值
- 抽出来只会制造命名负担

## 新增脚本的最小模板

```python
from __future__ import annotations

from game_bot.scripted.context import ScriptContext
from game_bot.scripted.runtime import ScriptPause, ScriptRuntime


def run_example(hwnd: int, *, dry_run: bool = False) -> ScriptContext:
    context = ScriptContext(hwnd=hwnd, script_id="example", dry_run=dry_run)
    runtime = ScriptRuntime(context)
    runtime.focus()
    try:
        runtime.wait(500, note="example wait")
        runtime.log("script completed")
    except ScriptPause as exc:
        context.variables["pause_reason"] = exc.reason
        runtime.log(f"script paused: {exc.reason}")
        raise
    return context
```

## 注册新脚本

新增脚本后，需要改两个地方。

1. 在 `game_bot/scripted/scripts/__init__.py` 导入并加入 `__all__`

```python
from game_bot.scripted.scripts.example import run_example
```

2. 在 `game_bot/scripted/runner.py` 的 `SCRIPT_REGISTRY` 中注册

```python
SCRIPT_REGISTRY = {
    "example": run_example,
}
```

注册后用下面命令确认：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list
```

## 暂停原因规范

当脚本无法继续但不是 Python 代码错误时，使用：

```python
raise ScriptPause("example_not_found")
```

规范：

- 使用英文 snake_case
- 保持稳定，便于日志检索
- 表达具体缺失或异常状态
- 不要包含动态坐标、分数、长句

示例：

- `death_dungeon_not_found`
- `judgment_dungeon_not_found`
- `judgment_dungeon_battle_not_found`
- `dimension_gate_not_found`

## 模板使用规则

模板路径建议定义为文件顶部常量：

```python
JUDGMENT_DUNGEON_TEMPLATE = "templates/icons/审判地下城/审判地下城.png"
```

匹配必需模板：

```python
probe = runtime.expect_template(
    JUDGMENT_DUNGEON_TEMPLATE,
    threshold=0.85,
    step_name="detect_judgment_dungeon",
    failure_reason="judgment_dungeon_not_found",
)
```

匹配可选模板：

```python
probe = runtime.match_first(
    JUDGMENT_DUNGEON_TEMPLATE,
    threshold=0.85,
    step_name="detect_judgment_dungeon",
)
if probe.found:
    runtime.click_match(probe)
```

如果模板 JSON 中有 `click_region` / `click_regions`，`runtime.click_match` 会使用点击区域中心，而不是直接点击整张模板中心。

## 验证建议

改动脚本或组件后，至少运行编译检查：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" -m py_compile "D:\work\monster-job32\game_bot\scripted\runtime.py" "D:\work\monster-job32\game_bot\scripted\runner.py" "D:\work\monster-job32\game_bot\scripted\components\battle.py" "D:\work\monster-job32\game_bot\scripted\scripts\judgment_dungeon.py"
```

再确认脚本注册：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list
```

涉及真实游戏状态的改动，最后用真实窗口跑一次对应脚本。

## 后续建议继续沉淀的组件

- 审判地下城入口组件
- 龙之地下城入口组件
- 死亡地下城入口组件
- 世界首领入口组件
- NPC 竞技场入口组件
- 工会 Boss 入口组件
- 通用确认框处理
- 通用结算处理
