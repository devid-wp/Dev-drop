#!/usr/bin/env sh
# Backward-compatible helper. TLS is prepared by the normal server startup.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    printf '%s\n' 'Create the project environment first, or run: python3 -m venv .venv && .venv/bin/pip install -e .' >&2
    exit 1
fi
exec "$PYTHON" -m app.cli serve "$@"
