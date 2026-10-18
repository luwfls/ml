import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import cv2
from automation.state import Store, validate_state
from automation.vision import Recognizer
from automation.adb import AdbDevice


def state(**values):
    return {'id': 'sample', 'recognition': {'type': 'text', 'texts': ['OK']}, **values}


class ConfirmedStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)

    def test_ids_names_priority_and_copies(self):
        saved = self.store.save({'name': 'new', 'recognition': {'type': 'text', 'texts': ['OK']}})
        self.assertEqual(saved['priority'], 1.0)
        self.assertNotEqual(self.store.copy_state(saved['id'])['id'], saved['id'])
        for values in [{'name': ''}, {'name': 2}, {'priority': 1.234}]:
            with self.assertRaises(ValueError): validate_state(state(**values))
        terminal = self.store.save(state(role='success'))
        flow = self.store.save_flow({'name': 'flow', 'state_ids': [terminal['id']]})
        self.assertNotEqual(self.store.copy_flow(flow['id'])['id'], flow['id'])
        with self.assertRaises(ValueError): self.store.save_flow({**flow, 'name': ' '})

    def test_tasks_order_revisions_legacy_and_reference_guard(self):
        self.store.save(state(role='success'))
        for fid in ['a', 'b']:
            self.store.save_flow({'id': fid, 'state_ids': ['sample']})
        task = self.store.save_task({'name': 'task', 'flow_ids': ['a', 'b', 'a']})
        self.assertEqual(task['flow_id'], 'a')
        self.assertEqual(task['revision'], 1)
        self.assertEqual(self.store.save_task(task)['revision'], 2)
        with self.assertRaises(ValueError): self.store.delete_flow('b')
        for ids in [[], ['missing']]:
            with self.assertRaises(ValueError): self.store.save_task({'name': 'bad', 'flow_ids': ids})
        self.store.write_json(self.store.tasks / 'old.json', {'id': 'old', 'name': 'old', 'flow_id': 'b', 'extra': 7})
        old = next(t for t in self.store.list_tasks() if t['id'] == 'old')
        self.assertEqual((old['flow_ids'], old['revision'], old['extra']), (['b'], 1, 7))

    def test_combined_regions_components_ocr_and_asset_copy(self):
        rng = np.random.default_rng(7)
        template = rng.integers(0, 255, (10, 10, 3), dtype=np.uint8)
        cv2.imwrite(str(self.store.assets / 'button.png'), template)
        frame = np.zeros((100, 100, 3), np.uint8)
        frame[10:20, 10:20] = template
        combined = state(group='old', recognition={'type': 'combined', 'operator': 'and',
            'image': {'asset': 'button.png', 'region': [0, 0, .5, .5]},
            'text': {'texts': ['No', 'OK'], 'region': [.5, .5, 1, 1]}})
        ocr = unittest.mock.Mock(return_value=[{'bbox': [60, 60, 80, 70], 'text': 'OK', 'confidence': .99}])
        recognizer = Recognizer(self.store, ocr)
        result = recognizer.match(frame, combined)
        self.assertTrue(result['found'])
        self.assertEqual(result['bbox'], [10, 10, 20, 20])
        self.assertTrue(result['components']['text']['found'])
        recognizer.match(frame, state(id='another'))
        ocr.assert_called_once()
        combined['recognition']['image']['region'] = [.5, 0, 1, .5]
        combined['id'] = 'or_state'
        combined['recognition']['operator'] = 'or'
        fallback = recognizer.match(frame, combined)
        self.assertTrue(fallback['found'])
        self.assertEqual(fallback['bbox'], [60, 60, 80, 70])
        saved = self.store.save(combined)
        copied = self.store.copy_state(saved['id'])
        self.assertNotEqual(copied['recognition']['image']['asset'], 'button.png')
        self.store.update_group('copy', 'old', 'new')
        for item in self.store.load_all():
            self.assertTrue((self.store.assets / item['recognition']['image']['asset']).exists())

    def test_combined_boolean_matching_and_selected_ambiguity(self):
        frame = np.zeros((20, 20, 3), np.uint8)
        recognition = {'type': 'combined', 'operator': 'and', 'image': {'asset': 'a.png'}, 'text': {'texts': ['OK']}}
        image = {'found': True, 'bbox': [1, 1, 5, 5], 'score': 1, 'ambiguous': True}
        text = {'found': False, 'bbox': None, 'score': 0, 'ambiguous': False}
        recognizer = Recognizer(self.store)
        with patch.object(recognizer, '_match_component', side_effect=[image, text]):
            result = recognizer.match(frame, state(recognition=recognition))
        self.assertFalse(result['found'])
        self.assertTrue(result['ambiguous'])
        recognition['operator'] = 'or'
        with patch.object(recognizer, '_match_component', side_effect=[image, text]):
            result = recognizer.match(frame, state(id='or', recognition=recognition))
        self.assertTrue(result['found'])
        self.assertTrue(result['ambiguous'])
        for changes in [{'operator': 'xor'}, {'image': None}, {'text': {'texts': []}}, {'text': {'texts': ['OK'], 'region': [0, 0, 0, 1]}}]:
            with self.assertRaises(ValueError): validate_state(state(recognition={**recognition, **changes}))

    def test_actions_validation_and_execution(self):
        for action in [{'type': 'key', 'key': 'A'}, {'type': 'key', 'key': 'space'}, {'type': 'swipe', 'direction': 'left'}, {'type': 'click_match', 'click_region': [0, .1, 1, .8]}]:
            validate_state(state(actions=[action]))
        with self.assertRaises(ValueError): validate_state(state(actions=[{'type': 'click_match', 'click_region': [0, 0, 2, 1]}]))
        device = AdbDevice('one')
        frame = np.zeros((100, 200, 3), np.uint8)
        viewport = b'Viewport INTERNAL: logicalFrame=[0, 0, 200, 100] isActive=[1]'
        match = {'found': True, 'bbox': [20, 10, 60, 30]}
        with patch.object(device, 'run', return_value=viewport) as run, patch('automation.adb.random.randrange', side_effect=lambda a,b: a):
            device.execute({'type': 'click_match', 'click_region': [.5, .5, 1, 1]}, match, frame)
            run.assert_called_with('shell', 'input', 'tap', 100, 50)
            device.execute({'type': 'click_match'}, match, frame)
            run.assert_called_with('shell', 'input', 'tap', 20, 10)
            device.execute({'type': 'swipe', 'direction': 'up'}, match, frame)
            run.assert_called_with('shell', 'input', 'swipe', 100, 80, 100, 20, 300)
            device.execute({'type': 'key', 'key': 'a'}, match, frame)
            run.assert_called_with('shell', 'input', 'keyevent', 29)
            device.execute({'type': 'key', 'key': 'Z'}, match, frame)
            run.assert_called_with('shell', 'input', 'keyevent', 54)
            device.execute({'type': 'key', 'key': 'space'}, match, frame)
            run.assert_called_with('shell', 'input', 'keyevent', 62)
            device.execute({'type': 'swipe', 'points': [0, 1, .5, .5]}, match, frame)
            run.assert_called_with('shell', 'input', 'swipe', 0, 99, 100, 50, 300)

    def test_legacy_client_can_change_first_flow_after_roundtrip(self):
        self.store.save(state(role='success'))
        for fid in ['a', 'b']:
            self.store.save_flow({'id': fid, 'state_ids': ['sample']})
        original = self.store.save_task({'name': 'old client', 'flow_id': 'a'})
        changed = self.store.save_task({**original, 'flow_id': 'b'})
        self.assertEqual(changed['flow_ids'], ['b'])
        changed_again = self.store.save_task({**changed, 'flow_ids': ['a', 'b']})
        self.assertEqual(changed_again['flow_ids'], ['a', 'b'])
