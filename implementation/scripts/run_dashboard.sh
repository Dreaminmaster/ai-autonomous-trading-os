#!/usr/bin/env bash
# ============================================================================
# run_dashboard.sh — Start ATOS local dashboard
# ============================================================================
# Starts the built-in ATOS dashboard HTTP server.
# This is separate from the Freqtrade WebUI — it shows ATOS-specific views:
#   - strategy candidates
#   - trade intents
#   - risk decisions
#   - ledger events
#   - strategy scores
#
# Usage:
#   ./scripts/run_dashboard.sh
#   ./scripts/run_dashboard.sh --port 8787
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

PORT="${1:-8787}"

echo "=== ATOS Dashboard ==="
echo "Starting at http://127.0.0.1:$PORT"
echo ""

cd "$PROJECT_DIR"
python -m atos.cli dashboard --port "$PORT"
