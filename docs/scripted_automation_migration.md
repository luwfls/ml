# Python 脚本化自动化迁移说明

## 结论

游戏操作编排已经切换到 Python 脚本维护。

后续新增、修复、迁移游戏自动化逻辑时，默认只使用：

- `game_bot/scripted/runtime.py`
- `game_bot/scripted/components/`
- `game_bot/scripted/scripts/`
- `game_bot/scripted/runner.py`
- `tools/run_scripted_flow.py`

旧的流程引擎和 YAML 工作流不再作为游戏操作的维护方向。

## 弃用范围

以下内容视为遗留实现，只能作为参考材料：

- `game_bot/workflow/*`
- `workflows/*.yaml`
- workflow 节点跳转、transition、branch、loop 等流程图式编排
- 可视化 workflow 编辑器里的流程编辑和流程运行能力

不要再新增 `workflows/*.yaml` 游戏脚本。
不要为了新玩法扩展 `game_bot/workflow/*`。

如果确实需要处理旧流程兼容、读取历史运行记录、或删除遗留代码，需要先明确这是“遗留兼容/清理”任务，而不是新的游戏操作开发。

## 保留范围

弃用的是“游戏操作编排层”，不是整个 YAML 或工具层。

以下能力继续保留并复用：

- `game_bot/core/window.py`
  - 查找窗口、准备窗口、置顶、调整 client size
- `game_bot/core/capture.py`
  - Win32/GDI/mss 截图
- `game_bot/core/input.py`
  - dm-backed 鼠标、键盘、拖拽、滚轮输入
- `game_bot/core/dm.py`
  - 注册 `dm.dll` 的低层封装
- `game_bot/vision/template.py`
  - OpenCV 模板匹配
- `game_bot/vision/templates.py`
  - 模板文件管理
- `game_bot/config/loader.py`
  - 配置读取
- `config/*.yaml`
  - settings、popups、targets、regions 等配置 YAML
- `tools/window_workbench.py`
  - 仍可作为窗口、截图、模板制作工作台

`config/*.yaml` 仍然可以用。
被弃用的是 `workflows/*.yaml` 这类“游戏流程编排 YAML”。

## 新编排层

新的编排层在 `game_bot/scripted/`。

目录职责：

- `context.py`
  - 保存一次脚本运行的状态
  - 包括 `run_id`、截图目录、调试目录、最近匹配、点击区域、自定义变量
- `runtime.py`
  - 提供脚本动作门面
  - 包括 `focus`、`wait`、`match_first`、`expect_template`、`click_match`、`drag_match`、`press_key`、日志
- `components/`
  - 放可复用业务组件
  - 例如回主岛、进入连续战斗、进入卡伊洛斯地下城、处理弹窗
- `scripts/`
  - 放完整可执行游戏脚本
  - 一个文件通常对应一个用户能直接运行的玩法任务
- `runner.py`
  - 脚本注册表
  - 默认游戏窗口查找
  - 窗口准备
  - 统一运行入口

命令行入口：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" judgment_dungeon
```

## 当前脚本状态

当前已注册脚本包括：

- `main_island_battle_entry`
- `giants_repeat_battle`
- `judgment_dungeon`
- `npc_arena`
- `world_boss`

以 `judgment_dungeon` 为例，脚本路径是：

- `game_bot/scripted/scripts/judgment_dungeon.py`

它复用 `enter_kairos_dungeon(runtime)` 组件，然后执行审判地下城相关选择：

1. 识别 `templates/icons/死亡地下城.png`
2. 从该匹配位置向上拖拽
3. 识别并点击 `templates/icons/审判地下城/审判地下城.png`
4. 识别并点击 `templates/icons/审判地下城/审判地下城_战斗.png`

## 迁移原则

迁移旧 YAML 工作流时，不要逐节点机械翻译。

推荐做法：

1. 先识别可复用业务意图
   - 回主岛
   - 打开次元之门
   - 进入连续战斗
   - 选择某个地下城
   - 点击战斗
   - 处理结算
   - 处理弹窗
2. 把可复用意图沉淀为 `components/` 函数
3. 把最终玩法串成 `scripts/` 下的可运行脚本
4. 用 Python 控制流表达重试、分支、恢复逻辑
5. 用稳定的 `ScriptPause(reason)` 表达人工接管点

不推荐做法：

- 把 YAML 节点 1:1 翻译成很多低语义 Python 函数
- 在脚本里堆大量模板名、点击、等待，导致无法复用
- 从脚本或组件直接调用 `dm.dll` COM 方法
- 为新玩法继续扩展 workflow engine

## 输入策略

键盘和鼠标输入必须继续走 dm-backed 封装。

脚本和组件应优先使用：

- `runtime.click_match(...)`
- `runtime.drag_match(...)`
- `runtime.press_key(...)`

低层能力来自：

- `game_bot.core.input.click_client`
- `game_bot.core.input.drag_client`
- `game_bot.core.input.press_key`
- `game_bot.core.input.scroll_client`

不要在脚本中直接使用：

- `pywinauto`
- `keybd_event`
- `SendInput`
- window-message 输入
- 裸 `win32com.client.Dispatch("dm.dmsoft")`

## 模板和点击区域

模板图像继续放在 `templates/` 下。

模板 sidecar JSON 中的 `click_region` / `click_regions` 会被 scripted runtime 用来计算点击点。
这对宽模板尤其重要，例如按钮只在模板右侧时，不应该点击模板中心。

制作或调整模板时，需要确认：

- 截图尺寸与脚本运行窗口尺寸一致
- 模板图像有足够视觉差异
- `click_region` 落在真实可点击区域
- 文件名稳定，不随意改名

## 受控暂停

缺少关键模板、状态异常、恢复失败时，组件或脚本应抛出：

```python
raise ScriptPause("stable_reason")
```

`reason` 要稳定、短、可检索。

推荐：

- `judgment_dungeon_not_found`
- `dimension_gate_not_found`
- `repeat_battle_not_found`

不推荐：

- `failed`
- `error`
- `没找到`
- 动态拼接很长的 UI 文本

## 推荐迁移顺序

1. 继续补强基础 runtime 能力
   - 点击
   - 拖拽
   - 按键
   - 模板点击区域
   - 日志和截图调试
2. 沉淀通用组件
   - 导航
   - 卡伊洛斯地下城入口
   - 连续战斗结算
   - 弹窗处理
3. 迁移具体玩法脚本
   - 地下城类
   - 竞技场类
   - 世界首领
   - 工会 Boss
4. 等 Python 脚本覆盖常用玩法后，再考虑清理 workflow engine 和 workflow YAML

## 验证方式

最小验证：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" -m py_compile "D:\work\monster-job32\game_bot\scripted\runtime.py" "D:\work\monster-job32\game_bot\scripted\runner.py"
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list
```

真实窗口验证：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" judgment_dungeon
```

只验证识别和日志、不发送输入：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" judgment_dungeon --dry-run
```
