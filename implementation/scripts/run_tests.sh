#!/usr/bin/env bash
# ============================================================================
# run_tests.sh — Run ATOS test suite with safety checks
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== ATOS Test Suite ==="
echo ""

cd "$PROJECT_DIR"

echo "Installing dependencies..."
pip install -e '.[dev]' -q

echo ""
echo "Running tests..."
pytest -v "$@"

echo ""
echo "=== All tests passed ==="
