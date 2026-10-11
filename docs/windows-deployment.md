## Windows 测试机部署

适用于 Windows 10/11 x64。OCR 集成在当前 Python 服务中，默认启用 RapidOCR + ONNX Runtime CPU，无需另开 OCR 服务。

### 首次准备

1. 安装标准版 [Python 3.14 x64](https://www.python.org/downloads/windows/)，勾选添加到 PATH。不要选择 32 位或 free-threaded 版本。
2. 下载 [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools)，将整个 `platform-tools` 文件夹解压到项目目录下（保留 DLL）。已有 ADB 也可使用 `--adb` 指定路径。
3. 下载本任务附带的 Windows 部署 ZIP，解压到可写目录，例如 `D:\auto-test`。部署包带已构建前端，无需 Node.js。若从 Git 拉取源码，首次构建需安装 [Node.js LTS](https://nodejs.org/en/download)，安装后重新打开终端。
4. 手机开启 USB 调试，连接测试机并在手机上授权；必要时安装设备厂商的 Windows USB 驱动。运行 `platform-tools\adb.exe devices -l`，设备应显示 `device`，而非 `unauthorized` 或 `offline`。

### 启动与使用

双击项目根目录 `start-windows.cmd`，或在 PowerShell 中执行：

```powershell
.\start-windows.cmd
```

首次会创建 `.venv`、安装锁定的 Python 依赖，需要联网。源码启动还会构建前端；后续启动复用已有环境。窗口显示后端启动成功后，浏览器打开 http://127.0.0.1:8765 。保持该窗口打开；关闭服务时按 Ctrl+C，等待活动任务停止并保存结果。第二次 Ctrl+C 会强制退出，可能中断结果保存。

在页面选择设备，截图或导入 PNG，配置图片/文字状态，预览匹配，再配置流程并运行。状态、模板和执行证据保存于项目 `data` 目录。

```powershell
# 使用现有 ADB，或者换端口
.\start-windows.cmd --adb "C:\Android\platform-tools\adb.exe" --port 8766
# 只准备环境，不启动服务
.\start-windows.cmd --setup-only
# 使用本地 OCR 模型配置（配置格式见 README）
.\start-windows.cmd --ocr-config ocr.local.json
# 临时关闭文字识别进行诊断
.\start-windows.cmd --no-ocr
# 重新安装锁定依赖并构建前端；此操作需要 Node.js 和网络
.\start-windows.cmd --refresh
```

参数中的相对路径以项目目录为基准。服务仅监听本机，启动器不安装 Windows 服务，也不设置开机自启。

### 常见问题

- Python 版本不匹配：安装标准 Python 3.14 x64；若 `.venv` 来自其他系统或旧 Python，先将其改名，再启动。不要删除 `data`。
- 找不到 ADB：确认 `platform-tools` 位于项目根目录，或使用 `--adb` 指定完整路径。
- 端口被占用：关闭已有实例，或者指定 `--port 8766`，同时使用对应浏览器地址。
- pip 下载失败：检查测试机网络及公司代理配置，然后重新执行启动命令；失败的安装不会标记为完成。
- 前端需要 Node.js：源码首次构建、前端源码变化或 `--refresh` 都需要 Node.js；部署 ZIP 的未修改前端可直接复用。

已在 Linux Python 3.14 x64 验证启动准备流程，并核对主要依赖可下载 Windows x64 wheel；尚未在 Windows 实机验证 CMD、USB 驱动及 OCR 推理。此包仍需在测试机完成首次设备验收。
