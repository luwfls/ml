# v0.5 工作台交互与 RapidOCR 验证记录

- Python：3.14.7，64 位；实际依赖版本见 requirements-tested.txt。
- `python -m unittest discover -s tests -v`：69 项测试全部通过，包含真实 RapidOCR CPU 推理、启动缓存与失败处理、真实子进程 Ctrl+C 延迟清理、分组与多流程持久化、故障回滚、引用保护、独立点击区和暂停恢复。
- `python -m compileall -q automation tests scripts`：通过。
- `npm run build`：通过，构建产物已包含在 dist/workbench。
- `python -m pip check`：通过。
- OCR：RapidOCR 3.9.2、ONNX Runtime 1.30.0；检测/识别使用 PP-OCRv6 small，分类使用随包 v2 mobile 模型。
- 禁止模型下载和 HTTP 请求时，真实引擎成功识别合成图中的中文按钮、提示及测试订单号；截图矩形经循环匹配生成预期 ADB tap 命令，ADB 进程使用替身，未发送到真实设备。
- 已完成独立代码审查，未发现阻断交付的问题。
- `node --test tests/frontend-*.test.mjs`：24 项通过，覆盖动作/未知字段往返、原始像素与点击区、裁剪取消资源隔离、快捷键关联操作、异步 State/流程保存与运行详情切换、分组重命名。
- 真实 Chromium 对生产构建执行 `tests/browser_smoke.py`：PNG 导入、框选、State 保存与预览、提示框关闭后的 F6、裁剪取消不覆盖原图、State 复制、独立点击区、新截图确认执行与删除、分组选择、流程复制、启动/暂停/继续/停止、刷新后的配置和运行证据查看均通过，无页面脚本错误。设备使用 `tests/browser_backend.py` 替身，未发送真实 ADB 输入。
- 协作暂停测试验证暂停期间无新动作/截图、暂停时间不计超时、恢复不重复既有输入，未执行动作恢复前重新截图。终止的歧义暂停记录和重启中断记录不可恢复。
- 代码审查发现的异步裁剪串写、迟到运行详情串显示及重命名分组抽屉残留已修复，并通过延迟响应回归与复核。
- `scripts/start.py --setup-only` 使用替身 ADB 完成真实 pip 依赖检查、npm ci 和前端构建；第二次准备仅检查 Python 依赖并复用前端，不启动服务。
- NumPy 2.5.3、OpenCV 5.0.0.93、ONNX Runtime 1.30.0 的 Windows x64 wheel 及 RapidOCR 3.9.2 通用 wheel 已成功下载验证。ANTLR 4.9.3 为纯 Python 源码依赖，正常 pip 安装构建；未在 Windows 实机执行完整安装。
- 启动器审查发现的 Ctrl+C 提前强杀后端问题已修正：第一次等待结果保存，第二次强制退出；POSIX 实际子进程清理测试通过，Windows 控制台仍需实机验证。
- 当前前端沿用既有 Vue 2 / Element UI 2，npm 安装报告 5 项漏洞（3 low、1 moderate、1 high）；未在本次启动脚本改动中升级框架。

验证使用固定合成图像和替身设备，未连接真实 Android/POS；未完成真实业务端到端验收、Windows/Mac 实机验证。浏览器自动化在 Linux Chromium 上完成。分组操作支持常规异常回滚，进程强制终止不提供跨文件事务保证；升级前保留 data 备份。

源码已集成到目标仓库；Git 分支、提交及合并请求以仓库记录为准。前端构建产物不提交到 Git，从源码首次启动需 Node.js。部署 ZIP 包含构建产物及缓存标记，未修改前端时无需 Node.js。
# Mac/Linux 一键入口验证（2026-10-06）

新增 `start.sh` 和 Mac 双击入口 `start-macos.command`，复用现有 Python 启动器及单端口页面/API 服务。`bash -n` 检查、参数帮助和缓存环境准备通过；8 项启动器测试通过。Linux 前台启动实测同时读取前端 HTML 与 `/api/states`，向启动进程组发送 Ctrl+C 后后端和启动器均正常退出。含空格目录、ADB 参数和失败退出码已验证；ADB 使用替身程序。Mac Finder 双击及真实设备尚未实测。

## 手动多设备任务验证（2026-10-11）

新增任务自动 ID、流程关联与删除引用保护；两台替身设备并发执行、离线/占用设备部分失败、设备独立运行失败、任务快照与重启记录回读均通过。前端覆盖多选设备、防重复启动、迟到响应隔离及启动确认（不依赖缓存的只识别配置）。Chromium 完成任务保存、双设备启动、单设备暂停与独立停止、刷新回读，无页面脚本错误。需求和代码质量复核通过。本次未修改图片/OCR 算法；真实多设备及 Windows/Mac 实机仍需验收。

## 2026-10-18 已确认交互的后端接口

基线 `833ca15`，按已确认 State、流程调试和 B 任务页实现后端，保留现有 Vue 页面和兼容接口。

- Python 3.14 64 位：`python -m unittest discover -s tests -p 'test_*.py'`，86 项全部通过。
- 前端既有行为：`node --test tests/frontend-*.test.mjs`，24 项全部通过；`npm run build` 通过，保留既有大包体积提示。
- `python -m compileall -q automation`、`pip check`、`git diff --check` 通过。
- 新运行测试通过实际 spawn 子进程和 HTTP：多流程顺序、固定快照、单设备/批次取消、真实子进程 PID、设备占用和失败隔离、步进/自动/暂停切换、重复步进、重启中断状态。
- 假 ADB 客户端延迟退出测试验证取消会回收该客户端再释放设备。未使用全局 adb kill-server 或按程序名杀进程。
- 本地真实 RapidOCR 测试仍通过；ADB 使用可执行替身和固定 PNG，未完成真实 Android/POS 或 Windows 主机验收。
- 新接口见 `docs/backend-api.md`；旧 `/api/run` 仍为兼容线程入口，新任务和多设备调试采用每设备独立进程。
