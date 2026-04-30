#!/usr/bin/env bash
set -e

python -m pip install --upgrade pip

if [ "$1" = "dev" ]; then
    python -m pip install -e ".[dev]"
else
    python -m pip install -e .
fi
