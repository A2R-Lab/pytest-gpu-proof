#!/usr/bin/env bash
set -e

# Check Python version — requires 3.11+
PY_TOO_OLD=$(python3 -c "import sys; print(sys.version_info < (3, 11))" 2>/dev/null || echo "True")
if [ "$PY_TOO_OLD" = "True" ]; then
    echo "ERROR: pytest-gpu-proof requires Python 3.11 or later."
    echo "       You are running: $(python3 --version 2>&1)"
    echo "       Please switch to Python 3.11+ before installing."
    exit 1
fi

python3 -m pip install --upgrade pip

if [ "$1" = "dev" ]; then
    python3 -m pip install -e ".[dev]"
else
    python3 -m pip install -e .
fi
