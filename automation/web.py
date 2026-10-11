from collections import deque
import base64
import json
import mimetypes
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import cv2
import numpy as np

from .adb import AdbDevice, list_devices
from .runner import RunControl, run_loop, validate_flow
from .state import identifier, validate_state
from .vision import Recognizer


def create_server(store, port=8765, adb='adb', ocr=None):
    guard = threading.RLock()
    device_locks, runs = {}, {}
    frontend = Path(__file__).resolve().parents[1] / 'dist' / 'workbench'

    def save_image(path, image):
        if not cv2.imwrite(str(path), image):
            raise OSError('截图/图片写入失败，请检查数据目录空间和权限')

    def lock_for(serial):
        with guard:
            return device_locks.setdefault(serial, threading.Lock())

    def mutation_allowed():
        if any(run.get('live', False) for run in runs.values()):
            raise ValueError('运行期间请停止流程后再修改 State 或资源')

    def capture_path(value):
        return store.captures / (identifier(value) + '.png')

    def start_run(body):
        serial = body.get('serial', '')
        device = AdbDevice(serial, executable=adb)
        serial = device.serial
        with guard:
            states = store.load_all()
            flow = body.get('flow')
            if flow is None:
                flow = next((f for f in store.list_flows() if f['id'] == body.get('flow_id')), None)
            if not isinstance(flow, dict): raise ValueError('请选择有效流程')
            validate_flow(flow, states)
            known = {s['id']: s for s in states}
            referenced, pending = set(), list(flow['state_ids'])
            while pending:
                state_id = pending.pop()
                if state_id in referenced:
                    continue
                referenced.add(state_id)
                condition = known[state_id]['conditions']
                pending.extend(condition['required_states'] + condition['excluded_states'])
            if ocr is None and any(known[s]['recognition']['type'] == 'text' for s in referenced):
                raise ValueError('OCR 未配置，请使用 RapidOCR 启动工作台后运行文字 State')
            lock = lock_for(serial)
            if not lock.acquire(blocking=False):
                raise ValueError('该设备正在截图或执行流程')
            run_id = uuid4().hex
            cancel = threading.Event()
            directory = store.runs / run_id
            try:
                directory.mkdir()
                (directory / 'config.json').write_text(json.dumps({'serial': serial, 'states': states, 'flow': flow}, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception:
                lock.release()
                raise
            run = {'id': run_id, 'status': 'running', 'live': True, 'events': [], 'cancel': cancel, 'serial': serial, 'flow_id': flow.get('id'), 'flow_name': flow.get('name', ''), 'success_count': 0}
            run['control'] = RunControl(cancel, lambda status: run.update(status=status, reason='user_paused' if status == 'paused' else ''))
            runs[run_id] = run

        def target():
            try:
                with (directory / 'events.jsonl').open('w', encoding='utf-8') as log:
                    def emit(event):
                        log.write(json.dumps(event, ensure_ascii=False) + '\n')
                        log.flush()
                        with guard:
                            run['events'].append(event)
                            run['events'] = run['events'][-200:]
                            if event['type'] == 'success': run['success_count'] = event['count']
                            if event['type'] == 'frame': run['frame_url'] = f"/runs/{run_id}/frame-{event['index']:04d}.png"
                            if event['type'] in {'success', 'frame'}:
                                store.write_json(directory / 'summary.json', {key: run[key] for key in ['serial', 'flow_id', 'flow_name', 'success_count', 'frame_url'] if key in run})

                    class RecordingDevice:
                        count = 0

                        def capture(self):
                            image = device.capture()
                            self.count += 1
                            save_image(directory / f'frame-{self.count:04d}.png', image)
                            emit({'type': 'frame', 'index': self.count})
                            return image

                        def execute(self, action, match, frame):
                            device.execute(action, match, frame)

                    result = run_loop(states, flow, RecordingDevice(), Recognizer(store, ocr), cancel=cancel, emit=emit, control=run['control'])
            except Exception as error:
                result = {'status': 'error', 'reason': str(error)}
            try:
                (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception as error:
                result = {'status': 'error', 'reason': f'运行结果写入失败: {error}'}
            finally:
                with guard:
                    run.update(result, live=False)
                lock.release()

        thread = threading.Thread(target=target, name=f'run-{run_id}')
        run['thread'] = thread
        try:
            thread.start()
        except Exception:
            with guard:
                runs.pop(run_id, None)
            lock.release()
            raise
        return {'id': run_id}

    def run_detail(run_id, include_events=True):
        if run_id in runs:
            return {k: v for k, v in runs[run_id].items() if k not in {'cancel', 'thread', 'control'} and (include_events or k != 'events')}
        directory = store.runs / identifier(run_id)
        config = json.loads((directory / 'config.json').read_text(encoding='utf-8'))
        result_file = directory / 'result.json'
        result = json.loads(result_file.read_text(encoding='utf-8')) if result_file.exists() else {'status': 'interrupted', 'reason': 'server_restarted'}
        events_file = directory / 'events.jsonl'
        events = deque(maxlen=200)
        if include_events and events_file.exists():
            with events_file.open(encoding='utf-8') as log:
                for line in log:
                    try: events.append(json.loads(line))
                    except json.JSONDecodeError: pass
        summary_file = directory / 'summary.json'
        summary = json.loads(summary_file.read_text(encoding='utf-8')) if summary_file.exists() else {}
        detail = {'id': run_id, 'live': False, 'serial': config['serial'], 'flow_id': config['flow'].get('id'), 'flow_name': config['flow'].get('name', ''), 'success_count': 0, **summary, **result}
        if include_events: detail['events'] = list(events)
        if 'frame_url' not in detail:
            frames = sorted(directory.glob('frame-*.png'))
            if frames: detail['frame_url'] = f'/runs/{run_id}/{frames[-1].name}'
        if include_events and 'success_count' not in result and 'success_count' not in summary:
            detail['success_count'] = max((e['count'] for e in events if e.get('type') == 'success'), default=0)
        return detail

    def preview_states(image, state_ids):
        known = {state['id']: state for state in store.load_all()}
        if not isinstance(state_ids, list) or any(state_id not in known for state_id in state_ids):
            raise ValueError('请选择存在的 State')
        matcher = Recognizer(store, ocr)
        matcher.begin(image)
        matches = []
        for state_id in state_ids:
            state = known[state_id]
            match = matcher.match(image, state)
            conditions = state['conditions']
            refs = conditions['required_states'] + conditions['excluded_states']
            if any(ref not in known for ref in refs): raise ValueError('条件引用不存在')
            eligible = match['found'] and all(matcher.match(image, known[ref])['found'] for ref in conditions['required_states'])
            eligible = eligible and not any(matcher.match(image, known[ref])['found'] for ref in conditions['excluded_states'])
            matches.append({**match, 'state_id': state_id, 'eligible': eligible})
        return matches

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def reply(self, body, status=200):
            raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path == '/api/health':
                    return self.reply({'python_bits': struct.calcsize('P') * 8, 'ocr': 'ready' if ocr is not None else 'disabled'})
                if path == '/api/devices':
                    return self.reply(list_devices(adb))
                if path == '/api/states':
                    with guard:
                        return self.reply(store.load_all())
                if path == '/api/groups':
                    with guard: return self.reply(store.list_groups())
                if path == '/api/flows':
                    with guard: return self.reply(store.list_flows())
                if path == '/api/runs':
                    with guard:
                        ids = {p.name for p in store.runs.iterdir() if p.is_dir() and (p / 'config.json').exists()} | set(runs)
                        ordered = sorted(ids, key=lambda i: (store.runs / i / 'config.json').stat().st_mtime, reverse=True)
                        return self.reply([{k: v for k, v in run_detail(i, include_events=False).items() if k != 'events'} for i in ordered])
                if path == '/api/flow':
                    file = store.root / 'flow.json'
                    return self.reply(json.loads(file.read_text(encoding='utf-8')) if file.exists() else None)
                if path.startswith('/api/runs/'):
                    run_id = identifier(path.split('/')[-1])
                    with guard: return self.reply(run_detail(run_id))
                if path.startswith('/runs/'):
                    _, run_id, filename = path.strip('/').split('/')
                    identifier(run_id)
                    identifier(Path(filename).stem)
                    if not filename.endswith('.png') or filename != Path(filename).name: raise ValueError('无效图片')
                    file = store.runs / run_id / filename
                elif path.startswith('/captures/') or (path.startswith('/assets/') and path.endswith('.png')):
                    group, filename = path.strip('/').split('/')
                    if not filename.endswith('.png'):
                        raise ValueError('仅支持 PNG')
                    identifier(filename[:-4])
                    file = getattr(store, group) / filename
                else:
                    file = (frontend / (path.strip('/') or 'index.html')).resolve()
                    if not file.is_relative_to(frontend.resolve()):
                        raise ValueError('无效文件路径')
                raw = file.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except FileNotFoundError:
                self.reply({'error': '资源不存在；页面需先 npm run build，或使用前端开发服务'}, 404)
            except Exception as error:
                self.reply({'error': str(error)}, 400)

        def do_POST(self):
            try:
                origin = self.headers.get('Origin')
                if origin and urlparse(origin).hostname not in {'localhost', '127.0.0.1'}:
                    raise ValueError('仅允许本机工作台请求')
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 12_000_000:
                    raise ValueError('请求体为空或过大')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError('请求必须为 JSON 对象')
                path = urlparse(self.path).path
                if path == '/api/import':
                    raw = base64.b64decode(body.get('png', ''), validate=True)
                    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise ValueError('导入文件必须是 PNG')
                    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                    if image is None:
                        raise ValueError('无法解码 PNG')
                    capture_id = uuid4().hex
                    save_image(capture_path(capture_id), image)
                    return self.reply({'id': capture_id, 'url': f'/captures/{capture_id}.png', 'width': image.shape[1], 'height': image.shape[0]})
                if path == '/api/capture':
                    device = AdbDevice(body.get('serial', ''), executable=adb)
                    lock = lock_for(device.serial)
                    if not lock.acquire(blocking=False):
                        raise ValueError('设备正在执行流程')
                    try:
                        image = device.capture()
                        capture_id = uuid4().hex
                        save_image(capture_path(capture_id), image)
                        return self.reply({'id': capture_id, 'url': f'/captures/{capture_id}.png', 'width': image.shape[1], 'height': image.shape[0]})
                    finally:
                        lock.release()
                if path in {'/api/groups', '/api/states/copy', '/api/states/delete', '/api/flows', '/api/flows/copy', '/api/flows/delete'}:
                    with guard:
                        mutation_allowed()
                        if path == '/api/groups': result = store.update_group(body.get('action'), body.get('name'), body.get('new_name'))
                        elif path == '/api/states/copy': result = store.copy_state(body['id'], body['new_id'], body.get('name'), body.get('group'))
                        elif path == '/api/states/delete': result = store.delete_state(body['id'])
                        elif path == '/api/flows': result = store.save_flow(body)
                        elif path == '/api/flows/copy': result = store.copy_flow(body['id'], body['new_id'], body.get('name'))
                        else: result = store.delete_flow(body['id'])
                        return self.reply(result)
                if path == '/api/preview-group':
                    with guard:
                        image = cv2.imread(str(capture_path(body['capture_id'])))
                        if image is None: raise ValueError('截图不存在')
                        return self.reply({'matches': preview_states(image, body['state_ids'])})
                if path == '/api/execute':
                    with guard:
                        mutation_allowed()
                        device = AdbDevice(body.get('serial', ''), executable=adb)
                        lock = lock_for(device.serial)
                        if not lock.acquire(blocking=False): raise ValueError('设备正在截图或执行流程')
                        try:
                            state = next((s for s in store.load_all() if s['id'] == identifier(body['state_id'])), None)
                            if state is None: raise ValueError('State 不存在')
                            image = device.capture()
                            match = preview_states(image, [state['id']])[0]
                            if not match['eligible']: return self.reply({'match': match, 'executed': False})
                            if match.get('ambiguous'): raise ValueError('识别存在歧义，禁止执行')
                            for action in state['actions']:
                                if action['type'] == 'wait': threading.Event().wait(action.get('ms', 500) / 1000)
                                else: device.execute(action, match, image)
                            return self.reply({'match': match, 'executed': True})
                        finally: lock.release()
                if path in {'/api/pause', '/api/resume'}:
                    with guard:
                        run = runs.get(identifier(body['id']))
                        if not run or not run.get('live'): raise ValueError('运行已经结束，不能暂停或继续')
                        if path == '/api/pause': run['control'].pause()
                        else: run['control'].resume()
                        return self.reply({'ok': True})
                if path == '/api/states':
                    with guard:
                        mutation_allowed()
                        return self.reply(store.save(body))
                if path == '/api/crop':
                    with guard:
                        mutation_allowed()
                        image = cv2.imread(str(capture_path(body['capture_id'])))
                        if image is None:
                            raise ValueError('截图不存在或不可解码')
                        box = body.get('box', [])
                        if len(box) != 4 or not all(isinstance(v, int) for v in box):
                            raise ValueError('框选坐标必须是四个整数')
                        left, top, right, bottom = box
                        if not 0 <= left < right <= image.shape[1] or not 0 <= top < bottom <= image.shape[0]:
                            raise ValueError('框选区域越界或为空')
                        asset = identifier(body['asset_id']) + '.png'
                        save_image(store.assets / asset, image[top:bottom, left:right])
                        return self.reply({'asset': asset})
                if path == '/api/preview':
                    image = cv2.imread(str(capture_path(body['capture_id'])))
                    if image is None:
                        raise ValueError('截图不存在')
                    return self.reply(Recognizer(store, ocr).match(image, validate_state(body['state'])))
                if path == '/api/flow':
                    with guard:
                        mutation_allowed()
                        validate_flow(body, store.load_all())
                        if (store.root / 'flows-migrated.json').exists():
                            store.save_flow({**body, 'id': 'default', 'name': body.get('name', '默认流程')})
                        temporary = store.root / 'flow.tmp'
                        temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
                        temporary.replace(store.root / 'flow.json')
                        return self.reply(body)
                if path == '/api/run':
                    return self.reply(start_run(body))
                if path == '/api/cancel':
                    with guard:
                        runs[identifier(body['id'])]['cancel'].set()
                    return self.reply({'ok': True})
                self.reply({'error': '接口不存在'}, 404)
            except Exception as error:
                self.reply({'error': str(error)}, 400)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)

    def stop_runs():
        with guard:
            active = list(runs.values())
            for run in active:
                run['cancel'].set()
        for run in active:
            run['thread'].join()

    server.stop_runs = stop_runs
    return server
