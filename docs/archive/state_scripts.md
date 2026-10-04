# 状态驱动脚本

> [!WARNING]
> `state_script.py` / state-script YAML 已弃用。当前仓库仅保留 `template-loop` 作为 YAML 驱动执行方案。
> 下文内容仅供历史参考，不能再作为新流程实现方式。

现在新增脚本的主路径是 `D:\work\monster-job32\state_scripts\*.yaml`。

旧的 `game_bot/scripted/scripts/*.py` 保留为兼容层和组件来源，新的玩法脚本不再建议继续按那个方式扩写。现在的目标是：

1. 固定入口组件负责把画面送到目标场景。
2. 入口成功以“识别到指定模板”为准。
3. 主循环每轮只截图一次。
4. 同一张图上匹配当前脚本关心的状态模板。
5. 命中哪个状态，就执行它绑定的动作。
6. 新增脚本时只需要增加一个 YAML 文件。

## 放在哪里

脚本目录：

```text
D:\work\monster-job32\state_scripts
```

文件名就是脚本名，比如：

```text
D:\work\monster-job32\state_scripts\giants_repeat_battle.yaml
```

运行时直接写：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" giants_repeat_battle
```

## 写脚本前先看这几个辅助命令

列出当前可运行脚本：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list
```

列出可复用入口/动作组件：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list-components
```

列出模板分组：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --list-template-groups
```

校验某个 YAML 能不能被解析：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\run_scripted_flow.py" --validate giants_repeat_battle
```

## 最小结构

```yaml
script:
  id: example_script
  template_groups:
    - 连续战斗
  common_groups:
    - 弹窗
  loop_interval_ms: 1000
  max_unknown_rounds: 8
  max_loops: 300

  entry:
    components:
      - enter_kairos_dungeon
    success_templates:
      - 连续战斗_卡伊洛斯地下城_巨人_战斗.png
    success_threshold: 0.85
    success_step_name: entry_ready
    success_failure_reason: entry_not_ready

  unknown_actions:
    - type: wait
      duration_ms: 1000

  states:
    - name: popup
      groups:
        - 弹窗
      threshold: 0.85
      priority: 100
      actions:
        - type: component
          name: dismiss_configured_popup

    - name: finish
      template: 连续战斗_结束连续战斗.png
      threshold: 0.85
      priority: 95
      actions:
        - type: finish
          result: success

    - name: battle_running
      template: 连续战斗_卡伊洛斯地下城_战斗中.png
      threshold: 0.85
      priority: 10
      actions:
        - type: wait
          duration_ms: 3000
```

## 字段说明

顶层：

- `script.id`: 脚本 ID，不写时默认用文件名。
- `template_groups`: 本脚本主模板组。写裸文件名时，会优先在这些组里找。
- `common_groups`: 通用模板组，典型就是 `弹窗`。
- `template_folders`: 除组之外，额外参与查找的模板目录。
- `loop_interval_ms`: 未命中状态后的等待时间。
- `max_unknown_rounds`: 连续多少轮没命中就暂停。
- `max_loops`: 最多循环次数。
- `initial_mode`: 可选，给脚本一个初始模式。

入口：

- `entry.components`: 固定入口组件列表。
- `entry.success_templates`: 入口成功模板。
- `entry.success_threshold`: 入口成功阈值。
- `entry.success_step_name`: 入口识别步骤名。
- `entry.success_failure_reason`: 入口识别失败时的暂停原因。

状态：

- `name`: 状态名。
- `template`: 单个模板。
- `templates`: 多个模板，命中任意一个即可。
- `groups`: 直接引用整组模板，比如 `弹窗`。
- `threshold`: 当前状态识别阈值。
- `priority`: 优先级，越大越先处理。
- `mode`: 只在指定模式下参与匹配。
- `actions`: 命中后的动作列表。

未知状态恢复：

- `unknown_actions`: 当前轮没有任何状态命中时执行。

## 模板引用规则

推荐优先写裸模板名，不用手写完整路径：

```yaml
template_groups:
  - 连续战斗
common_groups:
  - 弹窗
```

这样在状态里可以直接写：

```yaml
template: 连续战斗_再来一次.png
```

或者直接吃整组：

```yaml
groups:
  - 弹窗
```

如果一个裸模板名在多个组里都存在，解析器会报歧义错误，这时再改成更明确的组名或相对路径。

## 当前支持的动作

- `click_match`: 点击当前命中的模板
- `drag_match`: 从当前命中的模板位置拖拽
- `drag_point`: 从固定坐标拖拽
- `wait`: 等待
- `key`: 按键
- `component`: 调一个 Python 组件
- `set_mode`: 设置或清除当前模式
- `set_var`: 写运行时变量
- `log`: 打日志
- `pause`: 主动暂停脚本
- `finish`: 结束脚本

## 当前可复用组件

可以通过 `--list-components` 查看当前清单。现阶段主要有：

- `dismiss_configured_popup`
- `ensure_giants_repeat_battle_running`
- `enter_continuous_battle`
- `enter_kairos_dungeon`
- `enter_main_island_battle`
- `return_main_island`
- `settle_repeat_battle_and_restart`
- `start_giant_battle`

建议把“导航到目标场景”这种固定入口留在组件里，把“当前画面识别后怎么反应”放到 YAML 的 `states` 里。

## 推荐写法

适合抽成组件的：

- 回主岛
- 进入某个地图
- 打开某个入口
- 带重试和恢复的复杂导航

适合写在状态里的：

- 看见某个按钮就点
- 看见结算确认就继续点
- 看见战斗中就等待
- 看见结束模板就收尾

## 现成示例

已经提供了一个新的状态驱动版本：

```text
D:\work\monster-job32\state_scripts\giants_repeat_battle.yaml
```

这个脚本展示了几件事：

- 一个固定入口组件：`enter_kairos_dungeon`
- 多模板组组合：`连续战斗 + 弹窗`
- 弹窗组的通用处理
- 结算、确认、再来一次、战斗中这些状态的循环处理
- 用 `finish` 动作结束脚本

## 新增脚本建议流程

1. 先确认要复用哪些模板组。
2. 先确认入口组件够不够，不够再补组件。
3. 复制一个现有 YAML。
4. 改 `entry` 和 `states`。
5. 跑 `--validate`。
6. 再用 `--dry-run` 或真实窗口验证。

## 兼容说明

- `game_bot/workflow/*` 和 `workflows/*.yaml` 已经是旧方案，不再作为新脚本方向。
- `game_bot/scripted/scripts/*.py` 现在主要作为兼容层和组件来源。
- 如果 `state_scripts` 下存在同名 YAML，运行器会优先使用 YAML 版本。
