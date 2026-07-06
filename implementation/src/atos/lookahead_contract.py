"""Canonical→Round1 Lookahead Status Contract Consumer.

Single source of truth for consuming structured lookahead status JSON.
Round1 must NOT double-parse — it can only read this format.
"""
import json
from pathlib import Path


def consume_lookahead_status(wrapper_returncode: int, status_path: Path) -> dict:
    """Consume canonical lookahead status JSON, enforcing wrapper contract.

    Args:
        wrapper_returncode: exit code from subprocess.run wrapping the
            canonical runner (NOT the Freqtrade returncode).
        status_path: path to <output>_lookahead_status.json written by
            the canonical runner.

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

    # ── P2: missing status file ───────────────────────────────
    if not status_path.exists():
        DEFAULT["lookahead"] = "ERROR_MISSING_EVIDENCE"
        return DEFAULT

    # ── P2: invalid / malformed JSON ──────────────────────────
    try:
        st = json.loads(status_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        DEFAULT["lookahead"] = "ERROR_MALFORMED_EVIDENCE:{}".format(type(e).__name__)
        return DEFAULT

    # ── P2: schema validation ─────────────────────────────────
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

    # ── Contract enforcement ─────────────────────────────────
    if wrapper_returncode == 0 and final in ("PASS", "PASS_WITH_RC_ANOMALY"):
        contract = "ok"
    elif wrapper_returncode == 0 and final in ("FAIL", "ERROR"):
        contract = "error"
    elif wrapper_returncode != 0 and final in ("FAIL", "ERROR"):
        contract = "ok"
    elif wrapper_returncode != 0 and final in ("PASS", "PASS_WITH_RC_ANOMALY"):
        contract = "mismatch"
    else:
        contract = "error"

    return {
        "lookahead": final,
        "freqtrade_returncode": freq_rc,
        "parser_status": parser_status,
        "has_bias": has_bias,
        "contract_status": contract,
    }
