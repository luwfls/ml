# 已确认交互的后端接口实施计划

目标：将已确认 State、流程调试、B 任务页操作落地为真实后端能力；本次不重新制作前端页面。

架构：沿用 Python 64 位标准库 HTTP 服务、文件持久化、ADB 和 RapidOCR。保留已有单流程接口；新增进程运行管理器，任务/调试每设备使用 spawn 独立进程。运行固定 State/流程/任务快照，设备锁直到子进程退出才释放。

1. 状态与配置（automation/state.py、vision.py、adb.py、tests/test_confirmed_state.py）：先补默认 ID、两位优先级、组合识别及动作测试；实现兼容的 image/text/combined schema、区域随机点击、方向滑动、空格/字母键。任务支持 flow_ids 有序列表与 legacy flow_id，删除保护检查每项引用。
2. 运行管理（automation/execution.py、runner.py、tests/test_execution.py）：先以真实子进程和假 ADB 可执行文件复现顺序执行、快照、多设备、步进和终止需求；实现持久化进度/事件/结果、任务批次、父进程设备互斥、暂停继续/步进切换与退出确认。
3. HTTP 接口（automation/web.py、tests/test_backend_api.py）：先验证多流程保存/启动/批次查询/终止和草稿调试接口缺失；接入管理器，允许运行中保存流程和任务用于下次执行；State/图片资源仍受运行保护。新增 State 一次保存裁剪接口，保留旧入口。
4. 文档与交付（docs/backend-api.md、README.md）：列出请求响应、兼容字段、错误与终止语义。运行 Python 全套测试、前端现有测试/构建，检查 Git diff；提交 feature 分支并自动合并推送 test，提供 MR 链接。硬件依赖使用替身验证，真实 Windows/POS 验收限制如实说明。

验证命令：`.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`；`node --test tests/frontend-*.test.mjs`；`npm run build`；`.venv/bin/python -m compileall -q automation`。
