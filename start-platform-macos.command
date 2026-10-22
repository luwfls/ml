#!/usr/bin/env bash
cd -- "$(dirname -- "$0")" || exit 1
bash ./start-macos.command --platform-only "$@"
