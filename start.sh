#!/usr/bin/env bash
# Build the frontend and serve both the page and API in one foreground process.
set -e
cd -- "$(dirname -- "$0")"

if [ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = x86_64 ]; then
    if [ -x .venv-intel/bin/python ]; then
        workbench_python=.venv-intel/bin/python
    elif command -v python3.13 >/dev/null 2>&1; then
        workbench_python=python3.13
    else
        echo 'Intel Mac requires standard Python 3.13 (64-bit). Install it, then run this script again.' >&2
        exit 1
    fi
elif [ -x .venv/bin/python ]; then
    workbench_python=.venv/bin/python
elif command -v python3.14 >/dev/null 2>&1; then
    workbench_python=python3.14
elif command -v python3 >/dev/null 2>&1; then
    workbench_python=python3
else
    echo 'Install standard Python 3.14 (64-bit), then run this script again.' >&2
    exit 1
fi

exec "$workbench_python" scripts/start.py "$@"
