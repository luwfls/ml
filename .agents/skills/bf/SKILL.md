---
name: bf
description: Build workflow 的简写。将自然语言流程描述解析为 Monster Job 标准 workflow YAML 或 JSON 配置。适用于用户说“用 bf”“创建流程编排”“把这个流程转成 workflow”“输出任务编排配置/YAML/JSON”等场景。
---

# BF Skill

你是 Monster Job 项目的任务编排配置生成器。你的目标是把用户输入的自然语言流程，转换成本项目标准 workflow 配置。

## 适用场景

当用户要求：

- 创建流程编排
- 解析流程描述
- 生成 workflow YAML
- 生成 workflow JSON
- 把步骤转成 `workflows/*.yaml`
- 设计一个可运行的任务编排配置

就使用本 skill。

## 模板图标感知

使用本 skill 生成 workflow 前，先读取 `templates/icons/*` 下的现有图标列表，并把这些文件视为当前可直接引用的模板资源。

当前读取到的图标示例：

- `templates/icons/cy.png`

生成 `template_match` 时遵循：

1. 如果用户提到的目标能明显对应现有图标，优先直接使用 `template: templates/icons/<filename>`。
2. 如果用户要求“检测多个可能图标”，优先从现有图标列表中选择并生成 `templates: [...]`。
3. 如果没有对应图标，不要编造文件名；使用清晰的 TODO 占位，例如 `template: templates/icons/TODO_reward_button.png`，并提示需要补充模板图。
4. 如果用户新增或删除模板图，下一次使用本 skill 时应重新读取 `templates/icons/*`，不要只依赖本文档中的示例列表。

## 项目 workflow 格式

标准 YAML 顶层结构：

```yaml
id: example_workflow
name: 示例流程
start: shot
max_steps: 50
max_failures: 3

nodes:
  shot:
    type: screenshot
    next: detect_target

  detect_target:
    type: template_match
    target: battle_settings
    save_debug: true
    transitions:
      - when: found
        to: click_target
      - when: not_found
        to: wait_retry

  click_target:
    type: click
    point_from: last_match.center
    next: wait_after_click

  wait_after_click:
    type: wait
    duration_ms: 500
    next: shot

  pause:
    type: pause
    reason: unknown_state
```

## 支持的节点类型

### screenshot

用于截取当前绑定窗口客户区。

```yaml
shot:
  type: screenshot
  next: detect_target
```

### template_match

用于模板识别。优先使用 `target` 引用 `config/targets.yaml`。如果一个识别节点需要匹配多个模板，使用 `templates` 数组，默认 OR 关系：任一模板达到阈值就是 `found`。

```yaml
detect_target:
  type: template_match
  target: battle_settings
  save_debug: true
  transitions:
    - when: found
      to: click_target
    - when: not_found
      to: wait_retry
```

也可直接使用模板路径：

```yaml
detect_target:
  type: template_match
  template: templates/icons/button.png
  threshold: 0.85
  region: battle_controls
  scales: [0.9, 1.0, 1.1]
  save_debug: true
  transitions:
    - when: found
      to: click_target
    - when: not_found
      to: pause_not_found
```

多个模板使用 `templates`，表示 OR 关系：

```yaml
detect_target:
  type: template_match
  templates:
    - templates/icons/cy.png
    - templates/icons/cy1.png
    - templates/icons/cy2.png
  threshold: 0.85
  save_debug: true
  transitions:
    - when: found
      to: click_target
    - when: not_found
      to: pause_not_found
```

### click

仅允许客户区坐标或识别结果中心点，不允许屏幕绝对坐标。

```yaml
click_fixed:
  type: click
  point: [100, 200]
  next: wait_after_click
```

```yaml
click_detected:
  type: click
  point_from: last_match.center
  offset: [0, 10]
  next: wait_after_click
```

### key

用于发送单键。

```yaml
press_esc:
  type: key
  key: esc
  next: wait_close
```

### wait

```yaml
wait_retry:
  type: wait
  duration_ms: 1000
  next: shot
```

### branch

第一版只稳定支持：`last_match.found`。

```yaml
check_found:
  type: branch
  condition: last_match.found
  true: click_target
  false: wait_retry
```

### pause

```yaml
pause_unknown:
  type: pause
  reason: unknown_state
```

### end

```yaml
done:
  type: end
  result: success
```

## 生成原则

1. 默认输出 YAML，除非用户明确要求 JSON。
2. 默认生成可保存到 `workflows/<id>.yaml` 的完整配置。
3. 所有流程必须有 `max_steps` 和 `max_failures`。
4. 所有流程必须有清晰起点和终点：`start` 必须指向第一个真实节点，正常完成必须进入 `end`，失败 / 未知 / 找不到关键目标必须进入 `pause`。
5. 不要乱连线：只生成用户描述中明确存在的路径；不要让多个无关节点都指向同一个 wait；不要为了凑图随意添加跳转。
6. `template_match` 的找到 / 找不到必须优先使用 `transitions`：`found` 和 `not_found`，不要把它们写成普通 `next` / `on_fail` 来表达。
7. 默认不要生成独立 `screenshot` 节点；`template_match` 会自动截图。除非用户明确要求单独截图节点，否则直接让前置节点指向下一个 `template_match`。
8. “识别 X 并点击 / 找到就点它”必须合并到 `template_match` 节点中：设置 `click: true`、`click_point_from: last_match.center`，成功分支使用 `matched_clicked`；不要再生成独立 `click` 节点。
9. 模板匹配默认 `threshold: 0.85`。除非用户明确指定其它阈值，所有直接模板路径和模板数组匹配都写 `threshold: 0.85`。
10. `branch` 节点只用于变量条件，例如 `last_match.found`；模板识别本身不要额外再包一层 branch，直接用 `template_match.transitions`。
8. 所有循环必须通过 `max_steps` 或明确重试分支保护；循环路径必须语义清楚，例如 `wait_after_click -> shot` 或 `wait_retry -> shot`。
9. 遇到未知状态、连续找不到目标、关键条件不满足时，应进入 `pause`，不要无限盲跑。
10. 点击优先使用 `point_from: last_match.center`。
11. 如果用户没有明确点击坐标，不要编造固定坐标；应使用模板识别中心点，或标注需要用户补充 target/template。
12. 不生成屏幕绝对坐标。
13. 节点 ID 使用小写 snake_case，语义清晰，例如 `detect_battle_button`、`click_reward`。
14. 对不确定的 target/template，用占位名但要清楚，例如 `TODO_reward_button_target`。
15. 多个模板表示“任意一个命中即可”时，使用 `templates: [...]`，这是 OR 关系；不要拆成多个串行 `detect_x` 节点，除非用户明确要求按顺序逐个处理。
16. 除 `end` 节点外，所有节点必须有明确下游：普通节点必须有 `next` 或 `on_fail`，`template_match` 必须有 `found` 和 `not_found` transitions，`branch` 必须有 `true` 和 `false`。如果用户没有说明某个下游，默认指向正常结束节点 `done`，不要留下断头节点。

## 规范流程图规则

生成前先在脑中画出规范流程图：

```text
开始
  ↓
shot
  ↓
detect_x
  ├─ found → click_x → wait_after_click → done 或 shot
  └─ not_found → wait_retry → shot 或 pause_not_found
```

硬性规则：

- “开始”不是 YAML 节点，YAML 用顶层 `start: shot` 表达开始。
- “结束”必须是真实 `end` 节点，例如 `done`。
- 暂停必须是真实 `pause` 节点，例如 `pause_not_found`。
- `pause` 节点如果没有用户指定的恢复路径，也必须有 `next: done`，避免 HTML 图中出现断头死胡同；只有 `end` 节点可以没有下游。
- `template_match` 节点的 `found/not_found` 是专用分支，必须写在 `transitions` 中。
- 普通 `next` 只表示无条件下一步，例如 `screenshot -> detect`、`click -> wait`、`wait -> shot/done`。
- 失败路径不要伪装成 `on_fail`，除非节点执行错误才需要 `on_fail`；模板找不到应使用 `not_found` transition。
- 如果流程描述没有“循环继续”，点击后应进入 `done`，不要默认回到 `shot`。
- 如果流程描述有“循环/继续检测/重试”，等待节点才能回到 `shot`。

## 解析用户流程的方法

把用户描述拆成这些元素：

- 起点：通常是 `screenshot`。
- 识别：需要找什么按钮/图标/状态。
- 动作：点击、按键、等待。
- 分支：找到/没找到、成功/失败。
- 循环：等待后回到截图或识别。
- 终点：成功结束或暂停。

常见自然语言映射：

- “截图” → 通常不生成单独节点，因为 `template_match` 自动截图；只有用户明确要求保存截图/独立截图时才生成 `screenshot`
- “找/识别/检测 X” → `template_match`，默认 `threshold: 0.85`
- “找到了就点它 / 识别并点击 X” → `template_match` 内设置 `click: true`、`click_point_from: last_match.center`，成功 transition 用 `matched_clicked`
- “只识别不点击” → `template_match` 不设置 `click: true`，成功 transition 用 `found`
- “没找到等一下再试” → `template_match.transitions[not_found]` → `wait` → 回到对应 `template_match`
- “失败就暂停” → `pause`
- “按 ESC/回车” → `key`
- “循环直到出现 X” → `template_match → found/matched_clicked 分支 / not_found wait loop`
- “完成后结束” → `end`

## 前端预览联动

旧的 `tools/workflow_editor.html` 已移除。需要预览或编辑流程时，启动 Python API 后端和独立 Vue/Vite 前端：

```powershell
.\venv\Scripts\python.exe .\tools\window_workbench.py --api-only --no-browser --port 8765
corepack yarn dev
```

前端默认地址是 `http://127.0.0.1:5173`。

## 输出格式

如果用户只要求生成配置，直接输出：

```yaml
...
```

如果用户要求创建文件，应：

1. 生成文件到 `workflows/<workflow_id>.yaml` 或用户指定路径。
2. 使用命令校验：

```powershell
.\venv\Scripts\python.exe main.py workflow-validate --workflow workflows/<workflow_id>.yaml
```

3. 校验通过后打开 HTML workflow 编辑器，并通过 `?workflow=<workflow_id>.yaml` 自动展示该流程。
4. 简短报告文件路径、校验结果和 HTML 预览状态。

## YAML 输出模板

```yaml
id: <workflow_id>
name: <显示名称>
start: shot
max_steps: 50
max_failures: 3

nodes:
  shot:
    type: screenshot
    next: <first_detect_node>

  <first_detect_node>:
    type: template_match
    target: <target_name>
    save_debug: true
    transitions:
      - when: found
        to: <success_node>
      - when: not_found
        to: <retry_or_pause_node>

  <retry_or_pause_node>:
    type: wait
    duration_ms: 1000
    next: shot
```

## JSON 输出结构

仅当用户明确要求 JSON 时输出：

```json
{
  "id": "example_workflow",
  "name": "示例流程",
  "start": "shot",
  "max_steps": 50,
  "max_failures": 3,
  "nodes": {
    "shot": {
      "type": "screenshot",
      "next": "detect_target"
    }
  }
}
```

注意：当前项目 loader 第一优先支持 YAML。JSON 主要用于 HTML 编辑器或外部转换，若用户要直接运行，应建议保存为 YAML。

## 质量检查清单

生成前自查：

- `start` 指向的节点存在。
- 每个 `next`、`on_fail`、`transitions.to` 都指向存在节点。
- 除 `end` 外，每个节点都至少有一个下游；不知道去哪里时指向 `done`。
- `template_match` 必须同时有 `found` 和 `not_found` 两条 transition。
- `branch` 必须同时有 `true` 和 `false`。
- 循环有 `max_steps`。
- 点击没有使用屏幕绝对坐标。
- `template_match` 至少有 `target`、`template` 或 `templates`。
- `template_match` 找到/找不到必须有 `transitions: found/not_found`，除非用户明确只想检测不分支。
- `wait.duration_ms` 是非负整数。
- `key.key` 非空。
- 暂停节点有 `reason`。

## 示例

用户输入：

> 先截图，识别战斗设置按钮，找到就点，点完等 500ms 后继续截图；找不到就等 1 秒重试。

输出：

```yaml
id: battle_settings_loop
name: 战斗设置循环
start: shot
max_steps: 100
max_failures: 3

nodes:
  shot:
    type: screenshot
    next: detect_battle_settings

  detect_battle_settings:
    type: template_match
    target: battle_settings
    save_debug: true
    transitions:
      - when: found
        to: click_battle_settings
      - when: not_found
        to: wait_retry

  click_battle_settings:
    type: click
    point_from: last_match.center
    next: wait_after_click

  wait_after_click:
    type: wait
    duration_ms: 500
    next: shot

  wait_retry:
    type: wait
    duration_ms: 1000
    next: shot

  done:
    type: end
    result: success

  pause_not_found:
    type: pause
    reason: battle_settings_not_found
```

注意：这个例子因为用户明确说“继续截图”和“重试”，所以等待后回到 `shot`。如果用户只说“找到后点击，完成后结束”，则 `wait_after_click.next` 应该指向 `done`，不要默认循环。
