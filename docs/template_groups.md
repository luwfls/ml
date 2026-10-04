# 模板分组

## 目录约定

模板分组落在：

- `templates/icons/<group>/`

例如：

- `templates/icons/giants_repeat_battle/连续战斗_再来一次.png`
- `templates/icons/popups/礼包1.png`

未分组模板继续放在：

- `templates/icons/`

## 管理能力

当前模板管理支持：

1. 新建分组
2. 保存截图裁剪模板到指定分组
3. 把已有模板重命名并移动到指定分组
4. 按分组筛选模板列表

HTML 工作台模板页会通过本地 API 读取和维护这些分组。

## 脚本引用方式

`game_bot.scripted.runtime.ScriptRuntime.match_first()` 和 `expect_template()` 现在支持组引用。

格式：

```python
"group:<group_name>"
```

示例：

```python
probe = runtime.match_first(
    "group:popups",
    threshold=0.82,
    step_name="detect_popups",
)
```

也可以同时吃多个分组，再混合单个模板：

```python
probe = runtime.match_first(
    [
        "group:common_popups",
        "group:giants_repeat_battle_settle",
        "templates/icons/连续战斗/连续战斗_结束连续战斗.png",
    ],
    threshold=0.85,
    step_name="settle_or_finish",
)
```

推荐约定：

- `group:common_popups`
  - 所有脚本都引用
- `group:<script_name>`
  - 某个玩法自己的模板集合
- 必要时再额外补少量单模板路径

这样脚本组织会比较稳定：

```python
from game_bot.vision.templates import compose_template_references

templates = compose_template_references(
    "group:common_popups",
    "group:world_boss",
    [
        "templates/icons/地图_世界首领/地图_世界首领_结算.png",
    ],
)

probe = runtime.match_first(
    templates,
    threshold=0.85,
    step_name="world_boss_detect",
)
```

`compose_template_references(...)` 会自动：

- 合并多个组
- 展开组里的 PNG 模板
- 去重

## 说明

- 组引用会展开为该分组下所有 PNG 模板
- 多个组可以同时引用
- 如果分组不存在，或者分组下没有 PNG 模板，运行时会直接报错
- 这套能力主要给 `game_bot/scripted/*` 使用，不是给旧 `workflow` 继续扩展用的
