"""Prepare the project environment and run the workbench in the foreground."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import sysconfig


def run(arguments, **kwargs):
    return subprocess.run([str(arg) for arg in arguments], check=True, **kwargs)


def validate_python(version, bits, free_threaded):
    if tuple(version[:2]) != (3, 14) or bits != 64:
        raise RuntimeError('Install standard Python 3.14 x64 (64-bit), then run this launcher again.')
    if free_threaded:
        raise RuntimeError('Use standard Python, not the free-threaded build; OCR wheels use the standard ABI.')


def fingerprint(root, files):
    digest = hashlib.sha256()
    for file in sorted(files):
        digest.update(file.relative_to(root).as_posix().encode('utf-8') + b'\0')
        digest.update(file.read_bytes())
    return digest.hexdigest()


def cached(marker, value):
    return marker.is_file() and marker.read_text(encoding='ascii').strip() == value


def install_python(root, python, refresh=False):
    requirements = root / 'requirements-tested.txt'
    value = fingerprint(root, [requirements])
    marker = root / '.venv' / 'startup-requirements.sha256'
    if refresh or not cached(marker, value):
        print('Installing locked Python dependencies (first setup requires Internet)...', flush=True)
        run([python, '-m', 'pip', 'install', '-r', requirements])
        run([python, '-m', 'pip', 'check'])
        marker.write_text(value, encoding='ascii')
    else:
        run([python, '-m', 'pip', 'check'])


def node_npm():
    node = shutil.which('node')
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if node and npm:
        npm_path = Path(npm).resolve()
        cli = npm_path.parent / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js' if npm_path.suffix == '.cmd' else npm_path
        if cli.is_file():
            # Run Node directly, avoiding Windows npm.cmd shell quoting.
            return [node, str(cli)]
    raise RuntimeError('Frontend build requires Node.js LTS with npm in PATH. Install it and reopen the launcher.')


def build_frontend(root, refresh=False):
    files = [root / name for name in ['package.json', 'package-lock.json', 'vite.config.js', 'index.html']]
    files += [file for file in (root / 'frontend').rglob('*') if file.is_file()]
    value = fingerprint(root, files)
    output = root / 'dist' / 'workbench'
    marker = output / 'startup-build.sha256'
    if not refresh and (output / 'index.html').is_file() and cached(marker, value):
        print('Using existing frontend build.', flush=True)
        return
    command = node_npm()
    run(command + ['ci'], cwd=root)
    run(command + ['run', 'build'], cwd=root)
    if not (output / 'index.html').is_file():
        raise RuntimeError('Frontend build produced no index.html.')
    marker.write_text(value, encoding='ascii')


def check_port(port):
    with socket.socket() as listener:
        try:
            listener.bind(('127.0.0.1', port))
        except OSError as error:
            raise RuntimeError(f'Local port {port} is unavailable. Stop the other instance or use --port 8766.') from error


def find_adb(root, value):
    path = shutil.which(value)
    if not path:
        candidate = Path(os.path.expandvars(value)).expanduser()
        if candidate.is_file():
            path = str(candidate.resolve())
    if not path and value == 'adb':
        candidate = root / 'platform-tools' / ('adb.exe' if os.name == 'nt' else 'adb')
        if candidate.is_file():
            path = str(candidate)
    if not path:
        raise RuntimeError('ADB not found. Unzip Android platform-tools beside start-windows.cmd, or pass --adb "C:\\Android\\platform-tools\\adb.exe".')
    run([path, 'version'], timeout=10)
    return path


def server_command(python, adb, args):
    command = [str(python), '-m', 'automation', '--adb', str(adb), '--data', 'data', '--port', str(args.port)]
    if args.no_ocr:
        command.append('--no-ocr')
    if args.ocr_config:
        command.extend(['--ocr-config', str(args.ocr_config)])
    return command


def run_server(command):
    # Console Ctrl+C reaches both processes. Let the backend finish saving results.
    with subprocess.Popen(command) as process:
        try:
            return process.wait()
        except KeyboardInterrupt:
            print('Stopping backend; waiting for active work to finish. Ctrl+C again forces exit.', flush=True)
            try:
                return process.wait()
            except KeyboardInterrupt:
                process.kill()
                process.wait()
                return 130


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prepare and start the Android automation workbench')
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--ocr-config', type=Path)
    parser.add_argument('--no-ocr', action='store_true')
    parser.add_argument('--setup-only', action='store_true', help='Prepare dependencies/build without running the server')
    parser.add_argument('--refresh', action='store_true', help='Reinstall locked dependencies and rebuild frontend')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    try:
        validate_python(sys.version_info, struct.calcsize('P') * 8, bool(sysconfig.get_config_var('Py_GIL_DISABLED')))
        if not 1 <= args.port <= 65535:
            raise RuntimeError('Port must be between 1 and 65535.')
        if args.no_ocr and args.ocr_config:
            raise RuntimeError('--no-ocr and --ocr-config cannot be used together.')
        if args.ocr_config and not args.ocr_config.is_file():
            raise RuntimeError('OCR config file does not exist. Paths are relative to the project directory.')
        if not args.setup_only:
            check_port(args.port)
        adb = find_adb(root, args.adb)
        environment = root / '.venv'
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if not python.is_file():
            if environment.exists():
                raise RuntimeError('Existing .venv is incomplete or from another OS. Rename it and run the launcher again.')
            run([sys.executable, '-m', 'venv', environment])
        probe = "import struct,sys,sysconfig; assert sys.version_info[:2]==(3,14) and struct.calcsize('P')*8==64 and not sysconfig.get_config_var('Py_GIL_DISABLED'), 'Rename incompatible .venv and restart'"
        run([python, '-c', probe])
        install_python(root, python, args.refresh)
        build_frontend(root, args.refresh)
        if args.setup_only:
            print('Setup complete. No server was started.', flush=True)
            return 0
        print(f'Open http://127.0.0.1:{args.port} after the backend reports ready. Stop with Ctrl+C.', flush=True)
        return run_server(server_command(python, adb, args))
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Startup failed: {error}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
