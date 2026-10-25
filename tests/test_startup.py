import argparse
import socket
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.start import build_frontend, install_python, validate_python, validate_ocr_platform, check_port, server_command, run_server, main


class StartupTests(unittest.TestCase):
    def test_macos_ocr_wheel_requirements(self):
        validate_ocr_platform('Darwin', 'arm64', '14.0')
        validate_ocr_platform('Darwin', 'arm64', '15.7.1')
        validate_ocr_platform('Darwin', 'x86_64', '14.0')
        validate_ocr_platform('Linux', 'x86_64', '')
        validate_ocr_platform('Windows', 'AMD64', '')
        with self.assertRaisesRegex(RuntimeError, 'architecture'):
            validate_ocr_platform('Darwin', 'unknown', '15.0')
        with self.assertRaisesRegex(RuntimeError, 'macOS 14\\+'):
            validate_ocr_platform('Darwin', 'arm64', '13.7')
        with self.assertRaisesRegex(RuntimeError, 'macOS 14\\+'):
            validate_ocr_platform('Darwin', 'x86_64', '13.7')

    def test_intel_macos_selects_python_313_separate_environment_and_lock(self):
        previous = Path.cwd()
        try:
            with patch('scripts.start.platform.system', return_value='Darwin'), \
                 patch('scripts.start.platform.machine', return_value='x86_64'), \
                 patch('scripts.start.platform.mac_ver', return_value=('15.0', (), '')), \
                 patch('scripts.start.sys.version_info', (3, 13, 0)), \
                 patch('scripts.start.run'), \
                 patch('scripts.start.install_python') as install, \
                 patch('scripts.start.build_frontend'), \
                 patch('scripts.start.run_server') as server:
                self.assertEqual(main(['--no-adb', '--setup-only']), 0)
                self.assertTrue(install.call_args.kwargs['intel_macos'])
                self.assertFalse(install.call_args.kwargs['platform_only'])
                self.assertEqual(install.call_args.args[1].parent.parent.name, '.venv-intel')
                server.assert_not_called()
                self.assertEqual(main(['--platform-only', '--setup-only']), 0)
                self.assertTrue(install.call_args.kwargs['platform_only'])
        finally:
            os.chdir(previous)

    def test_intel_python_version_and_dependency_cache(self):
        validate_python((3, 13), 64, False, intel_macos=True)
        with self.assertRaisesRegex(RuntimeError, '3.13'):
            validate_python((3, 14), 64, False, intel_macos=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.venv-intel').mkdir()
            (root / 'requirements-macos-intel.txt').write_text('onnxruntime==1.20.1')
            with patch('scripts.start.run') as run:
                install_python(root, 'python3.13', intel_macos=True)
                self.assertEqual(run.call_args_list[0].args[0][-1].name, 'requirements-macos-intel.txt')
            self.assertTrue((root / '.venv-intel/startup-requirements.sha256').exists())
            self.assertFalse((root / '.venv/startup-requirements.sha256').exists())

    @unittest.skipIf(os.name == 'nt', 'POSIX shell launcher')
    def test_intel_shell_launcher_ignores_old_314_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'start.sh').write_text((Path(__file__).resolve().parents[1] / 'start.sh').read_text())
            (root / 'bin').mkdir()
            (root / 'bin/dirname').symlink_to(shutil.which('dirname'))
            (root / '.venv/bin').mkdir(parents=True)
            scripts = {
                'bin/uname': '#!/bin/sh\nif [ "$1" = -s ]; then echo Darwin; else echo x86_64; fi\n',
                'bin/python3.13': '#!/bin/sh\nprintf "%s\\n" "$@" > "$WORKBENCH_ARG_LOG"\n',
                '.venv/bin/python': '#!/bin/sh\nexit 91\n',
            }
            for name, text in scripts.items():
                (root / name).write_text(text)
                (root / name).chmod(0o755)
            env = dict(os.environ, PATH=str(root / 'bin'), WORKBENCH_ARG_LOG=str(root / 'args'))
            result = subprocess.run(['/bin/bash', str(root / 'start.sh'), '--no-adb'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / 'args').read_text().splitlines(), ['scripts/start.py', '--no-adb'])
            (root / 'bin/python3.13').unlink()
            result = subprocess.run(['/bin/bash', str(root / 'start.sh')], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Python 3.13', result.stderr)

    def test_no_adb_mode_keeps_ocr_and_full_dependencies_available(self):
        previous = Path.cwd()
        try:
            with patch('scripts.start.find_adb') as adb, \
                 patch('scripts.start.run'), \
                 patch('scripts.start.check_port'), \
                 patch('scripts.start.install_python') as install, \
                 patch('scripts.start.build_frontend'), \
                 patch('scripts.start.run_server', return_value=0) as server:
                self.assertEqual(main(['--no-adb']), 0)
                adb.assert_not_called()
                self.assertFalse(install.call_args.kwargs['platform_only'])
                command = server.call_args.args[0]
                self.assertIn('--no-adb', command)
                self.assertNotIn('--no-ocr', command)
        finally:
            os.chdir(previous)
    def test_platform_setup_skips_adb_and_selects_minimal_dependencies(self):
        previous = Path.cwd()
        try:
            with patch('scripts.start.find_adb') as adb, \
                 patch('scripts.start.run'), \
                 patch('scripts.start.install_python') as install, \
                 patch('scripts.start.build_frontend') as build, \
                 patch('scripts.start.run_server') as server:
                self.assertEqual(main(['--platform-only', '--setup-only']), 0)
                adb.assert_not_called()
                self.assertTrue(install.call_args.kwargs['platform_only'])
                build.assert_called_once()
                server.assert_not_called()
        finally:
            os.chdir(previous)

    def test_platform_server_disables_adb_and_ocr(self):
        previous = Path.cwd()
        try:
            with patch('scripts.start.find_adb') as adb, \
                 patch('scripts.start.run'), \
                 patch('scripts.start.check_port'), \
                 patch('scripts.start.install_python'), \
                 patch('scripts.start.build_frontend'), \
                 patch('scripts.start.run_server', return_value=0) as server:
                self.assertEqual(main(['--platform-only', '--port', '8766']), 0)
                adb.assert_not_called()
                command = server.call_args.args[0]
                self.assertIn('--no-adb', command)
                self.assertIn('--no-ocr', command)
                self.assertIn('8766', command)
        finally:
            os.chdir(previous)

    def test_platform_install_uses_only_platform_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.venv').mkdir()
            (root / 'requirements-platform.txt').write_text('numpy==2.5.3\nopencv-python==5.0.0.93\n')
            with patch('scripts.start.run') as run:
                install_python(root, 'python', platform_only=True)
                self.assertEqual(run.call_args_list[0].args[0][-1], root / 'requirements-platform.txt')

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
