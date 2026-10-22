#!/usr/bin/env bash
# Prepare the frontend and backend without Android tools or OCR.
set -e
cd -- "$(dirname -- "$0")"
exec bash ./start.sh --platform-only "$@"
