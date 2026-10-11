import base64
import json
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

from automation.web import create_server
from automation.state import Store


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name))
        self.server = create_server(self.store, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.stop_runs()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, route, data=None):
        request = Request(self.url + route, data=json.dumps(data).encode() if data is not None else None,
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_health_and_state_roundtrip(self):
        self.assertTrue(self.request('/api/health')['python_bits'] == 64)
        data = {'id': 'done', 'recognition': {'type': 'text', 'texts': ['收货成功']}, 'actions': []}
        saved = self.request('/api/states', data)
        self.assertEqual(self.request('/api/states'), [saved])

    def test_text_preview_and_flow_use_same_provider(self):
        calls = []
        def ocr(frame):
            calls.append(frame.shape)
            return [{'text': '收货成功', 'confidence': .98, 'bbox': [10, 10, 70, 30]}]
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server = create_server(self.store, port=0, ocr=ocr)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        image = np.zeros((50, 100, 3), np.uint8)
        cv2.imwrite(str(self.store.captures / 'sample.png'), image)
        data = {'id': 'done', 'role': 'success', 'recognition': {'type': 'text', 'texts': ['收货成功']}}
        self.request('/api/states', data)
        probe = self.request('/api/preview', {'capture_id': 'sample', 'state': data})
        self.assertEqual(probe['bbox'], [10, 10, 70, 30])
        self.assertEqual(probe['text'], '收货成功')
        class Device:
            serial = 'one'
            def capture(self):
                return image
        with patch('automation.web.AdbDevice', return_value=Device()):
            run = self.request('/api/run', {'serial': 'one', 'flow': {'state_ids': ['done'], 'poll_ms': 0}})
            deadline = time.monotonic() + 2
            while True:
                result = self.request('/api/runs/' + run['id'])
                if result['status'] != 'running' or time.monotonic() > deadline:
                    break
                time.sleep(.01)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.request('/api/health')['ocr'], 'ready')

    def test_unconfigured_text_flow_is_rejected_including_conditions(self):
        self.request('/api/states', {'id': 'label', 'recognition': {'type': 'text', 'texts': ['收货成功']}})
        self.request('/api/states', {'id': 'done', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'done.png'}, 'conditions': {'required_states': ['label']}})
        with self.assertRaises(HTTPError) as error:
            self.request('/api/run', {'serial': 'one', 'flow': {'state_ids': ['done']}})
        self.assertIn('OCR', json.load(error.exception)['error'])
        error.exception.close()

    def test_built_frontend_assets_are_served(self):
        import re
        with urlopen(self.url + '/', timeout=5) as response:
            html = response.read().decode()
        files = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
        self.assertTrue(files)
        for file in files:
            with urlopen(self.url + file, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())

    def test_crop_and_preview_without_device(self):
        image = np.random.default_rng(2).integers(0, 255, (80, 100, 3), dtype=np.uint8)
        cv2.imwrite(str(self.store.captures / 'sample.png'), image)
        cropped = self.request('/api/crop', {'capture_id': 'sample', 'asset_id': 'button', 'box': [40, 20, 60, 35]})
        self.assertEqual(cropped['asset'], 'button.png')
        data = {'id': 'button', 'recognition': {'type': 'image', 'asset': 'button.png'}}
        preview = self.request('/api/preview', {'capture_id': 'sample', 'state': data})
        self.assertEqual(preview['bbox'], [40, 20, 60, 35])

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request('/api/crop', {'capture_id': '../outside', 'asset_id': 'button', 'box': [0, 0, 1, 1]})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_run_persists_result_and_evidence(self):
        image = np.random.default_rng(4).integers(0, 255, (80, 100, 3), dtype=np.uint8)
        cv2.imwrite(str(self.store.assets / 'success.png'), image[20:35, 40:60])
        self.request('/api/states', {'id': 'success', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'success.png', 'threshold': .99}})
        class Device:
            serial = 'one'

            def capture(self):
                return image

        with patch('automation.web.AdbDevice', return_value=Device()):
            run = self.request('/api/run', {'serial': 'one', 'flow': {'state_ids': ['success'], 'max_rounds': 2, 'poll_ms': 0}})
            deadline = time.monotonic() + 2
            while True:
                result = self.request('/api/runs/' + run['id'])
                if result['status'] != 'running' or time.monotonic() > deadline:
                    break
                time.sleep(.01)
        self.assertEqual(result['status'], 'passed')
        self.assertTrue((self.store.runs / run['id'] / 'result.json').is_file())
        self.assertTrue((self.store.runs / run['id'] / 'frame-0001.png').is_file())

    def test_flow_save_preserves_all_fields(self):
        self.request('/api/states', {'id': 'done', 'role': 'success', 'recognition': {'type': 'text', 'texts': ['完成']}})
        flow = {'state_ids': ['done'], 'max_rounds': 20, 'timeout_seconds': 30, 'poll_ms': 150, 'completion_count': 2, 'dry_run': True}
        self.request('/api/flow', flow)
        self.assertEqual(self.request('/api/flow'), flow)

    def test_import_png_and_reject_non_image(self):
        image = np.zeros((30, 40, 3), np.uint8)
        encoded = base64.b64encode(cv2.imencode('.png', image)[1].tobytes()).decode()
        result = self.request('/api/import', {'png': encoded})
        self.assertEqual((result['width'], result['height']), (40, 30))
        self.assertTrue((self.store.captures / (result['id'] + '.png')).is_file())
        with self.assertRaises(HTTPError) as error:
            self.request('/api/import', {'png': base64.b64encode(b'bad').decode()})
        error.exception.close()

    def test_failed_config_write_releases_device(self):
        self.request('/api/states', {'id': 'success', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'success.png'}})
        write = Path.write_text
        def fail_config(path, *args, **kwargs):
            if path.name == 'config.json':
                raise OSError('disk full')
            return write(path, *args, **kwargs)
        body = {'serial': 'one', 'flow': {'state_ids': ['success']}}
        with patch.object(Path, 'write_text', fail_config):
            for _ in range(2):
                with self.assertRaises(HTTPError) as error:
                    self.request('/api/run', body)
                reason = json.load(error.exception)['error']
                error.exception.close()
                self.assertIn('disk full', reason)

    def test_screenshot_write_failure_is_error(self):
        image = np.random.default_rng(5).integers(0, 255, (20, 30, 3), dtype=np.uint8)
        self.request('/api/states', {'id': 'success', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'success.png'}})
        class Device:
            serial = 'one'
            def capture(self):
                return image
        with patch('automation.web.AdbDevice', return_value=Device()), patch('automation.web.cv2.imwrite', return_value=False):
            run = self.request('/api/run', {'serial': 'one', 'flow': {'state_ids': ['success']}})
            deadline = time.monotonic() + 2
            while True:
                result = self.request('/api/runs/' + run['id'])
                if result['status'] != 'running' or time.monotonic() > deadline:
                    break
                time.sleep(.01)
        self.assertEqual(result['status'], 'error')
        self.assertIn('截图', result['reason'])

    def test_serial_lock_uses_normalized_identity(self):
        entered, release = threading.Event(), threading.Event()
        self.request('/api/states', {'id': 'success', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'success.png'}})
        class Device:
            def __init__(self, serial, **kwargs):
                self.serial = serial.strip()
            def capture(self):
                entered.set()
                release.wait(2)
                raise RuntimeError('end test')
        with patch('automation.web.AdbDevice', Device):
            run = self.request('/api/run', {'serial': ' one ', 'flow': {'state_ids': ['success']}})
            self.assertTrue(entered.wait(1))
            try:
                with self.assertRaises(HTTPError) as error:
                    self.request('/api/capture', {'serial': 'one'})
                self.assertIn('执行流程', json.load(error.exception)['error'])
                error.exception.close()
            finally:
                release.set()
                self.server.stop_runs()

    def test_result_write_failure_does_not_leave_running(self):
        image = np.random.default_rng(6).integers(0, 255, (20, 30, 3), dtype=np.uint8)
        cv2.imwrite(str(self.store.assets / 'success.png'), image[2:12, 5:20])
        self.request('/api/states', {'id': 'success', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'success.png'}})
        class Device:
            serial = 'one'
            def capture(self):
                return image
        write = Path.write_text
        def fail_result(path, *args, **kwargs):
            if path.name == 'result.json':
                raise OSError('disk full')
            return write(path, *args, **kwargs)
        with patch('automation.web.AdbDevice', return_value=Device()), patch.object(Path, 'write_text', fail_result):
            run = self.request('/api/run', {'serial': 'one', 'flow': {'state_ids': ['success']}})
            self.server.stop_runs()
            result = self.request('/api/runs/' + run['id'])
        self.assertEqual(result['status'], 'error')
        self.assertIn('结果写入失败', result['reason'])


if __name__ == '__main__':
    unittest.main()
