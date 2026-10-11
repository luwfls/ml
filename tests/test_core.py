import copy
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from automation.adb import AdbDevice
from automation.state import Store, validate_state
from automation.vision import Recognizer, match_text
from automation.runner import run_loop


def state(name='button', role='normal', actions=None):
    return {'id': name, 'name': name, 'role': role, 'priority': 0,
            'recognition': {'type': 'image', 'asset': 'button.png', 'threshold': .9},
            'actions': [] if actions is None else actions,
            'conditions': {'required_states': [], 'excluded_states': []}}


class StateTests(unittest.TestCase):
    def test_empty_actions_remain_empty(self):
        self.assertEqual(validate_state(state())['actions'], [])

    def test_recognition_is_exclusive(self):
        data = state()
        data['recognition']['texts'] = ['成功']
        with self.assertRaises(ValueError):
            validate_state(data)

    def test_short_fuzzy_text_is_rejected(self):
        data = state()
        data['recognition'] = {'type': 'text', 'texts': ['好'], 'mode': 'fuzzy'}
        with self.assertRaises(ValueError):
            validate_state(data)

    def test_multiple_inputs_and_wait_before_click_are_rejected(self):
        for actions in [[{'type': 'key', 'key': 'back'}, {'type': 'click_match'}],
                        [{'type': 'wait', 'ms': 500}, {'type': 'click_match'}]]:
            with self.assertRaises(ValueError):
                validate_state(state(actions=actions))

    def test_store_rejects_path_escape_and_preserves_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            data = state()
            data['recognition']['scales'] = [.8, 1.0]
            store.save(data)
            self.assertEqual(store.load_all()[0], validate_state(data))
            data['id'] = '../outside'
            with self.assertRaises(ValueError):
                store.save(data)

    def test_broken_json_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            (store.states / 'broken.json').write_text('{', encoding='utf-8')
            with self.assertRaises(ValueError):
                store.load_all()


class VisionTests(unittest.TestCase):
    def test_text_variants_and_fuzzy_score(self):
        self.assertEqual(match_text('收货完成', ['收货成功', '收货完成'], 'exact'), 1)
        self.assertEqual(match_text('收货成攻', ['收货成功'], 'fuzzy'), .75)
        self.assertLess(match_text('收货失败', ['收货成功'], 'fuzzy'), .85)
        self.assertEqual(match_text('１２３', ['123'], 'exact'), 1)
        self.assertEqual(match_text('123.00', ['12300'], 'exact'), 0)

    def test_image_match_and_original_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            image = np.random.default_rng(1).integers(0, 255, (80, 100, 3), dtype=np.uint8)
            cv2.imwrite(str(store.assets / 'button.png'), image[20:35, 40:60])
            result = Recognizer(store).match(image, state())
            self.assertTrue(result['found'])
            self.assertEqual(result['bbox'], [40, 20, 60, 35])

    def test_ocr_runs_once_per_frame_and_ambiguity_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def ocr(image):
                calls.append(1)
                return [{'text': '收货成功', 'confidence': .99, 'bbox': [1, 1, 20, 10]},
                        {'text': '收货成功', 'confidence': .99, 'bbox': [21, 1, 40, 10]}]
            matcher = Recognizer(Store(Path(directory)), ocr=ocr)
            data = state()
            data['recognition'] = {'type': 'text', 'texts': ['收货成功'], 'mode': 'exact'}
            frame = np.zeros((50, 50, 3), np.uint8)
            matcher.begin(frame)
            self.assertTrue(matcher.match(frame, data)['ambiguous'])
            matcher.match(frame, data)
            self.assertEqual(len(calls), 1)
            matcher.begin(frame.copy())
            matcher.match(frame, data)
            self.assertEqual(len(calls), 2)

    def test_repeated_image_buttons_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            template = np.random.default_rng(3).integers(0, 255, (10, 15, 3), dtype=np.uint8)
            image = np.zeros((60, 100, 3), np.uint8)
            image[5:15, 5:20] = template
            image[30:40, 60:75] = template
            cv2.imwrite(str(store.assets / 'button.png'), template)
            result = Recognizer(store).match(image, state())
            self.assertTrue(result['found'])
            self.assertTrue(result['ambiguous'])

    def test_missing_ocr_is_error_not_no_match(self):
        with tempfile.TemporaryDirectory() as directory:
            data = state()
            data['recognition'] = {'type': 'text', 'texts': ['收货成功']}
            with self.assertRaises(RuntimeError):
                Recognizer(Store(Path(directory))).match(np.zeros((10, 10, 3), np.uint8), data)


class AdbTests(unittest.TestCase):
    def test_capture_keeps_binary_and_selects_serial(self):
        image = np.zeros((20, 30, 3), np.uint8)
        png = cv2.imencode('.png', image)[1].tobytes()
        with patch('automation.adb.subprocess.run', return_value=subprocess.CompletedProcess([], 0, png, b'')) as command:
            frame = AdbDevice('device-one').capture()
        self.assertEqual(frame.shape, image.shape)
        self.assertEqual(command.call_args.args[0], ['adb', '-s', 'device-one', 'exec-out', 'screencap', '-p'])
        self.assertNotIn('shell', command.call_args.kwargs)

    def test_invalid_png_and_missing_serial_fail(self):
        with self.assertRaises(ValueError):
            AdbDevice('')
        with patch('automation.adb.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'not png', b'')):
            with self.assertRaises(RuntimeError):
                AdbDevice('one').capture()


class Device:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.actions = []

    def capture(self):
        return next(self.frames)

    def execute(self, action, match, frame):
        self.actions.append(action)


class Matcher:
    def begin(self, frame):
        pass

    def match(self, frame, data):
        return {'found': data['id'] in frame, 'bbox': [0, 0, 1, 1], 'ambiguous': False}


def flow(**overrides):
    return {'state_ids': ['button', 'success'], 'max_rounds': 4,
            'timeout_seconds': 2, 'poll_ms': 0, 'completion_count': 1, **overrides}


class RunnerTests(unittest.TestCase):
    def test_static_success_page_is_counted_once(self):
        device = Device([{'success'}] * 4)
        result = run_loop([state(), state('success', 'success')], flow(completion_count=2), device, Matcher())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['success_count'], 1)

    def test_success_leave_and_reenter_counts_again(self):
        device = Device([{'success'}, set(), {'success'}])
        result = run_loop([state(), state('success', 'success')], flow(completion_count=2), device, Matcher())
        self.assertEqual(result['status'], 'passed')

    def test_actions_are_not_repeated_on_static_page(self):
        device = Device([{'button'}, {'button'}, {'success'}])
        result = run_loop([state(actions=[{'type': 'click_match'}]), state('success', 'success')], flow(), device, Matcher())
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(len(device.actions), 1)

    def test_no_match_fallback_does_not_click(self):
        device = Device([set()] * 4)
        fallback = state('button', 'fallback', [{'type': 'click_match'}])
        run_loop([fallback, state('success', 'success')], flow(), device, Matcher())
        self.assertEqual(device.actions, [])

    def test_required_condition_allows_lower_priority(self):
        high = state('high', actions=[{'type': 'click_match'}])
        high['priority'] = 10
        high['conditions']['required_states'] = ['missing']
        device = Device([{'high', 'button'}, {'success'}])
        events = []
        run_loop([high, state('missing'), state(actions=[{'type': 'click_match'}]), state('success', 'success')],
                 flow(state_ids=['high', 'button', 'success']), device, Matcher(), emit=events.append)
        self.assertEqual(next(e for e in events if e['type'] == 'action')['state_id'], 'button')

    def test_cancellation_and_dry_run(self):
        cancel = threading.Event()
        cancel.set()
        result = run_loop([state(), state('success', 'success')], flow(), Device([]), Matcher(), cancel=cancel)
        self.assertEqual(result['status'], 'cancelled')
        device = Device([{'button'}, {'success'}])
        run_loop([state(actions=[{'type': 'click_match'}]), state('success', 'success')], flow(dry_run=True), device, Matcher())
        self.assertEqual(device.actions, [])


if __name__ == '__main__':
    unittest.main()
