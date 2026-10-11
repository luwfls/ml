# 手动多设备任务 Implementation Plan

> **For agentic workers:** Use subagent-driven-development to implement the independent backend/frontend tasks and review the integrated result.

**Goal:** 保存关联一个已编排流程的任务，手动多选 ADB 设备，各设备独立执行并查看记录。

**Architecture:** 复用现有单设备运行器及设备锁，每次批量启动共享 batch_id，各设备拥有独立 run_id。任务保存在 data/tasks；运行配置保存任务名称/ID与批次，重启可回读。前端新增任务页和启动弹窗，允许其他设备已有运行时启动空闲设备。

**Tech Stack:** Python HTTP/JSON、ADB、Vue 2、Element UI；识别算法不变。

### Backend

- [x] 在 tests/test_tasks.py 写 API 红灯测试：任务 CRUD/自动ID与重启；多设备各自run、部分失败、占用/离线/非法重复设备、运行元数据回读、流程引用删除保护。
- [x] 执行 `.venv/bin/python -m unittest discover -s tests -p test_tasks.py -v`，记录功能缺失失败。
- [x] 修改 automation/state.py 和 automation/web.py：GET /api/tasks 返回数组；POST /api/tasks 接收 {id?,name,flow_id} 返回任务；POST /api/tasks/delete {id}；POST /api/tasks/start {id,serials} 返回 {batch_id,task_id,results:[{serial,id}|{serial,error}]}。任务ID为空时 uuid4.hex。启动时快照流程配置，不自动启动安卓应用；校验在线 device，重复serial拒绝，部分设备失败不影响其他设备。run配置/live/history都有task_id/task_name/batch_id。
- [x] 测试转绿，并跑全部 Python 测试。

### Frontend

- [x] 在 tests/frontend-tasks.test.mjs 写红灯测试：手动启动发送任务ID及去重设备集合、双击防重复、部分错误展示/刷新独立runs、活动设备不阻止启动其他设备。
- [x] 新增 TaskPanel.vue 及任务交互模块，App.vue 接入：任务名称、只读自动ID、已保存流程下拉、保存/删除；启动时弹窗多选在线/空闲 ADB 设备、显示设备状态，实际输入确认，按设备显示启动结果；任务关联runs可打开原RunPanel暂停/继续/停止和证据。
- [x] 运行 node --test tests/frontend-*.test.mjs 与 npm run build。

### Integration and Delivery

- [x] 需求复核后代码质量复核，修复阻塞问题。
- [x] Chromium 前台回归：任务页、保存、设备多选、启动两个替身设备、各自结果记录；测试进程在本回合结束前清理。
- [x] 更新使用说明，生成含前端构建部署包；提交 feature/manual-multi-device-tasks 并推送，合入 master，同步 test（已授权主分支统一交付）。
- [x] 回复本次触发评论，状态回到 in_review；识别组合另有待确认项，明确尚未实现。
