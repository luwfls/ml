# The Internet：可复现的 State 与流程样例

目标是公开的自动化练习应用 [The Internet](https://github.com/saucelabs/the-internet)。本目录保存 **8 个 State、3 个流程、对应完整截图和裁剪模板**，使用项目原有 `Store`、`Recognizer`、`run_loop` 执行。不是合成截图或预先编写的命中结果。

本机无法连通公开 Heroku 站点，因此使用上游提交 `412661999056d1cc302a920f8ec1b177eaa8ae3d` 的两个页面在本地运行：原 ERB 页面渲染为静态 HTML，保留原有 checkbox 和添加/删除 JavaScript；布局缩减为所需 CSS 和 jQuery。没有运行完整 Sinatra 服务，也不代表验证了在线站点或安卓设备。上游文件、许可、来源 URL 和 SHA256 见 `site/upstream/`、`site/provenance.json`。测试无需账号、联网或业务数据。

## 流程

| 流程 | 初始页面 | State 编排 | 独立结果断言 |
| --- | --- | --- | --- |
| `checkbox-cycle` | 第一项未选、第二项已选 | `checkbox-01` 点击第一项 → `checkbox-11` 点击第二项 → `checkbox-10` 点击第一项 → `checkbox-00` 成功 | 两项均未选，恰好三次输入，顺序与 State 一致 |
| `add-element` | 没有 Delete 按钮 | `element-empty` 点击 Add Element → `element-added` 成功 | Delete 数量从 0 变为 1，恰好一次输入 |
| `remove-element` | 上一个流程添加的元素 | `element-delete` 点击 Delete → `element-cleared` 成功 | Delete 数量从 1 变为 0，恰好一次输入 |

删除成功 State 同时要求 Delete 识别 State 不命中，防止仅凭始终可见的 Add Element 按钮误报成功。三个流程按上表顺序执行，后两个流程共享同一个真实浏览器页面。

## 重放已保存配置

在仓库根目录，使用 Python 3.14 隔离环境（或项目现有兼容环境）：

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-platform.txt -r examples/the-internet/requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python examples/the-internet/run.py
```

Windows 将 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`。已有 Chromium 可传 `--chromium /path/to/chromium`，无需再下载浏览器。此命令会临时启动本地页面，**读取 Git 中已有 JSON 和模板**执行，退出时关闭浏览器和本地 HTTP 服务，不重新制作模板。

`evidence/` 保存每轮截图、识别/动作事件、坐标、结果和独立断言，以及网络/控制台/脚本异常；运行证据已忽略，不混入样例定义。任一流程未通过、动作顺序/次数错误、最终 DOM 状态不符、页面异常或 HTTP 错误都会非零退出。`verification.json` 记录交付时对已保存资产的实测摘要。

State 为图片识别，固定 **1280×800、DPR=1、light、en-US**，阈值 0.999、scale=1；点击使用识别框内保存的 `target_box` 中心。DOM 仅用于初始条件和独立结果检查，不用于引擎判断命中或执行动作。`BrowserDevice` 是样例专用的真实截图/坐标点击适配器；平台原有 ADB 运行器保持原样。

截图包含浏览器原生 checkbox，跨操作系统或 Chromium 版本可能不匹配；不要降低阈值或在回归时自动重录。确需在新环境制作模板时，显式运行 `run.py --record`，审查图片、JSON、`manifest.json` 和重放结果后再提交。当前交付在 Linux Chromium 验证，未验证 Mac/Windows 的像素一致性。

## 在工作台中查看和预览

将样例复制到新的运行数据目录，避免编辑 Git 中的基准；不要覆盖已有数据目录：

```bash
.venv/bin/python -c "from pathlib import Path; import shutil; p=Path('data/the-internet-demo'); p.mkdir(parents=True,exist_ok=False); [shutil.copytree(Path('examples/the-internet')/d,p/d) for d in ('states','flows','assets','captures')]"
.venv/bin/python -m automation --data data/the-internet-demo --no-adb --no-ocr
```

先按项目说明构建前端（`npm ci && npm run build`），打开工作台，即可查看 8 个 State、恢复原图/识别区和预览，流程页可查看 3 条配置。工作台设备执行入口仍面向安卓 ADB；执行本 Web 样例请用上面的 `run.py`，不把它当成可直接用于安卓屏幕的资产。

样例目录单独版本管理；根目录运行数据忽略规则未改变，也没有提交用户 `data/`。
