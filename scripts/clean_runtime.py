"""Remove local workbench data. Stop the workbench before running this script."""
from pathlib import Path
import shutil


def main():
    root = Path(__file__).resolve().parents[1]
    for name in ('data', 'captures', 'assets', 'states', 'flows', 'tasks', 'runs', 'batches', 'logs'):
        path = root / name
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
        print(f'Cleared {name}/')


if __name__ == '__main__':
    main()
