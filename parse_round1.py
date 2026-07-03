import re, sys
from pathlib import Path

for i in range(1, 10):
    logs = list(Path("/tmp/ci_r3/freqtrade_data/backtest_results").glob(f"round1_{i}_*.log"))
    if not logs:
        print(f"{i}: LOG_MISSING")
        continue
    text = logs[0].read_text()
    found = False
    for line in text.split("\n"):
        if "TOTAL" in line and "Trades" not in line and re.search(r'[0-9]+', line) and "│" in line:
            parts = [p.strip() for p in line.split("│")]
            if len(parts) >= 7 and parts[2] and parts[2].strip().isdigit():
                name = logs[0].stem.replace("round1_", "")
                trades = parts[2].strip()
                profit = parts[5].strip() if len(parts) > 5 else "?"
                dd = parts[8].strip() if len(parts) > 8 else "?"
                print(f"{name}: trades={trades} profit={profit} dd={dd}")
                found = True
                break
    if not found:
        name = logs[0].stem.replace("round1_", "")
        # Try last resort
        for line in text.split("\n"):
            if "AISupervisedStrategy" in line and "│" in line:
                parts = [p.strip() for p in line.split("│")]
                trades = parts[2].strip() if len(parts) > 2 else "?"
                profit = parts[5].strip() if len(parts) > 5 else "?"
                dd = parts[8].strip() if len(parts) > 8 else "?"
                print(f"{name}: trades={trades} profit={profit} dd={dd} [from strat line]")
                found = True
                break
    if not found:
        print(f"{name}: PARSE_FAILED")
