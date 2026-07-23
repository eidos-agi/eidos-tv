#!/bin/bash
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH=.
export EIDOS_TV_ROOT="$(pwd)"
export EIDOS_TV_STATION=demo
exec python3 -m eidos_tv.cli serve --station demo --root . --port "${PORT:-8799}"
