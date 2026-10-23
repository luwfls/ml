# Mac 纯平台一键启动

无需安装 ADB，无需连接安卓设备，也不安装或加载 OCR。

在项目根目录执行：

```bash
bash ./start-platform.sh
```

或在 Finder 双击 `start-platform-macos.command`。首次需要先执行一次：

```bash
chmod +x start-platform-macos.command
```

启动后打开 http://127.0.0.1:8765 。前端构建和后端由同一个脚本准备，后端统一提供页面和 API，无需另开前端终端。终端保持打开，按 Ctrl+C 停止。

首次需要已安装标准 Python 3.14 64 位；源码未带前端构建时还需 Node.js LTS（含 npm）。脚本自动创建 `.venv`、安装 `requirements-platform.txt`、构建前端；第一次安装需要联网。部署包自带匹配的前端构建，可省去 Node.js。后续启动复用环境和构建，源码变更后自动重建。

可导入 PNG、框选图片、编辑保存 State、分组、流程和任务配置、查看历史记录、预览图片匹配。设备列表为空，设备截图和流程/任务执行不可用；文字识别预览不可用。配置保存在项目 `data`，重启后保留。

其他命令：

```bash
bash ./start-platform.sh --port 8766   # 更换端口，访问同端口页面
bash ./start-platform.sh --setup-only # 只准备环境，不启动服务
bash ./start-platform.sh --refresh    # 重装依赖、重建前端后启动
```

与原启动器共享 `.venv` 和 `data`。已有 Windows 虚拟环境不能在 Mac 复用，请先将该 `.venv` 改名再启动。切回设备模式仍用原来的 `bash ./start.sh`，会重新检查 ADB 和完整 OCR 依赖。

底层等价入口为 `bash ./start.sh --platform-only`。此模式固定禁用 OCR，不能与 `--ocr-config` 同用。程序不会自动安装系统 Python、Node 或 ADB。

已在 Linux 验证准备逻辑与 HTTP 链路；Mac 双击、Intel/Apple Silicon 依赖安装仍需实机验证。

## 识别和动作调试

| 启动命令 | 可用能力 |
| --- | --- |
| `bash ./start-platform.sh` | 无 ADB、无 OCR；导入原图后调试图片匹配 |
| `bash ./start.sh --no-adb` | 无 ADB，但安装完整依赖并加载 OCR；可调试导入截图的文字与图文组合 |
| `bash ./start.sh` | OCR + ADB；连接并选择已授权安卓设备后，可截图和执行保存的动作 |

切换模式前先 Ctrl+C 停止旧服务。文字预览需要 OCR 模型成功加载，设备模式还需已安装 Android platform-tools。既有 Mac 架构及依赖支持限制见工作台使用指南。

「识别预览」使用当前草稿和完整截图，不要求先保存 State 或填写名称，不会发送设备输入；含文字的 State 需要启用 OCR。图文组合还提供「仅图片预览」，即使 OCR 未启用也可调试图片部分，并明确标注未判断文字或完整图文关系，不修改原配置。

「执行动作 F5」使用已保存的 State 和设备新截图，须已启用 ADB、选择在线设备并先保存 State；含文字的配置还需 OCR。确认后才执行，未命中、条件不满足或歧义时不执行输入。调试结果显示在截图工作台。缺少条件时按钮会说明具体原因，只有请求处理中或执行锁定时才禁用相应操作。
