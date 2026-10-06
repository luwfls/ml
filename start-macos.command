#!/usr/bin/env bash
cd -- "$(dirname -- "$0")" || exit 1
bash ./start.sh "$@"
workbench_exit=$?
if [ "$workbench_exit" -ne 0 ]; then
    echo 'Startup failed. See the error above and docs/workbench-usage.md.' >&2
    read -r -p 'Press Enter to close...' || true
fi
exit "$workbench_exit"
