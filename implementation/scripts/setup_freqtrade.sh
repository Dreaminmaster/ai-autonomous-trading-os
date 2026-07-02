#!/usr/bin/env bash
# ============================================================================
# setup_freqtrade.sh — Initialize Freqtrade for AI Autonomous Trading OS
# ============================================================================
# Run this on macOS or Linux (not on iOS iSH).
# This script:
#   1. Installs Freqtrade via pip
#   2. Creates freqtrade_data directory structure
#   3. Generates dry-run config (no real API keys)
#   4. Ensures live trading is disabled
#
# Usage:
#   chmod +x setup_freqtrade.sh
#   ./setup_freqtrade.sh
#
# Docker alternative (recommended for production):
#   docker pull freqtradeorg/freqtrade:stable
#   docker run -v $(pwd)/freqtrade_data:/freqtrade/freqtrade_data freqtradeorg/freqtrade:stable
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
USER_DATA="$PROJECT_DIR/freqtrade_data"

echo "=== AI Autonomous Trading OS — Freqtrade Setup ==="
echo "Project dir: $PROJECT_DIR"
echo "User data:   $USER_DATA"
echo ""

# ---------- 1. Create freqtrade_data directory structure ----------
echo "[1/5] Creating freqtrade_data directory structure..."

mkdir -p "$USER_DATA"
mkdir -p "$USER_DATA/strategies"
mkdir -p "$USER_DATA/data"
mkdir -p "$USER_DATA/logs"
mkdir -p "$USER_DATA/backtest_results"
mkdir -p "$USER_DATA/hyperopt_results"

echo "  ✓ freqtrade_data created"

# ---------- 2. Install Freqtrade ----------
echo "[2/5] Installing Freqtrade..."

if python -c "import freqtrade" 2>/dev/null; then
    echo "  ✓ Freqtrade already installed"
else
    pip install freqtrade
    echo "  ✓ Freqtrade installed"
fi

# ---------- 3. Create dry-run config (no real keys) ----------
echo "[3/5] Creating dry-run config..."

cat > "$USER_DATA/config.dryrun.json" << 'CONFIGEOF'
{
    "max_open_trades": 3,
    "stake_currency": "USDT",
    "stake_amount": "unlimited",
    "tradable_balance_ratio": 0.99,
    "fiat_display_currency": "USD",
    "dry_run": true,
    "cancel_open_orders_on_exit": false,
    "trading_mode": "spot",
    "margin_mode": "",
    "unfilledtimeout": {
        "entry": 10,
        "exit": 10,
        "exit_timeout_count": 0,
        "unit": "minutes"
    },
    "entry_pricing": {
        "price_side": "other",
        "use_order_book": true,
        "order_book_top": 1,
        "price_last_balance": 0.0,
        "check_depth_of_market": {
            "enabled": false,
            "bids_to_ask_delta": 1
        }
    },
    "exit_pricing": {
        "price_side": "other",
        "use_order_book": true,
        "order_book_top": 1
    },
    "exchange": {
        "name": "okx",
        "key": "",
        "secret": "",
        "password": "",
        "ccxt_config": {
            "enableRateLimit": true,
            "urls": {
                "api": {
                    "public": "https://www.okx.com"
                }
            }
        },
        "ccxt_async_config": {},
        "pair_whitelist": [
            "BTC/USDT",
            "ETH/USDT"
        ],
        "pair_blacklist": [],
        "outdated_offset": 5
    },
    "pairlists": [
        {"method": "StaticPairList"}
    ],
    "bot_name": "atos_freqtrade_bot",
    "initial_state": "running",
    "force_entry_enable": false,
    "internals": {
        "process_throttle_secs": 5
    },
    "api_server": {
        "enabled": true,
        "listen_ip_address": "127.0.0.1",
        "listen_port": 8080,
        "verbosity": "info",
        "enable_openapi": false,
        "jwt_secret_key": "changeme_in_production_please_change_me_to_random_32_chars",
        "CORS_origins": [],
        "username": "atos",
        "password": "atos_dashboard"
    }
}
CONFIGEOF

echo "  ✓ config.dryrun.json created"

# ---------- 4. Create live config (disabled, example only) ----------
echo "[4/5] Creating live config example (live disabled by default)..."

cat > "$USER_DATA/config.live.example.json" << 'CONFIGEOF'
{
    "max_open_trades": 1,
    "stake_currency": "USDT",
    "stake_amount": 100,
    "tradable_balance_ratio": 0.99,
    "fiat_display_currency": "USD",
    "dry_run": false,
    "trading_mode": "spot",
    "margin_mode": "",
    "exchange": {
        "name": "okx",
        "key": "YOUR_OKX_API_KEY",
        "secret": "YOUR_OKX_API_SECRET",
        "password": "YOUR_OKX_API_PASSPHRASE",
        "ccxt_config": {"enableRateLimit": true},
        "ccxt_async_config": {},
        "pair_whitelist": [
            "BTC/USDT",
            "ETH/USDT"
        ],
        "pair_blacklist": []
    },
    "pairlists": [
        {"method": "StaticPairList"}
    ],
    "bot_name": "atos_freqtrade_live",
    "initial_state": "stopped"
}
CONFIGEOF

echo "  ✓ config.live.example.json created (live disabled)"

# ---------- 5. Verify installation ----------
echo "[5/5] Verifying installation..."
echo ""

FREQTRADE_VERSION=$(python -c "import freqtrade; print(freqtrade.__version__)" 2>/dev/null || echo "unknown")
echo "  Freqtrade version: $FREQTRADE_VERSION"
echo "  Config: $USER_DATA/config.dryrun.json"
echo "  Live disabled: YES (dry_run=true in dryrun config)"

# Create user_data symlink for Freqtrade compatibility
if [ ! -d "user_data" ] && [ ! -L "user_data" ]; then
    ln -s freqtrade_data user_data
    echo "  ✓ user_data → freqtrade_data symlink created"
fi
echo ""

echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Download historical data:"
echo "     ./scripts/download_data.sh"
echo ""
echo "  2. Run backtest:"
echo "     ./scripts/run_backtest.sh"
echo ""
echo "  3. Start dry-run:"
echo "     ./scripts/run_dryrun.sh"
echo ""
echo "  Docker alternative:"
echo "    docker run -v \$(pwd)/freqtrade_data:/freqtrade/freqtrade_data freqtradeorg/freqtrade:stable"
