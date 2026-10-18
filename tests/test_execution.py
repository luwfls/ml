import json
import os
import signal
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from automation.state import Store


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'data')
        self.frame = np.random.default_rng(10).integers(0, 255, (50, 70, 3), dtype=np.uint8)
        cv2.imwrite(str(self.root / 'good.png'), self.frame)
        cv2.imwrite(str(self.root / 'blank.png'), np.zeros_like(self.frame))
        cv2.imwrite(str(self.store.assets / 'done.png'), self.frame[10:25, 20:40])
        self.states = [self.store.save({'id': 'done', 'role': 'success', 'recognition': {'type': 'image', 'asset': 'done.png'}})]
        self.flows = [{'id': 'first', 'name': '第一流程', 'state_ids': ['done'], 'poll_ms': 10},
                      {'id': 'second', 'name': '第二流程', 'state_ids': ['done'], 'poll_ms': 10}]
        adb = self.root / 'adb'
        adb.write_text('#!' + os.sys.executable + '\nimport sys,time,os\nfrom pathlib import Path\n'
                       'serial=sys.argv[2]\n'
                       'if serial=="hung":\n'
                       ' (Path(__file__).parent/"client-pid").write_text(str(os.getpid()))\n'
                       ' time.sleep(6)\n'
                       ' (Path(__file__).parent/"late-action").write_text("sent")\n'
                       'sys.stdout.buffer.write((Path(__file__).parent/("blank.png" if serial=="wait" else "good.png")).read_bytes())\n')
        adb.chmod(0o755)
        self.adb = str(adb)
        self.manager = None

    def tearDown(self):
        if self.manager:
            self.manager.close()
        self.tmp.cleanup()

    def manager_start(self, serials, **kwargs):
        from automation.execution import ExecutionManager
        if not self.manager:
            self.manager = ExecutionManager(self.store, adb=self.adb)
        return self.manager.start_batch(self.flows, self.states, serials, set(serials), **kwargs)

    def until(self, fn, test, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = fn()
            if test(result): return result
            time.sleep(.02)
        self.fail('execution did not reach expected state: ' + str(result))

    def test_spawned_device_processes_execute_flow_sequence_and_snapshot(self):
        batch = self.manager_start(['one', 'two'], task={'id': 'task', 'name': '任务', 'revision': 1})
        self.flows[0]['name'] = 'later edit'
        detail = self.until(lambda: self.manager.batch_detail(batch['batch_id']), lambda r: not r['live'])
        self.assertEqual(detail['status'], 'passed')
        self.assertEqual(len({r['pid'] for r in detail['runs']}), 2)
        self.assertNotIn(os.getpid(), [r['pid'] for r in detail['runs']])
        for run in detail['runs']:
            self.assertEqual([r['flow_id'] for r in run['flow_results']], ['first', 'second'])
            self.assertEqual(run['snapshot']['flows'][0]['name'], '第一流程')
            self.assertTrue((self.store.runs / run['id'] / 'result.json').exists())

    def test_step_waits_for_one_round_and_cancel_releases_device(self):
        batch = self.manager_start(['wait'], mode='step')
        run_id = batch['results'][0]['id']
        detail = self.until(lambda: self.manager.detail(run_id), lambda r: r['status'] == 'waiting')
        self.assertEqual(detail['rounds'], 0)
        self.manager.command(run_id, 'next')
        detail = self.until(lambda: self.manager.detail(run_id), lambda r: r['status'] == 'waiting' and r['rounds'] == 1)
        self.assertEqual(detail['completed_flows'], 0)
        self.manager.command(run_id, 'auto')
        self.until(lambda: self.manager.detail(run_id), lambda r: r['rounds'] > 1)
        self.manager.command(run_id, 'cancel')
        self.assertFalse(self.manager.detail(run_id)['live'])
        self.assertEqual(self.manager.detail(run_id)['status'], 'cancelled')
        retry = self.manager.start_batch(self.flows, self.states, ['wait'], {'wait'}, mode='step')
        self.assertIn('id', retry['results'][0])

    def test_failure_busy_and_duplicate_task_are_isolated(self):
        waiting = self.manager_start(['wait'], task={'id': 'task', 'name': '任务'})
        with self.assertRaisesRegex(ValueError, '运行'):
            self.manager.start_batch(self.flows, self.states, ['one'], {'one'}, task={'id': 'task', 'name': '任务'})
        second = self.manager.start_batch(self.flows, self.states, ['wait', 'one', 'offline'], {'wait', 'one'})
        self.assertIn('error', second['results'][0])
        self.assertIn('id', second['results'][1])
        self.assertIn('error', second['results'][2])
        self.manager.cancel_batch(waiting['batch_id'])
        self.assertFalse(self.manager.batch_detail(waiting['batch_id'])['live'])

    def test_cancel_waiting_and_restart_history(self):
        batch = self.manager_start(['wait'], mode='step')
        self.manager.cancel_batch(batch['batch_id'])
        self.manager.close()
        from automation.execution import ExecutionManager
        self.manager = ExecutionManager(self.store, adb=self.adb)
        detail = self.manager.batch_detail(batch['batch_id'])
        self.assertEqual(detail['status'], 'cancelled')
        self.assertFalse(detail['live'])

    def test_restart_marks_nonterminal_summary_interrupted(self):
        from automation.execution import ExecutionManager
        run_id, batch_id = 'orphan', 'oldbatch'
        directory = self.store.runs / run_id
        directory.mkdir()
        config = {'engine': 'process', 'serial': 'one', 'batch_id': batch_id, 'task': None, 'flows': self.flows}
        self.store.write_json(directory / 'config.json', config)
        self.store.write_json(directory / 'summary.json', {'status': 'running', 'rounds': 5})
        manager = ExecutionManager(self.store, adb=self.adb)
        self.manager = manager
        self.store.write_json(manager.batches / (batch_id + '.json'), {'batch_id': batch_id, 'results': [{'serial': 'one', 'id': run_id}]})
        self.assertEqual(manager.detail(run_id)['status'], 'interrupted')
        self.assertEqual(manager.detail(run_id)['rounds'], 5)
        self.assertEqual(manager.batch_detail(batch_id)['status'], 'interrupted')

    @unittest.skipUnless(hasattr(signal, 'SIGSTOP'), 'requires POSIX process suspension')
    def test_duplicate_next_cannot_queue_an_extra_round(self):
        batch = self.manager_start(['wait'], mode='step')
        run_id = batch['results'][0]['id']
        detail = self.until(lambda: self.manager.detail(run_id), lambda r: r['status'] == 'waiting')
        os.kill(detail['pid'], signal.SIGSTOP)
        try:
            self.manager.command(run_id, 'next')
            with self.assertRaisesRegex(ValueError, '步进'):
                self.manager.command(run_id, 'next')
        finally:
            os.kill(detail['pid'], signal.SIGCONT)
        self.until(lambda: self.manager.detail(run_id), lambda r: r['rounds'] == 1 and r['status'] == 'waiting')
        time.sleep(.1)
        self.assertEqual(self.manager.detail(run_id)['rounds'], 1)

    def test_cancel_reaps_owned_adb_client_before_releasing_device(self):
        batch = self.manager_start(['hung'])
        run_id = batch['results'][0]['id']
        self.until(lambda: (self.root / 'client-pid').exists(), bool)
        client_pid = int((self.root / 'client-pid').read_text())
        self.manager.command(run_id, 'cancel')
        self.assertFalse(self.manager.detail(run_id)['live'])
        with self.assertRaises(ProcessLookupError):
            os.kill(client_pid, 0)
        self.assertFalse((self.root / 'late-action').exists())

    @unittest.skipUnless(hasattr(signal, 'SIGSTOP'), 'requires POSIX process suspension')
    def test_mode_switch_clears_outstanding_step_claim(self):
        batch = self.manager_start(['wait'], mode='step')
        run_id = batch['results'][0]['id']
        detail = self.until(lambda: self.manager.detail(run_id), lambda r: r['status'] == 'waiting')
        os.kill(detail['pid'], signal.SIGSTOP)
        try:
            self.manager.command(run_id, 'next')
            self.manager.command(run_id, 'auto')
            self.manager.command(run_id, 'step')
        finally:
            os.kill(detail['pid'], signal.SIGCONT)
        waiting = self.until(lambda: self.manager.detail(run_id), lambda r: r['status'] == 'waiting')
        self.assertEqual(waiting['rounds'], 0)
        self.manager.command(run_id, 'next')
        self.until(lambda: self.manager.detail(run_id), lambda r: r['rounds'] == 1 and r['status'] == 'waiting')
