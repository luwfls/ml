# v0.2 RapidOCR 接入验证记录

- Python：3.14.7，64 位；实际依赖版本见 requirements-tested.txt。
- `python -m unittest discover -s tests -v`：41 项测试全部通过，包含真实 RapidOCR CPU 推理。
- `python -m compileall -q automation tests`：通过。
- `npm run build`：通过，构建产物已包含在 dist/workbench。
- `python -m pip check`：通过。
- OCR：RapidOCR 3.9.2、ONNX Runtime 1.30.0；检测/识别使用 PP-OCRv6 small，分类使用随包 v2 mobile 模型。
- 禁止模型下载和 HTTP 请求时，真实引擎成功识别合成图中的中文按钮、提示及测试订单号；截图矩形经循环匹配生成预期 ADB tap 命令，ADB 进程使用替身，未发送到真实设备。
- 已完成独立代码审查，未发现阻断交付的问题。

验证使用固定合成图像和替身设备，未连接真实 Android/POS；未完成真实业务端到端验收、Windows 环境验证或浏览器自动化测试。

源码已从独立交付包集成到目标仓库；Git 分支、提交及合并请求以仓库记录为准。前端构建产物不提交到 Git，测试前需执行 npm ci 和 npm run build。
