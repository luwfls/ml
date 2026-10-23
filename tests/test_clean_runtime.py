import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CleanRuntimeTests(unittest.TestCase):
    def test_cleanup_removes_runtime_data_but_keeps_source_and_test_fixtures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'scripts' / 'clean_runtime.py'
            script.parent.mkdir()
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'scripts' / script.name, script)
            for name in ('data/states', 'data/captures', 'data/assets', 'states', 'runs', 'logs', 'frontend/src', 'tests/fixtures'):
                path = root / name
                path.mkdir(parents=True)
                (path / 'sample').write_text('keep only source and fixtures')
            outside = root / 'external'
            outside.mkdir()
            (outside / 'sample').write_text('external data')
            if sys.platform != 'win32':
                (root / 'captures').symlink_to(outside, target_is_directory=True)
            for _ in range(2):
                subprocess.run([sys.executable, str(script)], cwd=root.parent, check=True, capture_output=True)
            for name in ('data', 'states', 'runs', 'logs', 'captures'):
                self.assertFalse((root / name).exists())
            for name in ('frontend/src/sample', 'tests/fixtures/sample', 'external/sample'):
                self.assertTrue((root / name).is_file())
