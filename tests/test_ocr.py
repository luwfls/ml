import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from automation.ocr import RapidOcrProvider


class OcrTests(unittest.TestCase):
    def test_polygon_is_converted_to_original_pixel_rectangle(self):
        output = SimpleNamespace(boxes=np.array([[[10.2, 3.7], [30.8, 5], [29, 15.1], [9, 14]]]),
                                 txts=('收货成功',), scores=(.97,))
        with patch('rapidocr.RapidOCR') as factory:
            factory.return_value.return_value = output
            provider = RapidOcrProvider()
            items = provider(np.zeros((40, 80, 3), np.uint8))
        self.assertEqual(items[0]['bbox'], [9, 3, 31, 16])
        self.assertEqual(items[0]['text'], '收货成功')
        self.assertEqual(items[0]['confidence'], .97)
        self.assertTrue(factory.call_args.kwargs['params']['Det.model_path'].endswith('PP-OCRv6_det_small.onnx'))

    def test_concurrent_calls_do_not_share_mutable_engine_state(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        active, maximum = 0, 0
        def infer(frame):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            time.sleep(.02)
            active -= 1
            return SimpleNamespace(boxes=None, txts=None, scores=None)
        with patch('rapidocr.RapidOCR') as factory:
            factory.return_value.side_effect = infer
            provider = RapidOcrProvider()
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(provider, [np.zeros((40, 80, 3), np.uint8)] * 4))
        self.assertEqual(maximum, 1)

    def test_empty_result_is_no_text(self):
        with patch('rapidocr.RapidOCR') as factory:
            factory.return_value.return_value = SimpleNamespace(boxes=None, txts=None, scores=None)
            self.assertEqual(RapidOcrProvider()(np.zeros((40, 80, 3), np.uint8)), [])

    def test_malformed_result_is_error(self):
        with patch('rapidocr.RapidOCR') as factory:
            factory.return_value.return_value = SimpleNamespace(boxes=[[[0, 0]]], txts=['x'], scores=[])
            with self.assertRaises(ValueError):
                RapidOcrProvider()(np.zeros((40, 80, 3), np.uint8))

    def test_local_config_resolves_relative_paths_and_forces_cpu(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['det.onnx', 'cls.onnx', 'rec.onnx']:
                (root / name).write_bytes(b'model')
            config = root / 'ocr.json'
            config.write_text(json.dumps({'det_model': 'det.onnx', 'cls_model': 'cls.onnx', 'rec_model': 'rec.onnx'}))
            with patch('rapidocr.RapidOCR') as factory, patch('onnxruntime.InferenceSession') as session:
                session.return_value.get_modelmeta.return_value.custom_metadata_map = {'character': '中\n文'}
                RapidOcrProvider(config)
                params = factory.call_args.kwargs['params']
            self.assertEqual(params['Det.model_path'], str(root / 'det.onnx'))
            self.assertFalse(params['EngineConfig.onnxruntime.use_cuda'])
            self.assertEqual(params['Global.text_score'], 0)

    def test_custom_rec_without_embedded_dictionary_requires_local_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['det.onnx', 'cls.onnx', 'rec.onnx']:
                (root / name).write_bytes(b'model')
            config = root / 'ocr.json'
            config.write_text(json.dumps({'det_model': 'det.onnx', 'cls_model': 'cls.onnx', 'rec_model': 'rec.onnx'}))
            with patch('rapidocr.RapidOCR') as factory, patch('onnxruntime.InferenceSession') as session:
                session.return_value.get_modelmeta.return_value.custom_metadata_map = {}
                with self.assertRaisesRegex(ValueError, 'rec_keys'):
                    RapidOcrProvider(config)
                factory.assert_not_called()

    def test_missing_model_or_unknown_config_fails_before_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'ocr.json'
            for data in [{'det_model': 'missing.onnx', 'cls_model': 'missing.onnx', 'rec_model': 'missing.onnx'}, {'typo': 1}]:
                config.write_text(json.dumps(data))
                with patch('rapidocr.RapidOCR') as factory, self.assertRaises(ValueError):
                    RapidOcrProvider(config)
                factory.assert_not_called()

    def test_inference_failure_is_not_no_match(self):
        with patch('rapidocr.RapidOCR') as factory:
            factory.return_value.side_effect = RuntimeError('inference failed')
            with self.assertRaisesRegex(RuntimeError, 'inference failed'):
                RapidOcrProvider()(np.zeros((40, 80, 3), np.uint8))


class RealOcrTests(unittest.TestCase):
    def test_real_cpu_engine_recognizes_chinese_without_network(self):
        import cv2
        frame = cv2.imread(str(Path(__file__).parent / 'fixtures' / 'ocr-ui.png'))
        self.assertIsNotNone(frame)
        with patch('rapidocr.utils.download_file.DownloadFile.run', side_effect=AssertionError('unexpected model download')), \
             patch('requests.sessions.Session.request', side_effect=AssertionError('unexpected network request')):
            provider = RapidOcrProvider()
            items = provider(frame)
        texts = [item['text'] for item in items]
        self.assertIn('收货成功', texts)
        self.assertIn('确认收货', texts)
        self.assertTrue(any('PO123456' in text for text in texts))
        self.assertEqual(provider.engine.text_det.session.session.get_providers(), ['CPUExecutionProvider'])
        for item in items:
            x1, y1, x2, y2 = item['bbox']
            self.assertTrue(0 <= x1 < x2 <= frame.shape[1] and 0 <= y1 < y2 <= frame.shape[0])
        from automation.adb import AdbDevice
        from automation.runner import run_loop
        from automation.state import Store
        from automation.vision import Recognizer
        button = next(item for item in items if item['text'] == '确认收货')
        x1, y1, x2, y2 = button['bbox']
        states = [{'id': 'confirm', 'recognition': {'type': 'text', 'texts': ['确认收货']}, 'actions': [{'type': 'click_match'}]},
                  {'id': 'done', 'role': 'success', 'recognition': {'type': 'text', 'texts': ['另一验收页面']}}]
        png = cv2.imencode('.png', frame)[1].tobytes()
        viewport = b'Viewport INTERNAL: logicalFrame=[0, 0, 640, 280] isActive=[1]'
        outputs = [SimpleNamespace(returncode=0, stdout=raw, stderr=b'') for raw in [png, viewport, b'']]
        with tempfile.TemporaryDirectory() as directory, patch('automation.adb.subprocess.run', side_effect=outputs) as adb:
            result = run_loop(states, {'state_ids': ['confirm', 'done'], 'max_rounds': 1, 'poll_ms': 0},
                              AdbDevice('fixture-device'), Recognizer(Store(Path(directory)), provider))
        self.assertEqual(result['reason'], 'max_rounds')
        command = adb.call_args_list[-1].args[0]
        self.assertEqual(command[:6], ['adb', '-s', 'fixture-device', 'shell', 'input', 'tap'])
        self.assertTrue(x1 <= int(command[6]) < x2)
        self.assertTrue(y1 <= int(command[7]) < y2)
