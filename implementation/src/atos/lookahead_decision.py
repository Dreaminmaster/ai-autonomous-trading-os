"""Shared lookahead decision engine — single source of truth.

Used by both Canonical Runner and Round1.
Same input → same final_status, every path.
"""
from atos.lookahead_parser import parse_lookahead_result

FATAL_MARKERS = [
    "Traceback (most recent call last)",
    "No data found",
    "Terminating",
    "TimeoutExpired",
    "unhandled exception",
]

def decide_lookahead(process_returncode, parsed_result, combined_output):
    """Return unified decision dict.
    
    Rules (priority order):
      1. Parser FAIL → final_status=FAIL
      2. Parser ERROR → final_status=ERROR  
      3. Fatal marker in output → final_status=ERROR
      4. Parser PASS + rc=0 + no fatal → final_status=PASS
      5. Parser PASS + rc!=0 + explicit no-bias + no fatal → final_status=PASS_WITH_RC_ANOMALY
    """
    rc = process_returncode
    ps = parsed_result.get("status", "ERROR")
    has_bias = parsed_result.get("has_bias", None)
    evidence = parsed_result.get("evidence_source", "unknown")
    
    fatal_found = []
    for marker in FATAL_MARKERS:
        if marker.lower() in combined_output.lower():
            fatal_found.append(marker)
    
    # Rule 1: parser FAIL
    if ps == "FAIL":
        return {
            "process_returncode": rc,
            "parser_status": ps,
            "has_bias": has_bias,
            "explicit_no_bias_evidence": has_bias is False,
            "fatal_markers_found": fatal_found,
            "final_status": "FAIL",
            "reason": "parser returned FAIL (has_bias=True)"
        }
    
    # Rule 2: parser ERROR
    if ps == "ERROR":
        return {
            "process_returncode": rc,
            "parser_status": ps,
            "has_bias": has_bias,
            "explicit_no_bias_evidence": False,
            "fatal_markers_found": fatal_found,
            "final_status": "ERROR",
            "reason": "parser returned ERROR"
        }
    
    # Rule 3: fatal marker
    if fatal_found:
        return {
            "process_returncode": rc,
            "parser_status": ps,
            "has_bias": has_bias,
            "explicit_no_bias_evidence": False,
            "fatal_markers_found": fatal_found,
            "final_status": "ERROR",
            "reason": f"fatal marker(s): {fatal_found}"
        }
    
    # Rule 4: PASS + rc=0
    if ps == "PASS" and rc == 0:
        return {
            "process_returncode": rc,
            "parser_status": ps,
            "has_bias": has_bias,
            "explicit_no_bias_evidence": has_bias is False,
            "fatal_markers_found": fatal_found,
            "final_status": "PASS",
            "reason": "parser PASS, rc=0, no fatal markers"
        }
    
    # Rule 5: PASS + rc != 0  + explicit no-bias evidence
    if ps == "PASS" and rc != 0 and has_bias is False:
        return {
            "process_returncode": rc,
            "parser_status": ps,
            "has_bias": has_bias,
            "explicit_no_bias_evidence": True,
            "fatal_markers_found": fatal_found,
            "final_status": "PASS_WITH_RC_ANOMALY",
            "reason": f"parser PASS with explicit no-bias, but subprocess rc={rc}"
        }
    
    # Fallback
    return {
        "process_returncode": rc,
        "parser_status": ps,
        "has_bias": has_bias,
        "explicit_no_bias_evidence": False,
        "fatal_markers_found": fatal_found,
        "final_status": "ERROR",
        "reason": f"unexpected state: ps={ps} rc={rc}"
    }
