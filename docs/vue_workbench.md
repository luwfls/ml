# Vue 工作台开发启动

新版工作台是独立前端工程，使用 Vue 2、Element UI 和 Vite。旧的 `tools/workflow_editor.html` 已移除；日常开发使用 Vite 前端加 Python API 后端。

## 1. 启动 Python API 后端

Vite 开发服务器会把 `/api/*` 代理到 Python 工作台后端。默认代理目标是 `http://127.0.0.1:8765`，因此先启动后端：

```powershell
& "D:\work\monster-job32\venv\Scripts\python.exe" "D:\work\monster-job32\tools\window_workbench.py" --api-only --no-browser --port 8765
```

`--api-only` 会保持服务常驻，并打印后端地址与前端地址。这个后端仍复用 `game_bot.web.window_bridge` 中现有的窗口、截图、模板、状态流程 API。

## 2. 安装并启动前端

本机没有全局 yarn 时，可以使用 Node 自带的 Corepack：

```powershell
corepack yarn install
corepack yarn dev
```

如果已经启用了全局 yarn，也可以直接运行：

```powershell
yarn install
yarn dev
```

前端默认地址：

```text
http://127.0.0.1:5173
```

修改 `frontend/src/App.vue` 或 `frontend/src/styles.css` 后，Vite 会自动热加载。

## 自定义 API 代理目标

如需把 `/api` 代理到其他端口，启动前设置环境变量：

```powershell
$env:VITE_WORKBENCH_API_TARGET = "http://127.0.0.1:9000"
corepack yarn dev
```

## 构建

```powershell
corepack yarn build
```

构建产物输出到 `dist/workbench/`。
