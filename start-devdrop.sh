#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Dev-Drop needs Python 3.10 or newer. Install Python, then run this script again." >&2
        exit 127
    fi
    python3 -m venv "$ROOT/.venv"
fi

if ! "$PYTHON" -c 'import cryptography, fastapi, qrcode, textual, uvicorn' >/dev/null 2>&1; then
    echo "Setting up the Dev-Drop CLI..."
    "$PYTHON" -m pip install -e "$ROOT"
fi

if [ "$#" -eq 0 ]; then
    exec "$PYTHON" -m app.cli tui
fi

exec "$PYTHON" -m app.cli "$@"
