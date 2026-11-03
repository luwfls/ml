"""Recorded local HTTP business cases; device input uses an executable fixture."""
import argparse
import base64
from datetime import datetime
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_backend_api import BackendApiTests
from automation.ocr import RapidOcrProvider
from automation.web import create_server


CASE_IDS = dict(zip([
    'test_ordered_flows_execute_in_distinct_spawn_processes',
    'test_active_snapshot_survives_edits_and_duplicate_task_is_rejected',
    'test_busy_offline_and_execution_failures_are_isolated',
    'test_batch_cancel_is_confirmed_and_history_survives_server_restart',
    'test_debug_draft_step_executes_exactly_one_round_without_saving_flow',
    'test_debug_defaults_to_real_actions_and_supports_explicit_dry_run',
    'test_state_save_commits_crop_and_generated_state_atomically',
    'test_empty_flow_http_contract',
    'test_real_ocr_without_adb',
    'test_invalid_images_and_regions',
], [f'API-{i:02}' for i in range(1, 11)]))
OUTPUT = None


def now():
    return datetime.now().astimezone().isoformat()


class EvidenceApiTests(BackendApiTests):
    def setUp(self):
        self.records = []
        super().setUp()

    def request(self, route, body=None):
        record = {'case_id': CASE_IDS[self._testMethodName], 'started_at': now(),
                  'request': {'method': 'POST' if body is not None else 'GET', 'path': route, 'body': body},
                  'environment': 'isolated-localhost', 'trace_id': None}
        try:
            value = super().request(route, body)
            record['response'] = {'status': 200, 'body': value}
            return value
        except HTTPError as error:
            raw = error.read()
            record['response'] = {'status': error.code, 'body': json.loads(raw)}
            raise HTTPError(error.url, error.code, error.msg, error.headers, io.BytesIO(raw)) from None
        finally:
            record['finished_at'] = now()
            self.records.append(record)

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            path = OUTPUT / (CASE_IDS[self._testMethodName] + '.json')
            path.write_text(json.dumps(self.records, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_empty_flow_http_contract(self):
        empty = self.request('/api/flows', {'name': '待编排流程'})
        self.assertRegex(empty['id'], r'^[a-f0-9]{32}$')
        self.assertEqual(empty['state_ids'], [])
        updated = self.request('/api/flows', {**empty, 'name': '更新名称'})
        self.assertEqual(updated['id'], empty['id'])
        copied = self.request('/api/flows/copy', {'id': empty['id'], 'name': '副本'})
        self.assertNotEqual(copied['id'], empty['id'])
        self.assertEqual(copied['state_ids'], [])
        self.assertIn(updated, self.request('/api/flows'))
        self.assertIn('请选择 State', self.reject('/api/run', {'serial': 'one', 'flow': empty}))
        self.reject('/api/flows', {'name': '坏引用', 'state_ids': ['missing']})

    def test_real_ocr_without_adb(self):
        self.stop_server()
        self.server = create_server(self.store, port=0, adb=None, ocr=RapidOcrProvider())
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        health = self.request('/api/health')
        self.assertEqual((health['ocr'], health['adb']), ('ready', 'disabled'))
        fixture = Path(__file__).parent / 'fixtures/ocr-ui.png'
        capture = self.request('/api/import', {'png': base64.b64encode(fixture.read_bytes()).decode()})
        state = {'id': 'chinese', 'name': '中文确认', 'actions': [],
                 'recognition': {'type': 'text', 'texts': ['不存在的候选', '确认收货']}}
        exact = self.request('/api/preview', {'capture_id': capture['id'], 'state': state})
        self.assertTrue(exact['found'])
        self.assertEqual(exact['text'], '确认收货')
        fuzzy_state = {**state, 'recognition': {'type': 'text', 'texts': ['确认收获'],
                                               'mode': 'fuzzy', 'similarity_threshold': .7}}
        fuzzy = self.request('/api/preview', {'capture_id': capture['id'], 'state': fuzzy_state})
        self.assertTrue(fuzzy['found'])
        cropped = self.request('/api/crop', {'capture_id': capture['id'], 'asset_id': 'confirm', 'box': exact['bbox']})
        combined_state = {**state, 'recognition': {'type': 'combined', 'operator': 'and',
                          'image': {'type': 'image', 'asset': cropped['asset']}, 'text': state['recognition']}}
        combined = self.request('/api/preview', {'capture_id': capture['id'], 'state': combined_state})
        self.assertTrue(combined['found'])
        self.assertIn('未启用 ADB', self.reject('/api/execute', {'state_id': 'chinese', 'serial': 'one'}))

    def test_invalid_images_and_regions(self):
        before = self.request('/api/states')
        self.reject('/api/import', {'png': base64.b64encode(b'not a PNG').decode()})
        capture = self.request('/api/import', {'png': base64.b64encode((self.root / 'good.png').read_bytes()).decode()})
        self.reject('/api/crop', {'capture_id': capture['id'], 'asset_id': 'bad', 'box': [-1, 0, 15, 20]})
        self.reject('/api/crop', {'capture_id': capture['id'], 'asset_id': 'bad', 'box': [10, 10, 10, 20]})
        self.assertEqual(self.request('/api/states'), before)


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append({'case_id': CASE_IDS[test._testMethodName], 'status': '通过', 'test': test._testMethodName})

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.cases.append({'case_id': CASE_IDS[test._testMethodName], 'status': '失败', 'test': test._testMethodName})

    def addError(self, test, error):
        super().addError(test, error)
        self.cases.append({'case_id': CASE_IDS[test._testMethodName], 'status': '失败', 'test': test._testMethodName})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    OUTPUT = args.artifacts.resolve()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EvidenceApiTests)
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    (OUTPUT / 'cases.json').write_text(json.dumps(result.cases, ensure_ascii=False, indent=2), encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())
