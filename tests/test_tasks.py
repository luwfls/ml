"""Task persistence and validation through the public HTTP API."""
import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from automation.state import Store
from automation.web import create_server


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save({'id': 'done', 'role': 'success', 'recognition': {'type': 'text', 'texts': ['完成']}})
        for flow_id in ['first', 'second']:
            self.store.save_flow({'id': flow_id, 'name': flow_id, 'state_ids': ['done']})
        self.start_server()

    def start_server(self):
        self.server = create_server(self.store, port=0)
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

    def test_ordered_task_crud_persists_across_restart(self):
        self.assertEqual(self.request('/api/tasks'), [])
        task = self.request('/api/tasks', {'name': ' 收货回归 ', 'flow_ids': ['second', 'first']})
        self.assertRegex(task['id'], r'^[a-f0-9]{32}$')
        self.assertEqual(task['name'], '收货回归')
        self.assertEqual(task['flow_ids'], ['second', 'first'])
        updated = self.request('/api/tasks', {**task, 'name': '新名称'})
        self.assertEqual(updated['id'], task['id'])
        self.assertGreater(updated['revision'], task['revision'])
        self.stop_server()
        self.store = Store(self.directory.name)
        self.start_server()
        self.assertEqual(self.request('/api/tasks'), [updated])
        self.assertEqual(self.request('/api/tasks/delete', {'id': task['id']}), {'ok': True})
        self.assertEqual(self.request('/api/tasks'), [])

    def test_legacy_single_flow_field_remains_supported(self):
        task = self.request('/api/tasks', {'name': '旧任务', 'flow_id': 'first'})
        self.assertEqual(task['flow_ids'], ['first'])
        self.assertEqual(task['flow_id'], 'first')

    def test_task_validation_and_all_flow_reference_protection(self):
        invalid = [{'name': '', 'flow_ids': ['first']}, {'name': '  ', 'flow_ids': ['first']},
                   {'name': 1, 'flow_ids': ['first']}, {'name': 'x', 'flow_ids': ['missing']},
                   {'name': 'x', 'flow_ids': []}, {'name': 'x', 'flow_ids': 'first'},
                   {'id': '../bad', 'name': 'x', 'flow_ids': ['first']}]
        for body in invalid:
            with self.subTest(body=body):
                self.reject('/api/tasks', body)
        task = self.request('/api/tasks', {'name': '引用两个流程', 'flow_ids': ['first', 'second']})
        for flow_id in ['first', 'second']:
            self.assertIn('任务', self.reject('/api/flows/delete', {'id': flow_id}))
        self.request('/api/tasks/delete', {'id': task['id']})
        for flow_id in ['first', 'second']:
            self.assertEqual(self.request('/api/flows/delete', {'id': flow_id}), {'ok': True})

    def test_invalid_serial_selection_and_unknown_task_start_no_workers(self):
        task = self.request('/api/tasks', {'name': '验证任务', 'flow_ids': ['first']})
        for serials in [None, [], 'one', [None], [1], [''], ['  '], ['one', ' one ']]:
            with self.subTest(serials=serials):
                self.reject('/api/tasks/start', {'id': task['id'], 'serials': serials})
                self.assertEqual(self.request('/api/runs'), [])
        self.reject('/api/tasks/start', {'id': 'missing', 'serials': ['one']})
        self.assertEqual(self.request('/api/runs'), [])

    def test_missing_flow_start_fails_before_any_worker_is_created(self):
        task = self.request('/api/tasks', {'name': '验证任务', 'flow_ids': ['first', 'second']})
        (self.store.flows / 'second.json').unlink()
        self.reject('/api/tasks/start', {'id': task['id'], 'serials': ['one']})
        self.assertEqual(self.request('/api/runs'), [])


if __name__ == '__main__':
    unittest.main()
