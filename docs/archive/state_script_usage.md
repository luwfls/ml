# 状态驱动脚本使用说明

> [!WARNING]
> `state_script.py` / state-script YAML 已弃用。当前仓库仅保留 `template-loop` 作为 YAML 驱动执行方案。
> 下文内容仅供历史参考，不能再作为新流程实现方式。

## 目的

当前新的脚本方案，已经从“按流程顺序写死的 Python 脚本”切到“YAML 配置驱动的状态脚本”。

目标是：

1. 固定入口负责把画面带到目标场景。
2. 入口是否成功，以识别到指定模板为准。
3. 主循环每轮只截图一次。
4. 在同一张截图上判断当前命中了哪个状态。
5. 根据状态绑定的动作执行点击、拖拽、按键、等待、调用组件等操作。
6. 新增一个脚本时，优先只增加一个 YAML 文件。

## 目录约定

状态脚本统一放在：

```text
state_scripts/
```

例如：

```text
state_scripts/giants_repeat_battle.yaml
```

模板目录当前主要使用：

```text
templates/icons/
```

其中已经支持按分组组织模板，例如：

```text
templates/icons/连续战斗/
templates/icons/弹窗/
templates/icons/地图_竞技场/
```

## 快速开始

### 1. 查看可用脚本

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list
```

### 2. 查看可复用组件

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list-components
```

### 3. 查看模板分组

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list-template-groups
```

### 4. 校验脚本配置

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --validate giants_repeat_battle
```

### 5. 运行脚本

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" giants_repeat_battle
```

常用调试方式：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" giants_repeat_battle --dry-run
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" giants_repeat_battle --background
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" giants_repeat_battle --hwnd 0x00123456
```

## 新脚本创建流程

推荐流程：

1. 先确认这个玩法需要哪些模板组。
2. 先确认入口是否已有可复用组件。
3. 复制一个现有 YAML。
4. 修改入口配置和状态列表。
5. 先执行 `--validate`。
6. 再用 `--dry-run` 或真实窗口验证。

如果只是新增一个玩法脚本，优先不要再去写新的 `game_bot/scripted/scripts/*.py`。

## 配置文件编写说明

## 顶层结构

一个最小可用的脚本配置如下：

```yaml
script:
  id: giants_repeat_battle
  template_groups:
    - 连续战斗
  common_groups:
    - 弹窗
  loop_interval_ms: 1000
  max_unknown_rounds: 8
  max_loops: 600

  entry:
    components:
      - enter_kairos_dungeon
    success_templates:
      - 连续战斗_卡伊洛斯地下城_巨人_战斗.png
    success_threshold: 0.85
    success_step_name: giants_entry_ready
    success_failure_reason: giants_entry_not_ready

  unknown_actions:
    - type: wait
      duration_ms: 1000

  states:
    - name: common_popup
      groups:
        - 弹窗
      threshold: 0.85
      priority: 100
      actions:
        - type: component
          name: dismiss_configured_popup

    - name: battle_running
      template: 连续战斗_卡伊洛斯地下城_战斗中.png
      threshold: 0.85
      priority: 10
      actions:
        - type: wait
          duration_ms: 3000
```

## 顶层字段

### `script.id`

脚本 ID。

- 可选
- 不写时默认使用文件名
- 建议与文件名一致，方便排查日志

### `script.template_groups`

本脚本主要使用的模板组。

示例：

```yaml
template_groups:
  - 连续战斗
  - 地图_竞技场
```

作用：

- 当状态里写裸模板名时，会优先去这些组里查找
- 一个脚本可以同时吃多个分组

### `script.common_groups`

通用模板组。

典型例子就是所有脚本都要引用的弹窗组：

```yaml
common_groups:
  - 弹窗
```

它和 `template_groups` 一起参与模板解析，但语义上更偏“公共依赖”。

### `script.template_folders`

额外模板目录。

如果你不想只依赖组，也可以显式增加目录：

```yaml
template_folders:
  - templates/icons
  - templates/icons/连续战斗
```

通常优先推荐使用 `template_groups` / `common_groups`，只有在确实需要跨目录引用时再用它。

### `script.loop_interval_ms`

循环中没有命中任何状态时，默认等待多久。

### `script.max_unknown_rounds`

连续多少轮没有命中任何状态后，脚本暂停。

### `script.max_loops`

脚本最多跑多少轮状态循环，超过后暂停。

### `script.initial_mode`

可选的初始模式。

适合大脚本按阶段收缩状态匹配范围，例如：

```yaml
initial_mode: battle_running
```

## 入口配置 `entry`

入口表示脚本开始后，先执行哪些固定导航动作，直到进入目标场景。

### `entry.components`

入口组件列表。

示例：

```yaml
entry:
  components:
    - return_main_island
    - enter_kairos_dungeon
```

它们来自当前的组件注册表，可通过下面命令查看：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list-components
```

### `entry.success_templates`

入口成功模板列表。

只要命中其中任意一个，就认为入口完成。

示例：

```yaml
success_templates:
  - 连续战斗_卡伊洛斯地下城_巨人_战斗.png
```

### `entry.success_template`

`success_templates` 的单值写法。

### `entry.success_groups`

如果入口成功可以由一个模板组整体判定，也可以写组。

### `entry.success_threshold`

入口成功模板的匹配阈值。

### `entry.success_step_name`

日志中的入口步骤名。

### `entry.success_failure_reason`

入口成功模板没有识别到时，抛出的暂停原因。

建议统一使用英文 `snake_case`，例如：

```yaml
success_failure_reason: kairos_entry_not_ready
```

## 状态配置 `states`

`states` 是脚本主体。

每一轮循环会：

1. 截当前画面一次图
2. 用这张图匹配所有候选状态
3. 选出最合适的状态
4. 执行这个状态绑定的动作

### 状态最小结构

```yaml
- name: repeat_again
  template: 连续战斗_再来一次.png
  threshold: 0.85
  priority: 80
  actions:
    - type: click_match
      delay_after_ms: 1000
```

### `name`

状态名，必填。

建议：

- 语义清晰
- 使用英文或稳定命名
- 不要写成 `step_01` 这种无意义名称

### `template`

单模板写法。

### `templates`

多模板写法，命中任意一个即可。

例如：

```yaml
templates:
  - 连续战斗_出售所选_确定.png
  - 连续战斗_出售所选_二次确定.png
```

### `groups`

整个组直接参与匹配。

例如把弹窗全部视为一个高优先级状态：

```yaml
groups:
  - 弹窗
```

### `threshold`

当前状态的匹配阈值。

### `priority`

当前状态的优先级，越大越优先。

通常建议：

- 通用弹窗：最高
- 结束状态：高
- 关键确认按钮：中高
- 战斗中等待：低

### `mode`

只在指定模式下参与匹配。

例如：

```yaml
mode: settle
```

配合动作里的 `set_mode` 使用。

### `actions`

命中状态后执行的动作列表，至少要有一个动作。

## 未知状态恢复 `unknown_actions`

如果这一轮没有任何状态命中，就执行 `unknown_actions`。

典型写法：

```yaml
unknown_actions:
  - type: log
    message: no state matched
  - type: key
    key: esc
    delay_after_ms: 300
  - type: wait
    duration_ms: 1000
```

如果连续多轮都没命中，会按 `max_unknown_rounds` 暂停。

## 模板引用规则

## 推荐写裸模板名

如果已经配置了模板组：

```yaml
template_groups:
  - 连续战斗
common_groups:
  - 弹窗
```

那么状态里直接写：

```yaml
template: 连续战斗_再来一次.png
```

就会自动去对应分组里找。

## 也可以写完整相对路径

例如：

```yaml
template: templates/icons/连续战斗/连续战斗_再来一次.png
```

## 组引用

组引用本质上等价于：

```yaml
groups:
  - 弹窗
```

也就是把这个组下所有模板都纳入当前状态候选。

## 歧义规则

如果一个裸模板名在多个组里都存在，解析器会报错。

这时建议：

1. 调整 `template_groups`
2. 或改用明确的相对路径
3. 或拆分模板命名

## 当前支持的动作

## `click_match`

点击当前命中的模板。

示例：

```yaml
- type: click_match
  delay_after_ms: 500
  note: click repeat again
```

可用参数：

- `use_random_region`
- `delay_after_ms`
- `note`

## `drag_match`

从当前命中模板的位置发起拖拽。

示例：

```yaml
- type: drag_match
  direction: up
  distance: 300
  duration_ms: 300
  steps: 12
  delay_after_ms: 500
```

## `drag_point`

从固定坐标拖拽。

示例：

```yaml
- type: drag_point
  x: 600
  y: 500
  direction: up
  distance: 260
```

## `wait`

等待。

示例：

```yaml
- type: wait
  duration_ms: 3000
```

## `key`

发送按键。

示例：

```yaml
- type: key
  key: esc
  duration_ms: 50
  delay_after_ms: 500
```

## `component`

调用一个可复用 Python 组件。

示例：

```yaml
- type: component
  name: dismiss_configured_popup
```

## `set_mode`

切换脚本当前模式。

示例：

```yaml
- type: set_mode
  mode: settle
```

清空模式：

```yaml
- type: set_mode
```

## `set_var`

写运行时变量。

示例：

```yaml
- type: set_var
  name: battle_count
  value: 3
```

## `log`

写日志。

```yaml
- type: log
  message: state matched
```

## `pause`

主动暂停脚本。

```yaml
- type: pause
  reason: need_manual_check
```

## `finish`

结束脚本。

```yaml
- type: finish
  result: success
```

## 推荐配置模式

## 模式一：弹窗作为全局最高优先级状态

```yaml
- name: common_popup
  groups:
    - 弹窗
  threshold: 0.85
  priority: 100
  actions:
    - type: component
      name: dismiss_configured_popup
```

## 模式二：战斗中状态只负责等待

```yaml
- name: battle_running
  template: 连续战斗_卡伊洛斯地下城_战斗中.png
  threshold: 0.85
  priority: 10
  actions:
    - type: wait
      duration_ms: 3000
```

## 模式三：结束模板直接结束脚本

```yaml
- name: finish_repeat_battle
  template: 连续战斗_结束连续战斗.png
  threshold: 0.85
  priority: 95
  actions:
    - type: finish
      result: success
```

## 模式四：使用多个分组

```yaml
template_groups:
  - 连续战斗
  - 地图_竞技场
common_groups:
  - 弹窗
```

## 当前示例

可以直接参考这个文件：

[state_scripts/giants_repeat_battle.yaml](/D:/work/monster-job32/state_scripts/giants_repeat_battle.yaml:1)

## 排错建议

## `--validate` 失败

先检查：

1. YAML 缩进是否正确
2. `states` / `actions` 是否是列表
3. 模板组名是否存在
4. 裸模板名是否有歧义
5. 组件名是否拼错

## 运行时经常暂停 `unknown_state`

通常表示：

1. 模板缺失
2. 模板阈值不合适
3. 当前画面不在你预期的状态集合里
4. 应该增加一个通用弹窗状态
5. 入口组件没有真正把画面带到目标场景

## 某状态总是抢优先级

先检查：

1. 它的 `priority` 是否过高
2. 它的模板是否过于宽泛
3. 是否应该拆成多个状态
4. 是否要加 `mode`

## 最佳实践

1. 入口只做导航，不做大段业务循环。
2. 通用弹窗放到 `common_groups`，并给最高优先级。
3. 结束状态优先级要高于普通业务状态。
4. 长时间战斗中的状态只做等待，不要频繁发输入。
5. 先让状态集覆盖完整，再微调阈值。
6. 裸模板名够用时就别写长路径。
7. 一个状态只表达一种清晰的画面意图。

## 兼容说明

- `game_bot/workflow/*` 和 `workflows/*.yaml` 属于旧方案，不再作为新脚本方向。
- `game_bot/scripted/scripts/*.py` 当前更多承担兼容层和组件来源的角色。
- 如果同名 YAML 已存在，运行器会优先选择 YAML 状态脚本。
