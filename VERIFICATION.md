# Windows 启动器与 RapidOCR 验证记录

- Python：3.14.7，64 位；实际依赖版本见 requirements-tested.txt。
- `python -m unittest discover -s tests -v`：49 项测试全部通过，包含真实 RapidOCR CPU 推理、启动缓存与失败处理、真实子进程 Ctrl+C 延迟清理。
- `python -m compileall -q automation tests scripts`：通过。
- `npm run build`：通过，构建产物已包含在 dist/workbench。
- `python -m pip check`：通过。
- OCR：RapidOCR 3.9.2、ONNX Runtime 1.30.0；检测/识别使用 PP-OCRv6 small，分类使用随包 v2 mobile 模型。
- 禁止模型下载和 HTTP 请求时，真实引擎成功识别合成图中的中文按钮、提示及测试订单号；截图矩形经循环匹配生成预期 ADB tap 命令，ADB 进程使用替身，未发送到真实设备。
- 已完成独立代码审查，未发现阻断交付的问题。
- `scripts/start.py --setup-only` 使用替身 ADB 完成真实 pip 依赖检查、npm ci 和前端构建；第二次准备仅检查 Python 依赖并复用前端，不启动服务。
- NumPy 2.5.3、OpenCV 5.0.0.93、ONNX Runtime 1.30.0 的 Windows x64 wheel 及 RapidOCR 3.9.2 通用 wheel 已成功下载验证。ANTLR 4.9.3 为纯 Python 源码依赖，正常 pip 安装构建；未在 Windows 实机执行完整安装。
- 启动器审查发现的 Ctrl+C 提前强杀后端问题已修正：第一次等待结果保存，第二次强制退出；POSIX 实际子进程清理测试通过，Windows 控制台仍需实机验证。
- 当前前端沿用既有 Vue 2 / Element UI 2，npm 安装报告 5 项漏洞（3 low、1 moderate、1 high）；未在本次启动脚本改动中升级框架。

验证使用固定合成图像和替身设备，未连接真实 Android/POS；未完成真实业务端到端验收、Windows 环境验证或浏览器自动化测试。

源码已集成到目标仓库；Git 分支、提交及合并请求以仓库记录为准。前端构建产物不提交到 Git，从源码首次启动需 Node.js。部署 ZIP 包含构建产物及缓存标记，未修改前端时无需 Node.js。
