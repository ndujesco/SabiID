#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m backend.data_gen
exec python3 -m backend.app
