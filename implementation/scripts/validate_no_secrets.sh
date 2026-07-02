#!/bin/sh
# ============================================================================
# validate_no_secrets.sh — Scan for leaked secrets before commit/push
# ============================================================================
# Checks code, configs, logs, test fixtures, and Git history for:
#   - API keys, Private keys, Passwords, OKX credentials, OpenAI/DeepSeek keys
#
# Usage:
#   ./scripts/validate_no_secrets.sh
#
# Exit code 0 = clean, 1 = potential leak found
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PROJECT_DIR/.." && pwd)"

echo "=== Secret Leakage Scan ==="
echo "Scanning: $REPO_ROOT"
echo ""

VIOLATIONS=0

# More portable: define patterns in a loop with eval
scan_pattern() {
    pattern="$1"
    for scan_dir in \
        "$REPO_ROOT/implementation/src" \
        "$REPO_ROOT/implementation/tests" \
        "$REPO_ROOT/implementation/config" \
        "$REPO_ROOT/implementation/scripts" \
        "$REPO_ROOT/configs" \
        "$REPO_ROOT/schemas" \
        "$REPO_ROOT/prompts" \
        "$REPO_ROOT/docs"; do
        if [ -d "$scan_dir" ]; then
            MATCHES=$(grep -rnE "$pattern" "$scan_dir" 2>/dev/null | grep -vE '(\.example\.|\.sample\.|\.schema\.json|README|\.git|validate_no_secrets)' || true)
            if [ -n "$MATCHES" ]; then
                echo "  POTENTIAL LEAK: $pattern"
                echo "$MATCHES" | head -3
                echo ""
                VIOLATIONS=$((VIOLATIONS + 1))
            fi
        fi
    done
}

# OpenAI / generic API keys
scan_pattern 'sk-[a-zA-Z0-9]{32,}'
scan_pattern 'sk-[a-zA-Z0-9]{48,}'

# Hardcoded credentials
scan_pattern 'api_key *= *"[^"]{16,}"'
scan_pattern 'api_secret *= *"[^"]{16,}"'
scan_pattern 'passphrase *= *"[^"]{8,}"'
scan_pattern 'password *= *"[^"]{8,}"'

# Bearer tokens
scan_pattern 'Bearer +sk-[a-zA-Z0-9]{32,}'

# PEM keys (grep for start of private key)
scan_pattern 'BEGIN.*PRIVATE KEY'

# Check Git history for commits about secrets
if git -C "$REPO_ROOT" log --oneline -50 2>/dev/null | grep -qiE '(api.key|secret|password|credential)'; then
    echo "  Check: commits mention 'key/secret/password/credential' — verify no real secrets."
    VIOLATIONS=$((VIOLATIONS + 1))
fi

echo ""
if [ "$VIOLATIONS" -eq 0 ]; then
    echo "No secret leakage detected."
    exit 0
else
    echo "$VIOLATIONS potential leakage issue(s) found — review before pushing."
    exit 1
fi
