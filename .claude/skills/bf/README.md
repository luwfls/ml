# bf

把自然语言任务流程转换为 Monster Job 标准 workflow YAML / JSON。

## 示例请求

```text
使用 bf：
创建一个流程：先截图，识别 battle_settings，找到就点击识别中心，点完等 500ms 后回到截图；找不到等 1 秒重试。输出 YAML。
```

```text
使用 bf：
把下面流程保存成 workflows/collect_reward.yaml：截图 -> 识别奖励按钮 -> 找到点击 -> 等待 800ms -> 结束；找不到暂停。
```

## 模板图标感知

使用 bf 前先读取 `templates/icons/*`，把当前已有图标作为可直接引用的模板资源。当前图标：

- `templates/icons/cy.png`

如果目标能对应已有图标，优先写 `template: templates/icons/<filename>`；没有对应图标时不要编造文件名，使用 `TODO` 占位并提示需要补充模板图。

## 生成规范

- 生成规范流程，不要随意乱连线。
- 顶层 `start` 表示开始；正常结束必须有 `end` 节点，异常/找不到目标必须有 `pause` 节点。
- `template_match` 的 `found` / `not_found` 必须写在 `transitions` 中，不要用普通 `next` / `on_fail` 表示模板找没找到。
- 多模板匹配使用 `templates: [...]`，默认 OR 关系，任一模板命中即 `found`。
- 没有明确要求循环时，点击后应进入 `done`，不要默认回到截图。

## 运行校验

生成 YAML 后建议执行：

```powershell
.\venv\Scripts\python.exe main.py workflow-validate --workflow workflows/<name>.yaml
```
