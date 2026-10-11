import argparse
import socket
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.start import build_frontend, install_python, validate_python, check_port, server_command, run_server


class StartupTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX signal delivery; Windows console requires real-machine validation')
    def test_interrupt_waits_for_real_backend_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'cleanup'
            ready = Path(directory) / 'ready'
            code = (
                'import signal,time,pathlib,sys\n'
                'def stop(*args):\n'
                ' time.sleep(0.5)\n'
                ' pathlib.Path(sys.argv[1]).write_text("saved")\n'
                ' raise SystemExit(0)\n'
                'signal.signal(signal.SIGINT,stop)\n'
                'pathlib.Path(sys.argv[2]).write_text("ready")\n'
                'time.sleep(30)\n'
            )
            process = subprocess.Popen([sys.executable, '-c', code, str(marker), str(ready)])
            import time
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            wait = process.wait
            def interrupt(*args, **kwargs):
                process.send_signal(signal.SIGINT)
                process.wait = wait
                raise KeyboardInterrupt
            process.wait = interrupt
            with patch('scripts.start.subprocess.Popen', return_value=process):
                self.assertEqual(run_server(['backend']), 0)
            self.assertEqual(marker.read_text(), 'saved')

    def test_wrong_python_is_rejected_before_install(self):
        for version, bits in [((3, 12), 64), ((3, 14), 32)]:
            with self.assertRaisesRegex(RuntimeError, '3.14.*64'):
                validate_python(version, bits, False)
        validate_python((3, 14), 64, False)
        with self.assertRaisesRegex(RuntimeError, 'free-threaded'):
            validate_python((3, 14), 64, True)

    def test_python_install_cached_but_lock_change_installs_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.venv').mkdir()
            requirements = root / 'requirements-tested.txt'
            requirements.write_text('rapidocr==3.9.2')
            with patch('scripts.start.run') as run:
                install_python(root, 'python with spaces.exe')
                first = run.call_count
                install_python(root, 'python with spaces.exe')
                self.assertEqual(run.call_count, first + 1)  # pip check only
                requirements.write_text('rapidocr==3.9.3')
                install_python(root, 'python with spaces.exe')
                self.assertGreater(run.call_count, first + 2)

    def test_failed_install_does_not_mark_environment_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.venv').mkdir()
            (root / 'requirements-tested.txt').write_text('rapidocr==3.9.2')
            with patch('scripts.start.run', side_effect=subprocess.CalledProcessError(1, ['pip'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    install_python(root, 'python.exe')
            self.assertFalse((root / '.venv' / 'startup-requirements.sha256').exists())

    def test_frontend_skips_cached_build_and_rebuilds_on_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'frontend').mkdir()
            for file in ['package.json', 'package-lock.json', 'vite.config.js', 'index.html', 'frontend/main.js']:
                (root / file).write_text('old')
            calls = []
            def build(arguments, **kwargs):
                calls.append(arguments)
                if arguments[-2:] == ['run', 'build']:
                    path = root / 'dist' / 'workbench'
                    path.mkdir(parents=True, exist_ok=True)
                    (path / 'index.html').write_text('built')
            with patch('scripts.start.run', side_effect=build), patch('scripts.start.node_npm', return_value=['node.exe', 'npm-cli.js']):
                build_frontend(root)
                self.assertEqual(len(calls), 2)
                build_frontend(root)
                self.assertEqual(len(calls), 2)
                (root / 'frontend' / 'main.js').write_text('new')
                build_frontend(root)
                self.assertEqual(len(calls), 4)

    def test_failed_build_does_not_mark_frontend_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'frontend').mkdir()
            for file in ['package.json', 'package-lock.json', 'vite.config.js', 'index.html']:
                (root / file).write_text('source')
            with patch('scripts.start.node_npm', return_value=['node.exe', 'npm-cli.js']), \
                 patch('scripts.start.run', side_effect=subprocess.CalledProcessError(1, ['npm'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    build_frontend(root)
            self.assertFalse((root / 'dist' / 'workbench' / 'startup-build.sha256').exists())

    def test_occupied_port_is_reported(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            with self.assertRaisesRegex(RuntimeError, 'port'):
                check_port(server.getsockname()[1])

    def test_paths_with_spaces_are_passed_as_separate_arguments(self):
        args = argparse.Namespace(port=8766, no_ocr=False, ocr_config=Path('C:/Test Machine/ocr.json'))
        command = server_command('C:/Test Machine/python.exe', 'C:/Android Tools/adb.exe', args)
        self.assertIn('C:/Android Tools/adb.exe', command)
        self.assertEqual(command[-2:], ['--ocr-config', 'C:/Test Machine/ocr.json'])
