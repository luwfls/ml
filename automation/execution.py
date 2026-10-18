"""Spawn-based device runs. The HTTP owner holds device leases until workers exit."""
from collections import deque
import copy
import json
import multiprocessing as mp
import os
import threading
import time
from uuid import uuid4

import cv2

from .adb import AdbDevice
from .runner import run_loop, validate_flow
from .state import Store, identifier
from .vision import Recognizer


def uses_text(state):
    r = state['recognition']
    return r['type'] in {'text', 'combined'}


class ProcessControl:
    def __init__(self, cancel, mode, permits, notify):
        self.cancel, self.mode, self.permits, self.notify = cancel, mode, permits, notify

    def checkpoint(self):
        started = time.monotonic()
        if self.mode.value != 2:
            return 0
        self.notify('paused')
        while self.mode.value == 2 and not self.cancel.wait(.02):
            pass
        if not self.cancel.is_set():
            self.notify('running')
        return time.monotonic() - started

    def begin_round(self):
        started = time.monotonic()
        waited = False
        while not self.cancel.is_set():
            if self.mode.value == 0:
                break
            if self.mode.value == 1 and self.permits.acquire(block=False):
                break
            if not waited:
                self.notify('paused' if self.mode.value == 2 else 'waiting')
                waited = True
            self.cancel.wait(.02)
        if not self.cancel.is_set():
            self.notify('running')
        return time.monotonic() - started


def device_worker(root, run_id, adb, ocr_spec, cancel, mode, permits):
    parent = mp.parent_process()
    finished = threading.Event()
    if parent is not None:
        def watch_parent():
            parent.join()
            cancel.set()
            if not finished.wait(2):
                os._exit(1)
        threading.Thread(target=watch_parent, daemon=True).start()
    store = Store(root)
    directory = store.runs / run_id
    config = json.loads((directory / 'config.json').read_text(encoding='utf-8'))
    progress = {'id': run_id, 'pid': os.getpid(), 'serial': config['serial'], 'status': 'initializing',
                'rounds': 0, 'completed_flows': 0, 'flow_index': 0, 'flow_results': [], 'success_count': 0}
    log = None
    result = None

    def emit(event):
        event = {**event, 'flow_index': progress['flow_index'], 'time': time.time()}
        log.write(json.dumps(event, ensure_ascii=False) + '\n')
        log.flush()
        if event['type'] == 'frame':
            progress['rounds'] += 1
            progress['frame_url'] = f"/runs/{run_id}/frame-{event['index']:04d}.png"
        if event['type'] == 'success':
            progress['success_count'] = event['count']
        store.write_json(directory / 'summary.json', progress)

    def notify(status):
        progress['status'] = status
        emit({'type': 'control', 'status': status})

    try:
        with (directory / 'events.jsonl').open('w', encoding='utf-8') as log:
            store.write_json(directory / 'summary.json', progress)
            provider = None
            if ocr_spec.get('enabled'):
                from .ocr import RapidOcrProvider
                provider = RapidOcrProvider(ocr_spec.get('config_path'))
            device = AdbDevice(config['serial'], executable=adb, cancel=cancel)
            control = ProcessControl(cancel, mode, permits, notify)

            class RecordingDevice:
                count = 0

                def capture(self):
                    image = device.capture()
                    self.count += 1
                    if not cv2.imwrite(str(directory / f'frame-{self.count:04d}.png'), image):
                        raise OSError('截图写入失败')
                    emit({'type': 'frame', 'index': self.count})
                    return image

                def execute(self, action, match, frame):
                    if not cancel.is_set():
                        device.execute(action, match, frame)

            recording = RecordingDevice()
            for index, flow in enumerate(config['flows']):
                if cancel.is_set():
                    result = {'status': 'cancelled', 'reason': 'user_cancelled'}
                    break
                progress.update(flow_index=index, flow_id=flow.get('id'), flow_name=flow.get('name', ''), success_count=0)
                emit({'type': 'flow_started', 'flow_id': flow.get('id')})
                result = run_loop(config['states'], flow, recording, Recognizer(store, provider), cancel, emit, control)
                progress['flow_results'].append({'flow_id': flow.get('id'), 'flow_index': index, **result})
                emit({'type': 'flow_finished', **result})
                if result['status'] != 'passed':
                    break
                progress['completed_flows'] += 1
            if cancel.is_set():
                result = {'status': 'cancelled', 'reason': 'user_cancelled'}
    except Exception as error:
        result = {'status': 'cancelled' if cancel.is_set() else 'error', 'reason': str(error)}
    result = {**progress, **(result or {'status': 'error', 'reason': 'no_result'})}
    store.write_json(directory / 'result.json', result)
    finished.set()


class ExecutionManager:
    def __init__(self, store, adb='adb', ocr_spec=None, guard=None, lock_for=None):
        self.store, self.adb = store, adb
        self.ocr_spec = ocr_spec or {'enabled': False}
        self.guard = guard or threading.RLock()
        self.locks = {}
        self.lock_for = lock_for or (lambda serial: self.locks.setdefault(serial, threading.Lock()))
        self.context = mp.get_context('spawn')
        self.workers = {}
        self.batches = store.root / 'batches'
        self.batches.mkdir(exist_ok=True)

    def refresh(self):
        with self.guard:
            for run_id, worker in list(self.workers.items()):
                if worker['process'].is_alive():
                    continue
                worker['process'].join()
                directory = self.store.runs / run_id
                if not (directory / 'result.json').exists():
                    result = {'status': 'cancelled' if worker['cancel'].is_set() else 'error',
                              'reason': 'worker_terminated' if worker['cancel'].is_set() else 'worker_exited',
                              'pid': worker['process'].pid}
                    self.store.write_json(directory / 'result.json', result)
                worker['lock'].release()
                worker['process'].close()
                del self.workers[run_id]

    def active(self):
        self.refresh()
        return bool(self.workers)

    def start_batch(self, flows, states, serials, online, task=None, mode='auto'):
        if mode not in {'auto', 'step'}:
            raise ValueError('执行方式必须为 auto 或 step')
        if not isinstance(serials, list) or not serials or any(not isinstance(s, str) or not s.strip() for s in serials):
            raise ValueError('请选择设备 serial 列表')
        serials = [s.strip() for s in serials]
        if len(set(serials)) != len(serials):
            raise ValueError('设备 serial 不能重复')
        if not isinstance(flows, list) or not flows:
            raise ValueError('任务必须有流程')
        states, flows, task = copy.deepcopy((states, flows, task))
        for flow in flows:
            validate_flow(flow, states)
        if not self.ocr_spec.get('enabled') and any(uses_text(s) for s in states):
            raise ValueError('OCR 未配置')
        with self.guard:
            self.refresh()
            if task and any(self.detail(i)['task_id'] == task['id'] for i in self.workers if self.detail(i).get('task_id')):
                raise ValueError('任务已在运行')
            batch_id = uuid4().hex
            batch = {'batch_id': batch_id, 'task_id': task['id'] if task else None, 'task': task,
                     'flows': flows, 'mode': mode, 'results': []}
            # Persist intent before starting processes, including partial startup failures.
            self.store.write_json(self.batches / (batch_id + '.json'), batch)
            for serial in serials:
                try:
                    if serial not in online:
                        raise ValueError('设备不在线或未授权')
                    run_id = self._start(serial, flows, states, task, batch_id, mode)
                    batch['results'].append({'serial': serial, 'id': run_id})
                except Exception as error:
                    batch['results'].append({'serial': serial, 'error': str(error)})
            try:
                self.store.write_json(self.batches / (batch_id + '.json'), batch)
            except Exception:
                for result in batch['results']:
                    if 'id' in result:
                        self.command(result['id'], 'cancel')
                raise
            return batch

    def _start(self, serial, flows, states, task, batch_id, mode):
        lock = self.lock_for(serial)
        if not lock.acquire(blocking=False):
            raise ValueError('该设备正在截图或执行流程')
        run_id = uuid4().hex
        directory = self.store.runs / run_id
        process = None
        try:
            directory.mkdir()
            config = {'engine': 'process', 'serial': serial, 'flows': flows, 'flow': flows[0],
                      'states': states, 'task': task, 'batch_id': batch_id, 'mode': mode}
            if task:
                config.update(task_id=task['id'], task_name=task['name'])
            self.store.write_json(directory / 'config.json', config)
            cancel, mode_value, permits = self.context.Event(), self.context.Value('i', 0 if mode == 'auto' else 1), self.context.Semaphore(0)
            process = self.context.Process(target=device_worker, args=(str(self.store.root), run_id, self.adb, self.ocr_spec, cancel, mode_value, permits), name=f'device-{run_id}')
            process.start()
            self.workers[run_id] = {'process': process, 'cancel': cancel, 'mode': mode_value, 'permits': permits, 'lock': lock, 'resume_mode': mode_value.value}
            return run_id
        except Exception:
            if process is not None and process.pid is not None:
                process.terminate()
                process.join()
            lock.release()
            if (directory / 'config.json').exists():
                self.store.write_json(directory / 'result.json', {'status': 'error', 'reason': 'worker_start_failed'})
            raise

    def detail(self, run_id, include_events=True):
        identifier(run_id)
        with self.guard:
            self.refresh()
            directory = self.store.runs / run_id
            config = json.loads((directory / 'config.json').read_text(encoding='utf-8'))
            live = run_id in self.workers
            summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8')) if (directory / 'summary.json').exists() else {}
            result = json.loads((directory / 'result.json').read_text(encoding='utf-8')) if (directory / 'result.json').exists() else {}
            detail = {'id': run_id, 'serial': config['serial'], 'batch_id': config['batch_id'], 'rounds': 0,
                      'flow_results': [], 'completed_flows': 0, 'snapshot': config,
                      'status': 'initializing' if live else 'interrupted', 'reason': '' if live else 'server_restarted',
                      **summary, **result, 'live': live}
            if not live and not result:
                detail.update(status='interrupted', reason='server_restarted')
            if config.get('task'):
                detail.update(task_id=config['task']['id'], task_name=config['task']['name'])
            if live:
                detail['pid'] = self.workers[run_id]['process'].pid
                detail['mode'] = {0: 'auto', 1: 'step', 2: 'paused'}[self.workers[run_id]['mode'].value]
                if self.workers[run_id].get('step_round') == detail['rounds'] and detail['status'] == 'waiting':
                    detail['status'] = 'running'
                if not result:
                    detail['reason'] = ''
            if include_events:
                events = deque(maxlen=200)
                path = directory / 'events.jsonl'
                if path.exists():
                    for line in path.read_text(encoding='utf-8').splitlines():
                        try: events.append(json.loads(line))
                        except json.JSONDecodeError: pass
                detail['events'] = list(events)
            return detail

    def batch_detail(self, batch_id):
        batch = json.loads((self.batches / (identifier(batch_id) + '.json')).read_text(encoding='utf-8'))
        runs = [self.detail(r['id']) for r in batch['results'] if 'id' in r]
        live = any(r['live'] for r in runs)
        statuses = [r['status'] for r in runs]
        status = 'running' if live else 'error' if any('error' in r for r in batch['results']) else 'passed'
        if not live:
            for terminal in ['error', 'interrupted', 'failed', 'paused', 'cancelled']:
                if terminal in statuses:
                    status = terminal
                    break
        return {**batch, 'runs': runs, 'live': live, 'status': status}

    def command(self, run_id, action):
        with self.guard:
            detail = self.detail(run_id)
            worker = self.workers.get(run_id)
            if action == 'cancel' and not worker:
                return detail
            if not worker:
                raise ValueError('运行已结束')
            if action == 'cancel':
                worker['cancel'].set()
                worker['process'].join(timeout=2)
                if worker['process'].is_alive():
                    worker['process'].terminate()
                    worker['process'].join(timeout=5)
                if worker['process'].is_alive():
                    raise RuntimeError('设备进程尚未退出，锁仍保留')
                self.refresh()
            elif action == 'pause':
                if worker['mode'].value != 2:
                    worker['resume_mode'] = worker['mode'].value
                    worker['mode'].value = 2
            elif action == 'resume':
                if worker['mode'].value != 2:
                    raise ValueError('只有暂停状态可以继续')
                worker['mode'].value = worker['resume_mode']
            elif action in {'auto', 'step'}:
                worker.pop('step_round', None)
                worker['mode'].value = 0 if action == 'auto' else 1
                while worker['permits'].acquire(block=False):
                    pass
            elif action == 'next':
                if worker['mode'].value != 1 or detail['status'] != 'waiting':
                    raise ValueError('只有等待步进的设备可以执行下一轮')
                worker['step_round'] = detail['rounds']
                worker['permits'].release()
            else:
                raise ValueError('无效运行操作')
            return self.detail(run_id)

    def cancel_batch(self, batch_id):
        batch = self.batch_detail(batch_id)
        # Signal all devices before waiting for any one of them.
        with self.guard:
            for run in batch['runs']:
                if run['id'] in self.workers:
                    self.workers[run['id']]['cancel'].set()
            for run in batch['runs']:
                self.command(run['id'], 'cancel')
        return self.batch_detail(batch_id)

    def close(self):
        with self.guard:
            for worker in self.workers.values():
                worker['cancel'].set()
            for run_id in list(self.workers):
                self.command(run_id, 'cancel')
