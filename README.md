# 安卓 State 自动化工作台 · 首版

SCM-581 的安卓 State 自动化工作台首版，支持通过截图制作图片或文字 State，并使用 ADB 操控安卓设备。

沿用参考项目的 Vue 2 / Element UI / Vite 前端工程形态，以及 Python 本地 API、OpenCV 匹配与按画面循环的思路。只实现新核心，不包含原游戏流程、Windows 窗口控制、桌面截图、dm/COM、32 位环境、旧 workflow 图引擎和调度模块。

## 已实现

- ADB 枚举设备，明确 serial；二进制截图；点击、滑动、BACK/HOME/ENTER；命令超时和错误处理。
- 工作台设备截图/导入 PNG、原像素框选、裁剪图片、State 保存与编辑、图片匹配预览。
- 独立 JSON State，图片/文字二选一，空动作不输入；字段校验、配置完整保存、原子替换。
- OpenCV 多尺度匹配、ROI、模板缓存；重复独立图片候选标为歧义，点击时暂停。
- RapidOCR + ONNX Runtime 本地 CPU 引擎，统一输出文字、置信度、截图像素矩形；支持默认随包模型及 JSON 本地模型路径，推理串行保护；缺少模型/字典或推理错误明确失败。
- 文字 State 多文案 OR、exact/contains/fuzzy、Unicode 归一化、置信度过滤、同帧缓存，文字预览和运行共用引擎。
- 图片/文字 State 有限循环：优先级、required/excluded 同帧条件、成功页进入计数、真实匹配兜底、失败 State、重复动作抑制、超时、最大轮数、停止和只识别模式。
- 同设备互斥，运行期间禁止修改识别资源；独立 run_id、配置快照、逐帧图片、JSONL 事件和 result.json；证据写入失败返回 error。

## 启动

确保 PATH 中 `python` 指向 **64 位 Python**，ADB 已安装并能列出目标设备。后端入口会拒绝 32 位解释器。

```bash
python -c "import struct; assert struct.calcsize('P') * 8 == 64"
python -m venv .venv
```

Linux/macOS：

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m automation --adb adb --data data --port 8765
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m automation --adb "C:\Android\platform-tools\adb.exe" --data data --port 8765
```

首次使用 Git 源码时，先在项目根目录构建前端：

```bash
npm ci
npm run build
```

构建后启动后端，在本机浏览器打开 `http://127.0.0.1:8765`。构建产物 `dist/workbench` 不提交到 Git；之前 issue 附件源码包包含预构建产物。停止服务使用 Ctrl+C；正在运行的用例会收到取消请求，等待当前有超时的 ADB 调用和 OCR 推理退出。

开发前端或重新构建：

```bash
npm ci
npm run dev
# 本机浏览器打开 http://127.0.0.1:5173；后端仍需运行在 8765。
npm run build
```

后端仅绑定本机，首版不支持远程部署。依赖沿用参考前端的锁定版本；Vue 2 及其依赖已有维护/安全欠账，当前未做框架升级，也不建议直接发布到公网。

## 制作并运行第一条图片流程

1. 人工打开模拟器/真机的目标业务页面，点击“刷新设备”，选择状态为 device 的 serial。
2. 点击“设备截图”；拖动框选具备纹理且足以区分页面的区域。
3. 编辑 State ID（字母/数字/下划线/短横线）、名称与角色，点击“保存框选图片”，再保存 State。
4. 普通 State 默认 `actions=[]` 只识别。如需点击，明确填写 `[{"type":"click_match"}]`。首版每个 State 最多一个输入动作，必须位于动作列表首项，其后可接 wait；后续输入由新一轮截图驱动。
5. 对成功页制作 success State，动作保持空；业务失败页可制作 failure State。
6. 勾选流程需要的 State，设置轮数、超时、完成次数。先保持“只识别”开启检查结果；它会截屏并判断结果但不发送输入。准备好后关闭“只识别”运行。
7. 运行状态和最近 200 条事件显示在工作台；完整事件及证据在 `data/runs/<run-id>`。

识别资源位于 `data/assets`，State JSON 位于 `data/states`，流程配置位于 `data/flow.json`。条件、ROI、图片 scales/threshold 等进阶字段首版通过 JSON 配置；界面编辑已有 State 会保留这些字段。

success/failure 首版是纯断言状态，不执行动作。success 页面持续停留只计一次；离开全部 success 状态再进入才新增。若同时命中 success 和 failure，暂停处理歧义。

ADB 输入前读取活动逻辑显示，只有尺寸与截图一致时才发送输入；不猜测黑边、裁剪或副屏坐标。支持普通默认显示，尚未验证不同厂商 POS 的 dumpsys 格式及旋转变化。任何输入前都应保持设备方向固定。

## OCR 配置（已选择 RapidOCR）

已锁定 **rapidocr 3.9.2 + onnxruntime 1.30.0**，本次在 Python **3.14.7 x64 / Linux** 验证。OpenCV 统一使用 `opencv-python`，避免与 headless 包同时覆盖同一 `cv2` 模块。旧虚拟环境建议重建，再安装 requirements-tested.txt 复现本次完整依赖。

正常启动默认启用 OCR，使用锁定版本安装包自带的 `PP-OCRv6_det_small.onnx`、`ch_ppocr_mobile_v2.0_cls_mobile.onnx`、`PP-OCRv6_rec_small.onnx`。首次安装依赖需要联网；启动和识别明确传入本地模型路径，不自动下载模型。若安装包缺少模型会报错，可重装锁定版本或指定本地文件。只运行图片模式可添加 `--no-ocr`。

指定本地配置：复制 `ocr.local.example.json` 为 `ocr.local.json`，将三个模型放到配置文件旁的 models 目录，或修改为已有路径。路径相对 JSON 文件目录解析，也支持绝对路径；此示例不附带模型副本，默认模型已随依赖安装。

```json
{
  "det_model": "models/PP-OCRv6_det_small.onnx",
  "cls_model": "models/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
  "rec_model": "models/PP-OCRv6_rec_small.onnx"
}
```

```bash
.venv/bin/python -m automation --ocr-config ocr.local.json
```

Windows 使用 `.\.venv\Scripts\python.exe -m automation --ocr-config ocr.local.json`。没有内嵌 character 字典的自定义识别模型必须额外配置 `"rec_keys": "models/keys.txt"`，字典缺失会阻止启动，避免自动联网取字典。自定义模型应与本版 PP-OCRv6 small 检测/识别预处理、分类模型和字符顺序兼容；不支持仅换路径就任意切换模型架构。

文字 State 每行填写一个候选文案，选择 exact/contains/fuzzy，即可保存、预览和参与流程。ROI、min_confidence、similarity_threshold 可在 State JSON 设置；多个框命中时点击会暂停，请缩小 ROI。金额、单号优先 exact。工作台显示 OCR 是否启用。

真实引擎已在禁止网络请求的测试下识别合成中文 UI 图及测试订单号；尚未对供应链真实截图测准确率，也未验证 Windows/POS 环境。模型加载及单次 OCR 推理暂不可中断，取消需等当前推理返回；CPU 线程限制为 2/1，预览和运行共用推理锁。[RapidOCR 官方项目](https://github.com/RapidAI/RapidOCR)、[官方配置](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/config.yaml)。

## 验证

先构建前端，再跑测试（其中一个测试验证构建后的静态资源确实能被后端提供）：

```bash
npm ci
npm run build
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q automation
```

Windows 将 `.venv/bin/python` 换成 `.\.venv\Scripts\python.exe`。`requirements-tested.txt` 记录本次 Python 3.14.7 x64 环境中的依赖版本；未宣称其他 Python/OCR 组合已验证。

测试使用固定图像和替身设备，覆盖截图字节、图片坐标/歧义、文字匹配与缓存、循环计数/条件/停止/兜底、保存、API、独立结果证据、写盘失败、构建文件服务；新增真实 CPU OCR 离线识别、四边形坐标转换、本地配置、字典校验、并发保护、文字预览和执行。`tests/fixtures/ocr-ui.png` 是用 Noto Sans CJK 绘制的合成测试图，不是真实业务截图。本次未连接真机/POS，也未完成真实业务端到端验收或浏览器自动化测试。

## 首版边界与下一步

尚未实现有序业务步骤和 TestCase 独立断言模型、子流程及有预算的恢复、分组/删除界面、旧资产迁移工具、中文输入、多设备验收及 CI 报告。当前是有限的图片/文字循环闭环，不代表此前设计草案所有阶段已经完成。

输入可受设备页面刷新影响；仅适用于可控测试设备及已确认页面。同 State 动作抑制是连续命中保护，不提供业务幂等保证。超时/取消在动作边界生效，最坏要等待当前 ADB 调用超时（默认 10 秒）。每轮证据都保存到磁盘，长时间使用需自行归档或清理运行目录；首版尚未实现自动保留策略。

下一步：选一条供应链小程序及一条 POS 用例验证 → 逐步补有序流程和业务断言。
