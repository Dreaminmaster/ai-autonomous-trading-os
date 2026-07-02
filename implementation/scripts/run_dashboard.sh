#!/usr/bin/env bash
# ============================================================================
# run_dashboard.sh — Start ATOS local dashboard
# ============================================================================
# Starts the built-in ATOS dashboard HTTP server on 127.0.0.1.
# Override with: ATOS_DASHBOARD_PORT=XXXXX ./scripts/run_dashboard.sh
#
# Usage:
#   ./scripts/run_dashboard.sh
#   ATOS_DASHBOARD_PORT=9999 ./scripts/run_dashboard.sh
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

PORT="${ATOS_DASHBOARD_PORT:-28787}"
HOST="${ATOS_DASHBOARD_HOST:-127.0.0.1}"

echo "=== ATOS Dashboard ==="
echo "Starting at http://${HOST}:${PORT}"
echo ""

cd "$PROJECT_DIR"
python -m atos.cli dashboard --port "$PORT"
