# 模板状态驱动方案

> [!WARNING]
> `state_script.py` / state-script YAML 已弃用。当前仓库仅保留 `template-loop` 作为 YAML 驱动执行方案。
> 下文内容仅供历史参考，不能再作为新流程实现方式。

## 目标

把当前 `game_bot/scripted/scripts/*.py` 这种“顺序写死的流程脚本”收敛成一套：

1. 固定入口流程
2. 入口成功后进入模板状态循环
3. 每一轮只截一次图
4. 用同一张截图判断当前命中了哪个模板状态
5. 根据命中的状态执行对应动作
6. 命中结束模板时脚本结束

旧的 `game_bot/workflow/*` 和 `workflows/*.yaml` 只作为遗留兼容与参考，不再作为新脚本方案。

## 为什么要改

现在 `game_bot/scripted` 已经比旧 workflow 更接近可维护方案，但核心问题还在：

- 脚本仍然是“按作者预期顺序”往下走
- 同一个玩法里的异常分支、弹窗分支、结算分支，还是散落在 Python 代码里
- `match_first()` 是按一次调用截一次图，不适合做“当前画面到底在哪个状态”的统一判断
- 同一玩法里很多动作本质上是“看到某个模板就做某件事”，不需要写成长流程

更适合这类游戏自动化的，不是通用流程图，而是“模板识别 + 状态处理器”。

## 总体思路

### 1. 固定入口只负责把画面送进目标场景

入口流程仍然允许保留为 Python 组件，因为它往往更像“导航”：

- 回主岛
- 进入某地图
- 点到某玩法入口

但入口流程的完成判定，不再是“最后一步执行完了”，而是：

- 识别到入口成功模板，才算真正进入成功

例如：

- 进入连续战斗页面，识别到 `连续战斗_卡伊洛斯地下城.png`
- 进入世界首领布阵页，识别到 `地图_世界首领_战斗_自动布置.png`

### 2. 入口成功后切到状态循环

脚本主体不再写成：

- 先点 A
- 再点 B
- 再等 C
- 再点 D

而是写成：

- 我关心哪些模板状态
- 这些模板各自命中后该做什么
- 哪个模板是结束态

每轮循环：

1. 截一张当前窗口图
2. 用这张图匹配本脚本关心的一组模板
3. 选出当前最可信的状态
4. 执行该状态绑定的动作
5. 回到下一轮继续判断

## 建议的分层

尽量沿用现有 `game_bot/scripted`，不要再起一套平行大框架。

### 保留

- `game_bot/scripted/runtime.py`
  - 继续做底层运行时门面
- `game_bot/core/input.py`
  - 继续做 dm 输入
- `game_bot/vision/template.py`
  - 继续做 OpenCV 模板匹配
- `templates/*.png + .json`
  - 继续作为模板与点击区域元数据

### 新增

- `game_bot/scripted/state_models.py`
  - 状态脚本、状态节点、动作定义
- `game_bot/scripted/state_detector.py`
  - 单帧截图上的批量模板匹配
- `game_bot/scripted/state_actions.py`
  - click / drag / key / wait / scroll / component 等动作执行器
- `game_bot/scripted/state_engine.py`
  - 入口执行、循环检测、结束判定、超时与恢复
- `game_bot/scripted/state_scripts/`
  - 每个玩法的状态脚本定义

## 核心改动点

### 一次循环只截图一次

这是这次方案里最重要的点。

当前 `ScriptRuntime.match_first()` 的模式是：

- 截图
- 匹配一组模板
- 返回结果

如果脚本一口气判断多个模板，就会：

- 多次截图
- 不同模板基于不同时间点判断
- 容易出现上一张图和下一张图状态不一致

新的状态驱动里，一轮循环应该是：

```text
capture once
-> match template A on frame
-> match template B on frame
-> match template C on frame
-> choose best state
-> run action
```

所以建议新增“基于指定截图路径做批量匹配”的能力，而不是每个模板判断都重新抓图。

## 状态脚本的数据结构

建议用“Python 定义 + 少量 YAML 配置”混合方式。

- 入口流程、复杂组件调用：Python
- 模板列表、阈值、优先级、动作参数：数据化定义

不要重新回到旧 workflow 那种通用流程图编排。

### 结构示意

```python
TemplateStateScript(
    id="giants_repeat_battle_v2",
    entry=EntryFlow(
        component="enter_kairos_dungeon",
        success_templates=[
            "templates/icons/连续战斗/连续战斗_卡伊洛斯地下城.png",
        ],
        success_threshold=0.86,
    ),
    finish_templates=[
        "templates/icons/连续战斗/连续战斗_结束连续战斗.png",
    ],
    states=[
        TemplateState(
            name="repeat_again",
            templates=["templates/icons/连续战斗/连续战斗_再来一次.png"],
            threshold=0.88,
            priority=100,
            actions=[
                {"type": "click_match", "delay_after_ms": 1000},
            ],
        ),
        TemplateState(
            name="sell_selected",
            templates=["templates/icons/连续战斗/连续战斗_出售所选.png"],
            threshold=0.88,
            priority=90,
            actions=[
                {"type": "click_match", "delay_after_ms": 500},
            ],
        ),
        TemplateState(
            name="in_battle",
            templates=["templates/icons/连续战斗/连续战斗_卡伊洛斯地下城_战斗中.png"],
            threshold=0.84,
            priority=20,
            actions=[
                {"type": "wait", "duration_ms": 3000},
            ],
        ),
    ],
)
```

## 状态选择规则

同一帧里可能会有多个模板都能匹配上，所以必须定规则。

建议按下面顺序选中状态：

1. `priority` 高的优先
2. 同优先级时，`score` 高的优先
3. 再相同时，优先延续上一轮已经命中的状态
4. 再相同时，按定义顺序取第一个

这样能避免：

- 弹窗和主界面按钮同时命中时乱点
- 大模板和小模板重叠时误判
- 状态在两种模板之间来回抖动

## 动作系统

你提的“模板能力支持点击、拖拽、输入键盘等封装”，建议不要塞进模板匹配代码里，而是做成统一动作执行器。

### 第一批内置动作

- `click_match`
  - 点击当前命中模板
- `double_click_match`
- `drag_match`
  - 从模板点击区域出发拖拽
- `drag_point`
  - 从固定点拖拽
- `key`
  - 发送键盘
- `scroll`
- `wait`
- `component`
  - 调已有 Python 组件
- `finish`
  - 标记脚本结束
- `pause`
  - 进入人工接管
- `set_var`
  - 写上下文变量

### 第二批建议动作

- `click_region`
  - 点击模板 sidecar JSON 里命名区域
- `drag_region`
  - 从模板 sidecar JSON 里命名区域拖拽
- `retry_entry`
  - 从异常状态重新执行入口恢复
- `sequence`
  - 组合动作
- `if_var`
  - 简单条件动作

## 模板 sidecar JSON 的职责

模板 `.json` 建议只放“模板自身的交互几何信息”，不要把整段玩法逻辑写进去。

适合放进去的内容：

- `click_region`
- `click_regions`
- `coordinate_space`
- 后续可扩展：
  - `anchors`
  - `named_regions`
  - `default_drag_start`

不建议放进去的内容：

- 整个脚本流程
- 业务分支
- 某模板之后要跳到哪个模板

逻辑归脚本，几何归模板。

## 入口、全局、结束、异常四类状态

建议每个脚本把模板分成四类，而不是全混在一起。

### 1. entry

固定入口流程的成功判定模板。

### 2. global

任何时候都可能出现，而且优先级最高：

- 礼包弹窗
- 购买弹窗
- 网络异常提示
- 返回确认框

这部分其实就是把现在 `components/popups.py` 升级为全局状态集。

### 3. active

脚本真正的业务状态：

- 再来一次
- 出售所选
- 选择地区
- 战斗中
- 开始战斗

### 4. finish

命中后直接结束脚本：

- 结束连续战斗
- 次数耗尽
- 达到脚本目标

## 推荐引入 mode，而不是纯平铺

完全平铺地拿一个大模板列表去匹配，后期会越来越乱。

建议脚本支持轻量 mode，例如：

- `entry`
- `battle_prepare`
- `battle_running`
- `battle_settle`

每轮真正参与匹配的是：

- `global states`
- `finish states`
- `current mode states`

这样还能减少模板数量，提高判定稳定性。

这个 mode 不是旧 workflow 的流程图，只是“当前应该关注哪一组模板”。

## 运行循环建议

```text
prepare window
-> run entry flow
-> wait until entry success template appears
-> loop:
     capture current frame once
     detect global / finish / current-mode states
     if finish:
         end
     if matched state:
         execute bound actions
         update mode / vars / cooldown
         continue
     if no state matched:
         run unknown-state recovery
         if recovery failed too many times:
             pause
```

## unknown state 处理

这个很关键，不然状态驱动会比顺序脚本更容易卡死。

建议：

- 连续 `N` 轮无模板命中，先尝试全局恢复动作
  - `esc`
  - 等待
  - 重试截图
- 仍然失败则抛 `ScriptPause("unknown_state")`
- 把最后一张截图和各模板 score 落盘

这样后续补模板会非常快。

## 迁移建议

不要一口气全重写。按下面顺序迁移最稳。

### 第一步

先把 `ScriptRuntime` 拆出“单帧批量匹配”能力。

例如新增：

- `capture_frame(step_name) -> CaptureResult`
- `match_templates_on_frame(frame, candidates) -> list[StateMatch]`

### 第二步

先选一个最规则的玩法试点，推荐：

- `giants_repeat_battle`

因为它的主体非常适合状态驱动：

- 战斗中
- 再来一次
- 出售所选
- 二次确认
- 无出售项
- 结束连续战斗

### 第三步

把 `components/popups.py` 升级成全局状态集。

### 第四步

再迁移：

- `judgment_dungeon`
- `npc_arena`
- `world_boss`

其中：

- 导航和进入入口仍保留为 component
- 真正反复执行的场景切成模板状态循环

## 对现有目录的具体建议

### 保留不动

- `game_bot/scripted/components/`
- `game_bot/core/input.py`
- `game_bot/vision/template.py`
- `templates/*.json`

### 优先改造

- `game_bot/scripted/runtime.py`
  - 支持单帧批量识别
  - 支持动作执行统一封装

### 新入口

可以新增类似：

- `run_template_state_script(name, hwnd, ...)`

然后让 `runner.py` 里的注册表逐步切换到新入口。

## 一句话定性

旧方案是：

- 作者预先写好“应该怎么走”

新方案应该是：

- 脚本每轮先判断“现在画面处于什么模板状态”，再决定“下一步做什么”

这会更像一个会看画面做反应的自动机，而不是一个按剧本背台词的流程。

## 我建议的落地顺序

1. 明确旧 `workflow` 为 deprecated，只留兼容
2. 在 `game_bot/scripted` 内新增模板状态引擎
3. 先迁移 `giants_repeat_battle`
4. 动作系统先做 `click / drag / key / wait / component / finish`
5. 稳定后再把更多玩法切过去

如果你认这个方向，下一步最值当的是我直接把 `giants_repeat_battle` 先改成第一版模板状态驱动骨架。
