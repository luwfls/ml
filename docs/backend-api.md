# 已确认页面的后端接口

后端仍使用 `python -m automation` 启动，64 位 Python、RapidOCR 本地 CPU。接口只监听本机，JSON 请求/响应；失败返回 HTTP 400 和 `{ "error": "具体原因" }`，资源读取不存在返回 404。本次交付后端能力，已确认的 HTML 仍是交互原型；生产 Vue 页面的布局与新接口接线不包含在本次修改中。

## State、分组与流程

- `GET /api/states`、`GET /api/states/{id}`：配置列表/详情。
- `POST /api/states`：直接保存配置，省略 `id` 自动生成；更新传回原 ID。
- `POST /api/states/save`：一次保存模板裁剪与 State。请求 `{state, capture_id, box:[left,top,right,bottom]}`，box 是截图像素坐标；image 或 combined.image 的 asset 由后端生成。纯文字/不换模板时只传 `{state}`。失败时不保留新模板。
- `POST /api/states/copy`：`{id, name?, group?, new_id?}`，默认生成新 ID，复制图片资产，原 ID/引用不变。
- `POST /api/states/delete`：`{id}`，被条件或流程引用则拒绝。
- `POST /api/preview`：`{capture_id, state}`，只识别草稿，不保存或输入。State 新草稿可以省略 ID。
- `POST /api/execute`：`{serial,state_id}`，使用已保存 State 和新截图做一次识别及动作；执行前由页面提供显式入口。
- `GET /api/groups`、`POST /api/groups {action,name,new_name?}`：create/rename/copy/delete；非空组不允许删除，复制组生成新 State/资产 ID，组内条件重映射。
- `GET /api/flows`、`GET /api/flows/{id}`、`POST /api/flows`、`POST /api/flows/copy {id,new_id?,name?}`、`POST /api/flows/delete {id}`：流程配置 CRUD，保存/复制省略 ID 自动生成。被任务引用的流程不能删除。
- 原有截图导入、裁剪、设备截图及 `/api/flow` 兼容入口保留。

State priority 默认 `1.0`，最多两位小数，值越大越优先。默认 actions=[]，成功/失败断言不能配置输入动作。流程列表是候选 State 集合，不表示执行顺序；至少一个成功断言，完成次数按成功页面离开再进入计数。流程 `dry_run` 默认 false，必须传 JSON 布尔值。

### 组合识别

原有 `recognition.type=image/text` 数据继续可用。图片、文字同时启用时：

```json
{
  "name":"确认收货", "priority":1.25,
  "recognition":{
    "type":"combined", "operator":"or",
    "image":{"asset":"button.png","threshold":0.85,"scales":[1],"region":[0,0,1,1]},
    "text":{"texts":["确认收货","确定收货"],"mode":"contains","min_confidence":0.8,"region":[0,0.5,1,1]}
  },
  "actions":[{"type":"click_match","click_region":[0.2,0.6,0.8,0.8]}]
}
```

operator 为 and/or，文字候选之间始终 OR。两个组件同一帧识别并返回 `components.image/text`，每帧 OCR 共用一次结果。顶层 bbox 优先取命中图片，否则取文字；所选组件歧义时不自动点击。

所有 region/click_region 为 `[left,top,right,bottom]` 归一化屏幕区域。click_match 优先在独立 click_region 随机取整像素；没有独立区域则在命中的 bbox 内随机取点。每次执行重新取点。旧 `target_box` 是相对匹配框的历史字段，继续保留原中心点映射，前端新交互使用 click_region。

滑动：`{"type":"swipe","direction":"up","distance":0.6,"duration_ms":300}`，direction=up/down/left/right 表示手指移动方向。高级 `points:[x1,y1,x2,y2]` 仍支持，优先于方向。按键：`{"type":"key","key":"space"}` 或 back/home/enter/单个 A–Z，不区分大小写。

## 任务配置与执行

### 保存任务

`POST /api/tasks`：

```json
{"name":"收货全链路验证","flow_ids":["login","receive","check"]}
```

返回 `{id,name,flow_ids,flow_id,revision}`；flow_ids 顺序保留，允许重复引用，至少一项。省略 id 自动生成，更新传 id，revision 自动递增。legacy flow_id 请求仍接受，相当于一个流程；响应 flow_id 为首项，保留旧客户端兼容。`GET /api/tasks`、`GET /api/tasks/{id}` 读取。`POST /api/tasks/delete {id}` 删除配置，运行记录独立保留。

### 启动任务

`POST /api/tasks/start {"id":"任务ID","serials":["设备1","设备2"]}`。只使用已保存任务及其全部流程/State 的固定快照；运行中允许保存任务和流程，改动只影响下次。State、分组及模板仍在运行期间禁止修改，避免图片资源被覆盖。默认按各流程的 dry_run 策略自动识别/输入。

响应包含 `batch_id`、`task_id`、`results:[{serial,id}|{serial,error}]`。同一任务同一时刻最多一个活跃批次；设备 serial 必须唯一。离线、占用或启动失败按设备返回错误，其余设备继续启动。

每设备使用 Windows 兼容的 spawn 独立进程，完整执行 flow_ids 顺序；成功后进入下一流程。流程失败/异常/歧义终止当前设备，不影响其他设备。设备锁贯穿整个流程序列，旧单流程入口和截图、试执行入口也使用同一锁。任务不自动打开安卓应用。

### 查询与终止

- `GET /api/batches`、`GET /api/batches/{batch_id}`：批次配置、每设备 runs、汇总 status/live。单设备启动错误也保留在 results。
- `GET /api/runs`、`GET /api/runs/{id}`：运行状态、pid、serial、当前 flow_index（从 0 开始）、flow_id/name、rounds（所有流程累计截图轮数）、completed_flows、flow_results、最后 200 条 events 和最新 frame_url；详情 snapshot 固定本次配置。
- `POST /api/tasks/stop {batch_id}`：终止本次任务，先通知所有执行中设备，再等待退出。保留成功/失败结果与任务配置。再次启动从第一个流程开始。
- `POST /api/cancel {id}`：只终止该设备。两种终止均幂等；先协作取消，2 秒未退出则终止该设备子进程；确认退出后才释放占用锁。已发出的安卓输入不能撤回，真实设备终止需要现场验收。
- `POST /api/pause {id}`、`POST /api/resume {id}`：设备暂停/继续。暂停在检查点生效，不撤回已发送输入，不中断当前截图/OCR。

运行证据在 data/runs/{id}：config.json、summary.json、events.jsonl、result.json、frame-*.png。批次在 data/batches。服务正常关闭会终止并回收设备进程；重启读取历史，无结果的运行显示 interrupted，不自动续跑。服务应只启动一个实例访问同一数据目录。

## 流程调试

`POST /api/debug/start`：

```json
{"flow":{"name":"当前草稿","state_ids":["confirm","done"],"completion_count":1,"poll_ms":1000},"serials":["设备1","设备2"],"mode":"auto"}
```

可改传 flow_id 引用已保存流程。mode 默认 auto，支持 step。可在请求顶层传 dry_run=true/false 覆盖本次输入策略；不改已保存配置。响应与任务启动一样包含 batch_id 和每设备结果。

`POST /api/debug/control {id,action}`，action=next/auto/step/pause/resume/cancel。step 设备首先处于 waiting；next 完成一次新截图、识别和至多一个输入后再次等待；成功、失败或上限仍会结束。切到 auto 持续循环，切到 step 在当前轮结束后等待。每台设备独立控制，不产生任务配置。

原有 `/api/run` 单流程线程实现保留用于旧前端兼容，新多设备调试请使用 `/api/debug/start`。两者共享设备互斥与已有识别/循环实现。

## 验证范围

自动测试通过实际 HTTP 请求和独立 spawn 进程，ADB 使用可执行替身及固定截图；OCR 有本地真实引擎测试。已覆盖配置兼容、顺序推进、进程隔离、编辑快照、占用/离线、失败隔离、步进/暂停/模式切换、终止及重启历史。未声称已完成真实安卓/POS、多设备硬件或 Windows 主机验收。
