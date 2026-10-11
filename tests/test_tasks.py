import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import numpy as np

from automation import web
from automation.state import Store
from automation.web import create_server


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save({'id': 'done', 'role': 'success', 'recognition': {'type': 'text', 'texts': ['完成']}})
        self.flow = self.store.save_flow({'id': 'flow', 'name': '流程', 'state_ids': ['done'], 'poll_ms': 0})
        self.entered = {serial: threading.Event() for serial in ['one', 'two', 'broken']}
        self.release = {serial: threading.Event() for serial in self.entered}
        self.failures = set()
        owner = self

        class Device:
            def __init__(self, serial, **kwargs):
                self.serial = serial.strip()

            def capture(self):
                owner.entered[self.serial].set()
                if not owner.release[self.serial].wait(3):
                    raise RuntimeError('test gate timed out')
                if self.serial in owner.failures:
                    raise RuntimeError('device capture failed')
                return np.zeros((20, 30, 3), np.uint8)

        self.device_patch = patch('automation.web.AdbDevice', Device)
        self.online_patch = patch('automation.web.list_devices', return_value=[
            {'serial': serial, 'status': 'device'} for serial in self.entered
        ] + [{'serial': 'offline', 'status': 'offline'}, {'serial': 'unauthorized', 'status': 'unauthorized'}])
        self.device_patch.start()
        self.online_patch.start()
        self.start_server()

    def start_server(self):
        self.server = create_server(self.store, port=0, ocr=lambda frame: [
            {'text': '完成', 'confidence': 1, 'bbox': [1, 1, 10, 10]}])
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def stop_server(self):
        for gate in self.release.values():
            gate.set()
        self.server.stop_runs()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop_server()
        self.device_patch.stop()
        self.online_patch.stop()
        self.directory.cleanup()

    def request(self, route, body=None):
        request = Request(self.url + route, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def reject(self, route, body):
        with self.assertRaises(HTTPError) as caught:
            self.request(route, body)
        with caught.exception as response:
            self.assertEqual(response.code, 400)
            return json.load(response)['error']

    def task(self):
        return self.request('/api/tasks', {'name': '收货回归', 'flow_id': 'flow'})

    def start(self, task, serials):
        return self.request('/api/tasks/start', {'id': task['id'], 'serials': serials})

    def test_crud_auto_id_and_restart(self):
        self.assertEqual(self.request('/api/tasks'), [])
        task = self.task()
        self.assertRegex(task['id'], r'^[a-f0-9]{32}$')
        self.assertEqual(task['name'], '收货回归')
        updated = self.request('/api/tasks', {**task, 'name': '新名称'})
        self.assertEqual(updated['id'], task['id'])
        self.stop_server()
        self.store = Store(self.directory.name)
        self.start_server()
        self.assertEqual(self.request('/api/tasks'), [updated])
        self.assertEqual(self.request('/api/tasks/delete', {'id': task['id']}), {'ok': True})
        self.assertEqual(self.request('/api/tasks'), [])

    def test_task_validation_and_flow_reference_protection(self):
        for body in [{'name': '', 'flow_id': 'flow'}, {'name': '  ', 'flow_id': 'flow'},
                     {'name': 1, 'flow_id': 'flow'}, {'name': 'x', 'flow_id': 'missing'},
                     {'id': '../bad', 'name': 'x', 'flow_id': 'flow'}]:
            self.reject('/api/tasks', body)
        task = self.task()
        self.assertIn('任务', self.reject('/api/flows/delete', {'id': 'flow'}))
        self.request('/api/tasks/delete', {'id': task['id']})
        self.assertEqual(self.request('/api/flows/delete', {'id': 'flow'}), {'ok': True})

    def test_invalid_serial_selection_is_rejected_before_any_run(self):
        task = self.task()
        for serials in [None, [], 'one', [None], [1], [''], ['  '], ['one', ' one ']]:
            self.reject('/api/tasks/start', {'id': task['id'], 'serials': serials})
            self.assertEqual(self.request('/api/runs'), [])

    def test_unknown_task_and_missing_flow_do_not_start(self):
        self.reject('/api/tasks/start', {'id': 'missing', 'serials': ['one']})
        task = self.task()
        (self.store.flows / 'flow.json').unlink()
        self.reject('/api/tasks/start', {'id': task['id'], 'serials': ['one']})
        self.assertEqual(self.request('/api/runs'), [])

    def test_two_real_workers_overlap_and_metadata_survives_restart(self):
        task = self.task()
        batch = self.start(task, [' one ', 'two'])
        self.assertEqual(batch['task_id'], task['id'])
        self.assertEqual([r['serial'] for r in batch['results']], ['one', 'two'])
        self.assertNotEqual(batch['results'][0]['id'], batch['results'][1]['id'])
        for serial in ['one', 'two']:
            self.assertTrue(self.entered[serial].wait(1), serial)
        for run in self.request('/api/runs'):
            self.assertTrue(run['live'])
            self.assertEqual(run['task_name'], task['name'])
            self.assertEqual(run['batch_id'], batch['batch_id'])
            config = json.loads((self.store.runs / run['id'] / 'config.json').read_text())
            self.assertEqual(config['flow'], self.flow)
            self.assertEqual(config['task_id'], task['id'])
            self.assertEqual(config['task_name'], task['name'])
            self.assertEqual(config['batch_id'], batch['batch_id'])
        self.stop_server()
        self.start_server()
        self.request('/api/tasks', {**task, 'name': '后来改名'})
        for item in batch['results']:
            detail = self.request('/api/runs/' + item['id'])
            self.assertFalse(detail['live'])
            self.assertEqual(detail['task_name'], task['name'])
            self.assertEqual(detail['task_id'], task['id'])
            self.assertEqual(detail['batch_id'], batch['batch_id'])
        self.assertEqual(len(self.request('/api/runs')), 2)

    def test_busy_offline_and_unknown_devices_do_not_block_free_device(self):
        task = self.task()
        first = self.start(task, ['one'])
        self.assertTrue(self.entered['one'].wait(1))
        second = self.start(task, ['one', 'offline', 'unauthorized', 'unknown', 'two'])
        self.assertNotEqual(first['batch_id'], second['batch_id'])
        self.assertTrue(all('error' in result for result in second['results'][:-1]))
        self.assertIn('id', second['results'][-1])
        self.assertTrue(self.entered['two'].wait(1))
        self.assertEqual(len(self.request('/api/runs')), 2)

    def test_one_device_initialization_failure_still_starts_next_device(self):
        task = self.task()
        factory = web.AdbDevice

        def device(serial, **kwargs):
            if serial == 'broken':
                raise RuntimeError('initialization failed')
            return factory(serial, **kwargs)

        with patch('automation.web.AdbDevice', side_effect=device):
            batch = self.start(task, ['broken', 'two'])
        self.assertEqual(batch['results'][0], {'serial': 'broken', 'error': 'initialization failed'})
        self.assertIn('id', batch['results'][1])
        self.assertTrue(self.entered['two'].wait(1))
        self.assertEqual(len(self.request('/api/runs')), 1)

    def test_running_task_crud_uses_existing_mutation_guard(self):
        task = self.task()
        self.start(task, ['one'])
        self.assertTrue(self.entered['one'].wait(1))
        self.assertIn('运行期间', self.reject('/api/tasks', {**task, 'name': '改名'}))
        self.assertIn('运行期间', self.reject('/api/tasks/delete', {'id': task['id']}))

    def test_device_execution_failure_does_not_cancel_healthy_worker(self):
        task = self.task()
        self.failures.add('broken')
        batch = self.start(task, ['broken', 'two'])
        for serial in ['broken', 'two']:
            self.assertTrue(self.entered[serial].wait(1))
        self.release['broken'].set()
        self.release['two'].set()
        deadline = time.monotonic() + 2
        while any(run['live'] for run in self.request('/api/runs')) and time.monotonic() < deadline:
            threading.Event().wait(.01)
        broken, healthy = [self.request('/api/runs/' + result['id']) for result in batch['results']]
        self.assertEqual(broken['status'], 'error')
        self.assertEqual(healthy['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
