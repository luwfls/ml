# State 制作与循环流程实施计划

> For agentic workers: use subagent-driven-development for bounded tasks and review. User approved frontend-page-plan.md on 2026-10-06; continue through implementation and delivery.

Goal: restore reference template/loop_template interactions with working persistence and ADB execution, without changing recognition algorithms.

Architecture: two Vue2 pages share the State drawer and capture canvas. Extend Python stdlib API and Store for groups/named flows; runner cooperatively pauses at safe boundaries while preserving its counters and action deduplication. Existing endpoints/data remain compatible.

Tech Stack: Vue2/ElementUI/Vite, Python3.14 x64, OpenCV and RapidOCR unchanged.

## Contract

- GET /api/groups -> [{name: string}]; State has group string, default empty. POST /api/groups -> {action: create|rename|copy|delete, name, new_name?}; response may be {ok:true}. Deleting a nonempty group is rejected; rename/copy updates/preserves State metadata and condition references respectively.
- POST /api/states/copy {id,new_id,name?,group?} -> State; POST /api/states/delete {id} -> {ok:true}. Referenced States cannot be deleted. Image copy duplicates asset; unknown fields preserved.
- GET /api/flows -> [flow]; POST /api/flows accepts {id,name,state_ids,max_rounds,timeout_seconds,poll_ms,completion_count,dry_run}; copy/delete endpoints accept {id,new_id,name?}/{id}. Legacy flow.json imported as default on first listing without overwriting it; existing /api/flow remains available.
- GET /api/runs -> run summaries newest first; detail /api/runs/<id> retains events, serial, flow_id, flow_name, success_count and latest frame_url when present across restart.
- POST /api/pause and /api/resume {id}; pause is cooperative, status pausing until acknowledged paused; resume only live user-paused runs. Cancel works while paused. Timeout excludes acknowledged pause duration. State/resources cannot mutate while a live run is paused. Reload retains run records but interrupted runs are marked interrupted and cannot resume.
- POST /api/preview-group {capture_id,state_ids} -> {matches:[matching result with state_id/eligible]}; same-frame conditions, no actions.
- POST /api/execute {serial,state_id} -> {match,...}; use saved State and fresh screenshot, validate conditions and ambiguity, require mutation/device exclusivity; frontend confirms input operation.
- click_match optional target_box: four finite relative-to-match-box coordinates (range -100..100), ordered rectangle. Execute its center mapped from match bbox, enforce screenshot bounds. Default match center unchanged. UI derives this only for image State from recognition/click rectangles; no chains of multiple input actions.

## Task 1 — Backend persistence and runtime

Files: automation/state.py, new automation/catalog.py if helpful, automation/web.py, automation/runner.py, automation/adb.py, tests/test_catalog.py, tests/test_workbench.py, runner/ADB tests.

- [x] Write tests first for group persistence/rename/copy/reference-safe delete, multi-flow restart and legacy migration, copied asset independence, pause-no-input/resume-no-repeat/cancel, relative click coordinates and invalid targets, group preview conditions, persisted run detail. Run `.venv/bin/python -m unittest discover -s tests -v`; observe new tests fail before implementation.
- [x] Implement contract with atomic JSON writes and guard lock; reject concurrent mutation. Do not silently delete referenced data or allow stale screenshot execution.
- [x] Run backend tests including existing 49 tests and fix regressions; do not edit frontend or commit independently.

## Task 2 — Frontend workbench

Files: frontend/src/App.vue, new frontend/src/components/*.vue and frontend/src/model.js as needed, tests/frontend-model.test.mjs. Existing API proxy and dependencies unchanged.

- [x] Write meaningful Node tests for model roundtrip, action form mapping and screenshot/click geometry before model implementation; run `node --test tests/frontend-model.test.mjs` and observe failure.
- [x] Two-page sidebar, shared device/API/OCR toolbar. State groups/cards/counts, drawer CRUD and image/text configuration; capture/import, crop rectangle, independent image click region, ROI and conditions, preview bbox/ambiguity; action fields replace raw JSON while preserving all supported saved fields.
- [x] Groups and flow CRUD invoke contract. Flow form includes explicit State IDs, group selection, cards opening shared drawer, JSON preview, dry-run, completion count/rounds/timeout/polling. Save-and-start uses returned saved flow. Runtime panel lists/reloads/polls run details with frames/events, pause/resume/cancel based on live statuses.
- [x] Button-first F1/F2/F3/F4/F5/F6 shortcuts only when input not focused; actual execute confirms and uses current saved State; no fake pause, browser-only persistence or placeholder buttons.
- [x] Run Node tests and npm build. Do not edit automation or commit independently.

## Task 3 — Integration/review/delivery

- [x] Read every change for contract and approved spec compliance. Obtain independent spec and quality reviews and fix findings.
- [x] Full Python/Node checks, production build, pip check, browser interaction checks using PNG and fake ADB; verify groups and multiple flows survive reload, preview/copy/delete/save/run/pause/resume/cancel and coordinates. Windows/Mac actual device validation remains a limitation.
- [x] Save approved spec, usage and verification documents; commit and push existing feature branch, fast-forward/safely merge and push test, update existing MR !1. Package source+dist with startup hash and exclude local deps/data/secrets. Attach package and exactly one final issue comment, move to in_review.
