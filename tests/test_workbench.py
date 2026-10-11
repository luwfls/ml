import threading
import time
import unittest
from automation.runner import run_loop, RunControl
import test_web
from unittest.mock import patch
import cv2
import numpy as np


class WorkbenchTests(unittest.TestCase):
    setUp = test_web.WebTests.setUp
    tearDown = test_web.WebTests.tearDown
    request = test_web.WebTests.request
    def test_group_preview_conditions_and_execute_fresh_frame(self):
        image = np.random.default_rng(12).integers(0, 255, (50, 70, 3), dtype=np.uint8)
        cv2.imwrite(str(self.store.captures / 'sample.png'), image)
        cv2.imwrite(str(self.store.assets / 'a.png'), image[10:20, 20:35])
        self.request('/api/states', {'id': 'a', 'recognition': {'type': 'image', 'asset': 'a.png'}, 'actions': [{'type': 'click_match'}]})
        preview = self.request('/api/preview-group', {'capture_id': 'sample', 'state_ids': ['a']})
        self.assertTrue(preview['matches'][0]['eligible'])
        class Device:
            serial = 'one'
            calls = 0
            actions = []
            def capture(self):
                self.calls += 1
                return image
            def execute(self, action, match, frame): self.actions.append(action)
        device = Device()
        with patch('automation.web.AdbDevice', return_value=device):
            result = self.request('/api/execute', {'serial': 'one', 'state_id': 'a', 'capture_id': 'stale'})
        self.assertTrue(result['executed'])
        self.assertEqual(device.calls, 1)
        self.assertEqual(len(device.actions), 1)
    def test_group_conditions_prevent_execution(self):
        from urllib.error import HTTPError
        image = np.random.default_rng(15).integers(0, 255, (50, 70, 3), dtype=np.uint8)
        other = np.random.default_rng(16).integers(0, 255, (10, 15, 3), dtype=np.uint8)
        cv2.imwrite(str(self.store.captures / 'sample.png'), image)
        cv2.imwrite(str(self.store.assets / 'a.png'), image[10:20, 20:35])
        cv2.imwrite(str(self.store.assets / 'b.png'), other)
        self.request('/api/states', {'id': 'b', 'recognition': {'type': 'image', 'asset': 'b.png', 'threshold': .99}})
        self.request('/api/states', {'id': 'a', 'recognition': {'type': 'image', 'asset': 'a.png'}, 'conditions': {'required_states': ['b']}, 'actions': [{'type': 'click_match'}]})
        probe = self.request('/api/preview-group', {'capture_id': 'sample', 'state_ids': ['a']})['matches'][0]
        self.assertTrue(probe['found'])
        self.assertFalse(probe['eligible'])
        class Device:
            serial = 'one'
            def capture(self): return image
            def execute(self, *args): raise AssertionError('input despite missing condition')
        with patch('automation.web.AdbDevice', return_value=Device()):
            self.assertFalse(self.request('/api/execute', {'serial': 'one', 'state_id': 'a'})['executed'])
        with self.assertRaises(HTTPError) as error:
            self.request('/api/states/delete', {'id': 'b'})
        error.exception.close()

    def test_live_pause_blocks_mutation_and_cancel_finishes(self):
        from urllib.error import HTTPError
        image = np.random.default_rng(18).integers(0, 255, (50, 70, 3), dtype=np.uint8)
        other = np.random.default_rng(19).integers(0, 255, (10, 15, 3), dtype=np.uint8)
        cv2.imwrite(str(self.store.assets / 'b.png'), other)
        self.request('/api/states', {'id': 'b', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'b.png', 'threshold': .99}})
        class Device:
            serial = 'one'
            def capture(self): return image
        with patch('automation.web.AdbDevice', return_value=Device()):
            run = self.request('/api/run', {'serial': 'one', 'flow': {'state_ids': ['b'], 'poll_ms': 30}})
            try:
                self.request('/api/pause', run)
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    detail = self.request('/api/runs/' + run['id'])
                    if detail['status'] == 'paused': break
                    time.sleep(.005)
                self.assertEqual(detail['status'], 'paused')
                self.assertTrue(detail['live'])
                self.request('/api/pause', run)
                self.assertEqual(self.request('/api/runs/' + run['id'])['status'], 'paused')
                with self.assertRaises(HTTPError) as error:
                    self.request('/api/groups', {'action': 'create', 'name': 'blocked'})
                error.exception.close()
                self.request('/api/cancel', run)
                self.server.stop_runs()
                self.assertEqual(self.request('/api/runs/' + run['id'])['status'], 'cancelled')
                with self.assertRaises(HTTPError) as error: self.request('/api/resume', run)
                error.exception.close()
            finally:
                self.request('/api/cancel', run)
                self.server.stop_runs()

    def test_run_restart_retains_evidence_and_metadata(self):
        directory = self.store.runs / 'saved'
        directory.mkdir()
        self.store.write_json(directory / 'config.json', {'serial': 'one', 'flow': {'id': 'flow', 'name': 'named'}})
        self.store.write_json(directory / 'result.json', {'status': 'passed', 'success_count': 2})
        (directory / 'events.jsonl').write_text('{"type":"success","count":2}\n')
        cv2.imwrite(str(directory / 'frame-0001.png'), np.zeros((10, 10, 3), np.uint8))
        result = self.request('/api/runs/saved')
        self.assertEqual(result['flow_name'], 'named')
        self.assertEqual(result['success_count'], 2)
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['frame_url'], '/runs/saved/frame-0001.png')
        self.assertEqual(self.request('/api/runs')[0]['id'], 'saved')
        (directory / 'result.json').unlink()
        self.assertEqual(self.request('/api/runs/saved')['status'], 'interrupted')


class PauseTests(unittest.TestCase):
    def test_pause_freezes_input_excludes_timeout_and_resume_preserves_dedup(self):
        cancel = threading.Event()
        paused = threading.Event()
        acted = threading.Event()
        statuses = []
        def notify(status):
            statuses.append(status)
            if status == 'paused': paused.set()
        control = RunControl(cancel, notify)
        states = [ {'id': 'button', 'recognition': {'type': 'image', 'asset': 'a.png'}, 'actions': [{'type': 'click_match'}]},
                   {'id': 'done', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'b.png'}} ]
        class Device:
            calls = 0
            frames = 0
            def capture(self): self.frames += 1; return None
            def execute(self, action, match, frame): self.calls += 1; acted.set()
        class Matcher:
            def begin(self, frame): pass
            def match(self, frame, state): return {'found': state['id'] == 'button', 'bbox': [0, 0, 1, 1]}
        device = Device()
        result = {}
        thread = threading.Thread(target=lambda: result.update(run_loop(states, {'state_ids': ['button', 'done'], 'timeout_seconds': .15, 'poll_ms': 30}, device, Matcher(), cancel, control=control)))
        thread.start()
        try:
            self.assertTrue(acted.wait(1))
            control.pause()
            self.assertTrue(paused.wait(1))
            captures = device.frames
            time.sleep(.2)
            self.assertEqual(device.calls, 1)
            self.assertEqual(device.frames, captures)
            control.resume()
            time.sleep(.03)
            self.assertTrue(thread.is_alive())
            self.assertEqual(device.calls, 1)
            control.pause()
            paused.clear()
            deadline = time.monotonic() + 1
            while not control.paused and time.monotonic() < deadline: time.sleep(.005)
            cancel.set()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result['status'], 'cancelled')
        finally:
            cancel.set()
            thread.join(2)

    def test_resume_recaptures_before_unexecuted_input(self):
        cancel = threading.Event()
        entered = threading.Event()
        release = threading.Event()
        paused = threading.Event()
        control = RunControl(cancel, lambda status: paused.set() if status == 'paused' else None)
        states = [{'id': 'button', 'recognition': {'type': 'image', 'asset': 'a.png'}, 'actions': [{'type': 'click_match'}]}, {'id': 'done', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'b.png'}}]
        class Device:
            frames = 0
            taps = []
            def capture(self): self.frames += 1; return self.frames
            def execute(self, action, match, frame): self.taps.append((frame, match['bbox'])); cancel.set()
        class Matcher:
            def begin(self, frame): pass
            def match(self, frame, state):
                if frame == 1 and state['id'] == 'button': entered.set(); release.wait(1)
                return {'found': state['id'] == 'button', 'bbox': [frame, 0, frame + 1, 1]}
        device = Device()
        thread = threading.Thread(target=lambda: run_loop(states, {'state_ids': ['button', 'done'], 'poll_ms': 0}, device, Matcher(), cancel, control=control))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            control.pause()
            release.set()
            self.assertTrue(paused.wait(1))
            control.pause()
            control.resume()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(device.taps, [(2, [2, 0, 3, 1])])
        finally:
            release.set()
            cancel.set()
            thread.join(2)
