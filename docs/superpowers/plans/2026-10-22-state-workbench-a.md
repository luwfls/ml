# State 工作台 A 落地计划

目标：将用户已确认的附件 workbench-A-confirmed 落地到生产 Vue 前端，直接提交 master 并同步 test。

设计：复用现有截图、裁剪、State 保存、预览和组合识别 API。截图与编辑器左右同屏，窄屏上下排列；图片及文字可单独启用或组合，候选文案逐行输入，AND/OR 由后端处理。ROI 默认开启，使用识别区归一化坐标，关闭后全图搜索。State 的 workbench 元数据保留识别区与开关，旧 State 保留原范围。裁剪创建新资源，取消编辑不修改保存模板。

1. 在 tests/frontend-model.test.mjs 增加组合识别往返、ROI 开关/重新框选、无识别区校验、旧配置保留测试；先运行 node --test tests/frontend-model.test.mjs 确认失败。
2. 修改 frontend/src/model.js 转换组合识别与编辑元数据。修改 App.vue 将 StateEditor 放入截图工作台右栏，并将识别区变化接入裁剪与保存；CaptureCanvas.vue 去掉独立 ROI，统一蓝色识别区与橙色点击区，支持恢复框选；StateEditor.vue 改为普通表单卡片并接入图文开关及关系配置。
3. 更新 tests/browser_smoke.py，在真实 API 浏览器测试中检查同屏、ROI 默认、保存恢复、重新框选自动替换模板、候选文字/组合识别、关闭 ROI 全图及旧流程/任务回归。运行 Node 全套、Python 非 OCR 测试、npm run build、浏览器冒烟，附新布局截图。
4. 检查差异与文档，确认所有进程退出。提交并推送 HEAD:master，再将同一提交同步到 test；核对远端 SHA。评论交付提交号、验证结果与更新启动命令。

执行结果：步骤 1–3 完成；测试先红后绿，32 项 Node、82 项非 OCR Python、前端构建与 Chromium 冒烟通过。独立审查两项 Important 已修复并复核。步骤 4 按用户要求直接推送 master 并同步 test。
