"""Canonical→Round1 Lookahead Status Contract Consumer.

Single source of truth for consuming structured lookahead status JSON.
Round1 must NOT double-parse — it can only read this format.
Canonical status JSON is IMMUTABLE — this consumer is read-only.
"""
import json
from pathlib import Path


def consume_lookahead_status(wrapper_returncode: int, status_path: Path) -> dict:
    """Consume canonical lookahead status JSON, enforcing wrapper contract.

    READ-ONLY: Never writes to status_path.

    Returns:
        {
            "lookahead": final_status string for Round1 report,
            "freqtrade_returncode": raw Freqtrade subprocess returncode,
            "parser_status": parser status from canonical runner,
            "has_bias": whether bias was detected,
            "contract_status": one of "ok" / "mismatch" / "error",
        }
    """
    DEFAULT = {
        "lookahead": "ERROR_MISSING_EVIDENCE",
        "freqtrade_returncode": -1,
        "parser_status": "ERROR",
        "has_bias": None,
        "contract_status": "error",
    }

    # ── missing status file ───────────────────────────────────
    if not status_path.exists():
        DEFAULT["lookahead"] = "ERROR_MISSING_EVIDENCE"
        return DEFAULT

    # ── invalid / malformed JSON ──────────────────────────────
    try:
        st = json.loads(status_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        DEFAULT["lookahead"] = "ERROR_MALFORMED_EVIDENCE:{}".format(type(e).__name__)
        return DEFAULT

    # ── schema validation ─────────────────────────────────────
    if not isinstance(st, dict):
        DEFAULT["lookahead"] = "ERROR_BAD_SCHEMA:not_dict"
        return DEFAULT
    if st.get("schema_version") != 1:
        DEFAULT["lookahead"] = "ERROR_UNKNOWN_SCHEMA_VERSION"
        return DEFAULT

    final = st.get("final_status", "ERROR")
    freq_rc = st.get("freqtrade_returncode", -1)
    parser_status = st.get("parser_status", "ERROR")
    has_bias = st.get("has_bias")

    # ── P1: True contract enforcement ─────────────────────────
    if wrapper_returncode == 0 and final in ("PASS", "PASS_WITH_RC_ANOMALY"):
        # A: wrapper success + canonical PASS → accept
        lookahead = final
        contract = "ok"
    elif wrapper_returncode != 0 and final in ("PASS", "PASS_WITH_RC_ANOMALY"):
        # B: wrapper failed but canonical says PASS → mismatch (evidence conflict)
        lookahead = "ERROR_CONTRACT_MISMATCH"
        contract = "mismatch"
    elif wrapper_returncode == 0 and final in ("FAIL", "ERROR"):
        # C: wrapper success but canonical says FAIL/ERROR → propagate
        lookahead = "ERROR_CONTRACT:{}".format(final)
        contract = "error"
    elif wrapper_returncode != 0 and final in ("FAIL", "ERROR"):
        # D: wrapper failed + canonical FAIL/ERROR → propagate
        lookahead = final
        contract = "ok"
    else:
        lookahead = "ERROR_CONTRACT:unknown"
        contract = "error"

    return {
        "lookahead": lookahead,
        "freqtrade_returncode": freq_rc,
        "parser_status": parser_status,
        "has_bias": has_bias,
        "contract_status": contract,
    }
