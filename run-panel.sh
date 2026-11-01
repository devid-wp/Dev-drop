#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"
PIP="$ROOT/.venv/bin/pip"

if [ ! -x "$PYTHON" ]; then
    python3 -m venv "$ROOT/.venv"
fi

if ! "$PYTHON" -c 'import fastapi, uvicorn, textual' >/dev/null 2>&1; then
    "$PIP" install -e .
fi

exec "$PYTHON" -m app.cli serve "$@"
