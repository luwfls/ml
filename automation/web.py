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
from .runner import run_loop, validate_flow
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
        if any(run['status'] == 'running' for run in runs.values()):
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
            run = {'id': run_id, 'status': 'running', 'events': [], 'cancel': cancel}
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

                    result = run_loop(states, flow, RecordingDevice(), Recognizer(store, ocr), cancel=cancel, emit=emit)
            except Exception as error:
                result = {'status': 'error', 'reason': str(error)}
            try:
                (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception as error:
                result = {'status': 'error', 'reason': f'运行结果写入失败: {error}'}
            finally:
                with guard:
                    run.update(result)
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
                if path == '/api/flow':
                    file = store.root / 'flow.json'
                    return self.reply(json.loads(file.read_text(encoding='utf-8')) if file.exists() else None)
                if path.startswith('/api/runs/'):
                    run_id = identifier(path.split('/')[-1])
                    with guard:
                        run = runs.get(run_id)
                        if run:
                            return self.reply({k: v for k, v in run.items() if k not in {'cancel', 'thread'}})
                    result = store.runs / run_id / 'result.json'
                    return self.reply({'id': run_id, **json.loads(result.read_text(encoding='utf-8'))})
                if path.startswith('/captures/') or (path.startswith('/assets/') and path.endswith('.png')):
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
