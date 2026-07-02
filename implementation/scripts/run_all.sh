#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install -e '.[dev]'
python -m atos.cli status
python -m atos.cli risk
python -m atos.cli cycle
python -m atos.cli loop --loops 3
python -m atos.cli review
pytest
