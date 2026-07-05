import sys
lines = open(sys.argv[1]).readlines()
repl = [
    '        la_text = result.stdout + "\\n" + result.stderr\n',
    '        outer_rc = result.returncode\n',
    '        from atos.lookahead_parser import parse_lookahead_result\n',
    '        parsed = parse_lookahead_result(la_text)\n',
    '        final = parsed["status"]\n',
    '        if parsed["status"] == "PASS":\n',
    '            final = "PASS"\n',
    '        elif outer_rc != 0 and parsed["status"] == "ERROR":\n',
    '            final = "ERROR(rc={})".format(outer_rc)\n',
    '        b["lookahead"] = final\n',
    '        sp = Path("freqtrade_data/backtest_results/{}_la_lookahead_status.json".format(name))\n',
    '        sp.write_text(json.dumps({\n',
    '            "outer_returncode": outer_rc,\n',
    '            "parser_status": parsed["status"],\n',
    '            "has_bias": parsed.get("has_bias"),\n',
    '            "evidence_source": parsed.get("evidence_source", "unknown"),\n',
    '            "evidence_log": str(Path("freqtrade_data/backtest_results/{}_la_lookahead.log".format(name)).resolve()),\n',
    '            "final_status": final,\n',
    '        }, indent=2, default=str))\n',
    '    except Exception as e:\n',
    '        b["lookahead"] = "CRASH:{}".format(e)\n',
]
with open(sys.argv[1], "w") as f:
    f.writelines(lines[:126] + repl + lines[140:])
