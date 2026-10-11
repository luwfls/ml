import tempfile
import unittest
from pathlib import Path
from automation.state import Store, validate_state


def state(id, **values):
    return {'id': id, 'recognition': {'type': 'image', 'asset': id + '.png'}, **values}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def test_group_copy_remaps_conditions_and_copies_assets(self):
        self.store.assets.joinpath('a.png').write_bytes(b'original')
        self.store.assets.joinpath('b.png').write_bytes(b'other')
        self.store.save(state('a', group='old', conditions={'required_states': ['b']}))
        self.store.save(state('b', group='old'))
        self.store.update_group('copy', 'old', 'new')
        copied = [s for s in self.store.load_all() if s['group'] == 'new']
        self.assertEqual(len(copied), 2)
        a = next(s for s in copied if s['conditions']['required_states'])
        b = next(s for s in copied if not s['conditions']['required_states'])
        self.assertEqual(a['conditions']['required_states'], [b['id']])
        self.assertNotEqual(a['recognition']['asset'], 'a.png')
        self.store.assets.joinpath('a.png').write_bytes(b'changed')
        self.assertEqual(self.store.assets.joinpath(a['recognition']['asset']).read_bytes(), b'original')
        self.store.update_group('rename', 'new', 'renamed')
        self.assertIn({'name': 'renamed'}, Store(self.tmp.name).list_groups())
        with self.assertRaises(ValueError): self.store.update_group('delete', 'renamed')
    def test_flow_migration_restart_and_reference_safe_delete(self):
        import json
        self.store.save(state('done', role='success'))
        legacy = {'state_ids': ['done'], 'poll_ms': 2}
        self.store.root.joinpath('flow.json').write_text(json.dumps(legacy))
        self.assertEqual(self.store.list_flows()[0]['id'], 'default')
        self.store.save_flow({'id': 'second', 'name': 'two', 'state_ids': ['done']})
        self.assertEqual(len(Store(self.tmp.name).list_flows()), 2)
        self.assertEqual(json.loads(self.store.root.joinpath('flow.json').read_text()), legacy)
        with self.assertRaises(ValueError): self.store.delete_state('done')
    def test_group_failure_rolls_back_states_and_assets(self):
        from unittest.mock import patch
        self.store.assets.joinpath('a.png').write_bytes(b'a')
        self.store.assets.joinpath('b.png').write_bytes(b'b')
        self.store.save(state('a', group='old'))
        self.store.save(state('b', group='old'))
        before = self.store.load_all()
        original = self.store.save
        def fail_second(value):
            if value['group'] == 'new' and value['recognition']['asset'] != 'a.png':
                fail_second.calls += 1
                if fail_second.calls == 2: raise OSError('disk full')
            return original(value)
        fail_second.calls = 0
        with patch.object(self.store, 'save', fail_second):
            with self.assertRaises(OSError): self.store.update_group('copy', 'old', 'new')
        self.assertEqual(self.store.load_all(), before)
        self.assertEqual({p.name for p in self.store.assets.iterdir()}, {'a.png', 'b.png'})
        with patch.object(self.store, 'write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.store.update_group('rename', 'old', 'new')
        self.assertEqual(self.store.load_all(), before)

    def test_click_target_validation(self):
        for target in [[0, 0, 0, 1], [0, 0, float('nan'), 1], [0, 0, 101, 1]]:
            with self.assertRaises(ValueError): validate_state(state('a', actions=[{'type': 'click_match', 'target_box': target}]))

class ClickTests(unittest.TestCase):
    def test_relative_click_is_mapped_to_original_match_and_rejects_bounds(self):
        import numpy as np
        from unittest.mock import patch
        from automation.adb import AdbDevice
        device = AdbDevice('one')
        frame = np.zeros((100, 200, 3), np.uint8)
        match = {'found': True, 'bbox': [20, 10, 60, 30]}
        viewport = b'Viewport INTERNAL: logicalFrame=[0, 0, 200, 100] isActive=[1]'
        with patch.object(device, 'run', return_value=viewport) as run:
            device.execute({'type': 'click_match', 'target_box': [1, 1, 2, 2]}, match, frame)
            run.assert_called_with('shell', 'input', 'tap', 80, 40)
            with self.assertRaises(RuntimeError):
                device.execute({'type': 'click_match', 'target_box': [10, 10, 11, 11]}, match, frame)
