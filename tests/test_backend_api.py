"""HTTP contracts exercised with real spawn workers and an executable fake adb."""
import base64
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import cv2
import numpy as np

from automation.state import Store
from automation.web import create_server


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'data')
        frame = np.random.default_rng(10).integers(0, 255, (50, 70, 3), dtype=np.uint8)
        cv2.imwrite(str(self.root / 'good.png'), frame)
        cv2.imwrite(str(self.root / 'blank.png'), np.zeros_like(frame))
        cv2.imwrite(str(self.store.assets / 'done.png'), frame[10:25, 20:40])
        self.store.save({'id': 'done', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'done.png'}})
        self.first = self.store.save_flow({'id': 'first', 'name': '第一流程', 'state_ids': ['done'], 'poll_ms': 10})
        self.second = self.store.save_flow({'id': 'second', 'name': '第二流程', 'state_ids': ['done'], 'poll_ms': 10})
        adb = self.root / 'adb'
        adb.write_text('#!' + os.sys.executable + '\nimport sys\nfrom pathlib import Path\n'
                       'if sys.argv[1:2] == ["devices"]:\n'
                       ' print("List of devices attached\\none\\tdevice\\ntwo\\tdevice\\nwait\\tdevice\\nbroken\\tdevice\\noffline\\toffline\\nunauthorized\\tunauthorized")\n'
                       'elif "dumpsys" in sys.argv:print("Viewport INTERNAL: logicalFrame=[0, 0, 70, 50] isActive=[1]")\n'
                       'elif "input" in sys.argv:\n'
                       ' with (Path(__file__).parent/"actions.log").open("a") as log:log.write(" ".join(sys.argv)+"\\n")\n'
                       'elif "screencap" in sys.argv:\n'
                       ' serial=sys.argv[2]\n'
                       ' if serial=="broken":sys.exit(1)\n'
                       ' sys.stdout.buffer.write((Path(__file__).parent/("blank.png" if serial=="wait" else "good.png")).read_bytes())\n')
        adb.chmod(0o755)
        self.adb = str(adb)
        self.start_server()

    def start_server(self):
        self.server = create_server(self.store, port=0, adb=self.adb)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def stop_server(self):
        self.server.stop_runs()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop_server()
        self.tmp.cleanup()

    def request(self, route, body=None):
        request = Request(self.url + route, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    def reject(self, route, body):
        with self.assertRaises(HTTPError) as caught:
            self.request(route, body)
        with caught.exception as response:
            self.assertEqual(response.code, 400)
            return json.load(response)['error']

    def until(self, route, condition, timeout=10):
        deadline = time.monotonic() + timeout
        result = None
        while time.monotonic() < deadline:
            result = self.request(route)
            if condition(result):
                return result
            time.sleep(.025)
        self.fail('HTTP execution did not reach expected state: ' + str(result))

    def task(self, **kwargs):
        return self.request('/api/tasks', {'name': '收货回归', 'flow_ids': ['first', 'second'], **kwargs})

    def start(self, task, serials):
        return self.request('/api/tasks/start', {'id': task['id'], 'serials': serials})

    def test_ordered_flows_execute_in_distinct_spawn_processes(self):
        task = self.task(flow_ids=['second', 'first'])
        batch = self.start(task, ['one', 'two'])
        detail = self.until('/api/batches/' + batch['batch_id'], lambda b: not b['live'])
        self.assertEqual(detail['status'], 'passed')
        self.assertEqual(detail['task_id'], task['id'])
        self.assertEqual([r['serial'] for r in detail['runs']], ['one', 'two'])
        self.assertEqual(len({r['pid'] for r in detail['runs']}), 2)
        for run in detail['runs']:
            self.assertNotEqual(run['pid'], os.getpid())
            self.assertEqual(run['completed_flows'], 2)
            self.assertEqual([f['flow_id'] for f in run['flow_results']], ['second', 'first'])
            self.assertEqual(run['snapshot']['task'], task)
            self.assertEqual([f['id'] for f in run['snapshot']['flows']], ['second', 'first'])
            self.assertEqual(self.request('/api/runs/' + run['id'])['status'], 'passed')
        self.assertEqual(len(self.request('/api/runs')), 2)
        self.assertEqual(self.request('/api/batches')[0]['batch_id'], batch['batch_id'])

    def test_active_snapshot_survives_edits_and_duplicate_task_is_rejected(self):
        task = self.task()
        batch = self.start(task, ['wait'])
        route = '/api/runs/' + batch['results'][0]['id']
        self.until(route, lambda r: r['rounds'] > 0)
        self.reject('/api/tasks/start', {'id': task['id'], 'serials': ['one']})
        updated = self.request('/api/tasks', {**task, 'name': '下次运行', 'flow_ids': ['second']})
        self.request('/api/flows', {**self.first, 'name': '修改流程'})
        run = self.request(route)
        self.assertEqual(run['snapshot']['task']['name'], task['name'])
        self.assertEqual(run['snapshot']['flows'][0]['name'], self.first['name'])
        self.reject('/api/tasks/delete', {'id': task['id']})
        self.reject('/api/states', {'id': 'new', 'recognition': {'type': 'image', 'asset': 'done.png'}})
        self.reject('/api/crop', {'capture_id': 'missing', 'asset_id': 'new', 'box': [0, 0, 5, 5]})
        stopped = self.request('/api/tasks/stop', {'batch_id': batch['batch_id']})
        self.assertFalse(stopped['live'])
        self.assertEqual(stopped['status'], 'cancelled')
        next_batch = self.start(updated, ['one'])
        detail = self.until('/api/batches/' + next_batch['batch_id'], lambda b: not b['live'])
        self.assertEqual(len(detail['runs'][0]['snapshot']['flows']), 1)
        self.assertEqual(detail['runs'][0]['snapshot']['task']['name'], '下次运行')

    def test_busy_offline_and_execution_failures_are_isolated(self):
        occupied = self.start(self.task(), ['wait'])
        batch = self.start(self.task(name='另一任务'), ['wait', 'offline', 'unauthorized', 'unknown', 'broken', 'two'])
        self.assertTrue(all('error' in r for r in batch['results'][:4]))
        self.assertTrue(all('id' in r for r in batch['results'][4:]))
        finished = self.until('/api/batches/' + batch['batch_id'], lambda b: not b['live'])
        self.assertEqual([r['status'] for r in finished['runs']], ['error', 'passed'])
        self.request('/api/tasks/stop', {'batch_id': occupied['batch_id']})
        self.assertFalse(self.request('/api/batches/' + occupied['batch_id'])['live'])

    def test_batch_cancel_is_confirmed_and_history_survives_server_restart(self):
        task = self.task()
        batch = self.start(task, ['wait'])
        stopped = self.request('/api/tasks/stop', {'batch_id': batch['batch_id']})
        self.assertFalse(stopped['live'])
        self.stop_server()
        self.store = Store(self.root / 'data')
        self.start_server()
        previous = self.request('/api/batches/' + batch['batch_id'])
        self.assertFalse(previous['live'])
        self.assertEqual(previous['status'], 'cancelled')
        self.assertEqual(previous['runs'][0]['task_name'], task['name'])
        retry = self.start(task, ['wait'])
        self.assertIn('id', retry['results'][0])
        self.assertNotEqual(retry['batch_id'], batch['batch_id'])
        self.assertEqual(len(self.request('/api/batches')), 2)

    def test_debug_draft_step_executes_exactly_one_round_without_saving_flow(self):
        draft = {**self.first, 'name': '未保存草稿', 'poll_ms': 0}
        batch = self.request('/api/debug/start', {'flow': draft, 'serials': ['wait'], 'mode': 'step'})
        run_id = batch['results'][0]['id']
        route = '/api/runs/' + run_id
        waiting = self.until(route, lambda r: r['status'] == 'waiting')
        self.assertEqual(waiting['rounds'], 0)
        self.assertEqual(waiting['snapshot']['flows'][0]['name'], draft['name'])
        self.assertFalse(waiting['snapshot']['flows'][0].get('dry_run', False))
        self.request('/api/debug/control', {'id': run_id, 'action': 'next'})
        self.until(route, lambda r: r['status'] == 'waiting' and r['rounds'] == 1)
        time.sleep(.1)
        self.assertEqual(self.request(route)['rounds'], 1)
        self.request('/api/debug/control', {'id': run_id, 'action': 'auto'})
        self.until(route, lambda r: r['rounds'] > 1)
        self.request('/api/debug/control', {'id': run_id, 'action': 'pause'})
        self.until(route, lambda r: r['status'] == 'paused')
        self.request('/api/debug/control', {'id': run_id, 'action': 'resume'})
        self.until(route, lambda r: r['mode'] == 'auto')
        self.request('/api/cancel', {'id': run_id})
        self.assertFalse(self.request(route)['live'])
        self.assertEqual(next(f for f in self.request('/api/flows') if f['id'] == 'first')['name'], self.first['name'])

    def test_debug_defaults_to_real_actions_and_supports_explicit_dry_run(self):
        missing = np.random.default_rng(99).integers(0, 255, (15, 20, 3), dtype=np.uint8)
        cv2.imwrite(str(self.store.assets / 'future.png'), missing)
        self.store.save({'id': 'future', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'future.png'}})
        self.store.save({'id': 'click', 'recognition': {'type': 'image', 'asset': 'done.png'},
                         'actions': [{'type': 'key', 'key': 'back'}]})
        flow = {'name': '动作草稿', 'state_ids': ['click', 'future'], 'max_rounds': 1, 'poll_ms': 0}
        first = self.request('/api/debug/start', {'flow': flow, 'serials': ['one']})
        self.until('/api/batches/' + first['batch_id'], lambda b: not b['live'])
        log = self.root / 'actions.log'
        self.assertIn('input keyevent 4', log.read_text())
        actions = log.read_text()
        dry = self.request('/api/debug/start', {'flow': flow, 'serials': ['one'], 'dry_run': True})
        result = self.until('/api/batches/' + dry['batch_id'], lambda b: not b['live'])
        self.assertTrue(result['runs'][0]['snapshot']['flows'][0]['dry_run'])
        self.assertEqual(log.read_text(), actions)

    def test_state_save_commits_crop_and_generated_state_atomically(self):
        imported = self.request('/api/import', {'png': base64.b64encode((self.root / 'good.png').read_bytes()).decode()})
        saved = self.request('/api/states/save', {'state': {'name': '新状态', 'recognition': {'type': 'image'}},
                                                   'capture_id': imported['id'], 'box': [20, 10, 40, 25]})
        self.assertRegex(saved['id'], r'^[a-f0-9]{32}$')
        asset = saved['recognition']['asset']
        self.assertEqual(cv2.imread(str(self.store.assets / asset)).shape[:2], (15, 20))
        states_before = self.request('/api/states')
        assets_before = set(self.store.assets.iterdir())
        self.reject('/api/states/save', {'state': {'name': '无效', 'role': 'invalid', 'recognition': {'type': 'image'}},
                                         'capture_id': imported['id'], 'box': [20, 10, 40, 25]})
        self.assertEqual(self.request('/api/states'), states_before)
        self.assertEqual(set(self.store.assets.iterdir()), assets_before)
        with patch.object(self.store, 'save', side_effect=OSError('disk full')):
            error = self.reject('/api/states/save', {'state': {'name': '保存失败', 'recognition': {'type': 'image'}},
                                                    'capture_id': imported['id'], 'box': [20, 10, 40, 25]})
        self.assertIn('disk full', error)
        self.assertEqual(self.request('/api/states'), states_before)
        self.assertEqual(set(self.store.assets.iterdir()), assets_before)


if __name__ == '__main__':
    unittest.main()
