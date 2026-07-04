"""Lookahead result parser for Freqtrade 2026.6 output."""
import re


def parse_lookahead_result(text: str) -> dict:
    """Parse Freqtrade lookahead-analysis output into structured result.

    Returns:
        {
            "status": "PASS|FAIL|ERROR",
            "has_bias": true|false|null,
            "total_signals": int or None,
            "biased_entry_signals": int or None,
            "biased_exit_signals": int or None,
            "evidence_source": "table|log|error"
        }
    """
    if not text:
        return {"status": "ERROR", "has_bias": None, "evidence_source": "error", "error": "empty output"}

    # ── Error conditions ─────────────────────────────────────
    if "No data found" in text or "Terminating" in text:
        return {"status": "ERROR", "has_bias": None, "evidence_source": "error", "error": "no data found"}

    # ── Log message: "AISupervisedStrategy: no bias detected" ─
    if "no bias detected" in text.lower():
        return parse_table_row(text) or {"status": "PASS", "has_bias": False, "evidence_source": "log",
                                           "total_signals": None, "biased_entry_signals": None, "biased_exit_signals": None}

    # ── Log message: "AISupervisedStrategy: bias detected!" ──
    if "bias detected!" in text or "bias detected" in text:
        br = parse_table_row(text)
        if br:
            br["status"] = "FAIL"
            return br
        return {"status": "FAIL", "has_bias": True, "evidence_source": "log",
                "total_signals": None, "biased_entry_signals": None, "biased_exit_signals": None}

    # ── Table-based result ────────────────────────────────────
    br = parse_table_row(text)
    if br:
        return br

    # ── Cannot parse ──────────────────────────────────────────
    return {"status": "ERROR", "has_bias": None, "evidence_source": "error", "error": "unparseable output"}


def parse_table_row(text: str) -> dict | None:
    """Parse Freqtrade Lookahead Analysis table row.

    Expected format:
    │ ai_supervised_strategy.py │ AISupervisedStrategy │ No │ 20 │ 0 │ 0 │ │
    or
    │ filename │ strategy │ has_bias │ total_signals │ biased_entry_signals │ biased_exit_signals │ biased_indicators │
    │ ai_supervised_strategy.py │ AISupervisedStrategy │ Yes │ 20 │ 18 │ 16 │ │
    """
    for line in text.split("\n"):
        if "AISupervisedStrategy" not in line:
            continue
        if "│" not in line:
            continue
        if "too few trades" in line.lower():
            return {"status": "ERROR", "has_bias": None, "evidence_source": "table",
                    "total_signals": None, "biased_entry_signals": None, "biased_exit_signals": None,
                    "error": "too few trades"}

        parts = [p.strip() for p in line.split("│")]
        # Expected: filename | strategy | has_bias | total_signals | biased_entry | biased_exit | biased_indicators
        if len(parts) < 5:
            continue

        # Find has_bias column
        strategy_idx = next((i for i, p in enumerate(parts) if "AISupervisedStrategy" in p), -1)
        if strategy_idx < 0:
            continue

        bias_val = parts[strategy_idx + 1] if len(parts) > strategy_idx + 1 else ""
        bias_clean = bias_val.replace("Yes", "true").replace("No", "false").lower()
        has_bias = True if "true" in bias_clean else (False if "false" in bias_clean else None)

        total_sig = int(parts[strategy_idx + 2]) if len(parts) > strategy_idx + 2 and parts[strategy_idx + 2].isdigit() else None
        biased_entry = int(parts[strategy_idx + 3]) if len(parts) > strategy_idx + 3 and parts[strategy_idx + 3].isdigit() else None
        biased_exit = int(parts[strategy_idx + 4]) if len(parts) > strategy_idx + 4 and parts[strategy_idx + 4].isdigit() else None

        status = "PASS" if has_bias is False else ("FAIL" if has_bias is True else "ERROR")
        return {
            "status": status,
            "has_bias": has_bias,
            "total_signals": total_sig,
            "biased_entry_signals": biased_entry,
            "biased_exit_signals": biased_exit,
            "evidence_source": "table",
        }

    return None
