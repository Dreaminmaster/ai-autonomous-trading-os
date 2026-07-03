from pathlib import Path
names = {1:'baseline',2:'trend025',3:'trend_off',4:'hold6h',5:'hold4h',6:'t025+h6',7:'toff+h6',8:'t025+early',9:'toff+early'}
for i in range(1,10):
    logs = list(Path('/tmp/ci_0290/freqtrade_data/backtest_results').glob(f'round1_{i}_*.log'))
    if not logs:
        print(f'V{i}: LOG_MISSING')
        continue
    text = logs[0].read_text()
    found = False
    for line in text.split('\n'):
        if 'AISupervisedStrategy' in line and '\u2502' in line and 'TOTAL' not in line and 'Trades' not in line:
            parts = [p.strip() for p in line.split('\u2502')]
            if len(parts) >= 8 and parts[2].lstrip('-').replace('.','').isdigit():
                n = names.get(i, str(i))
                print(f'V{i} {n}: trades={parts[2]} profit={parts[5]} dd={parts[7] if len(parts)>7 else "?"}')
                found = True
                break
    if not found:
        # Try TOTAL row instead
        for line in text.split('\n'):
            if 'TOTAL' in line and '\u2502' in line and any(c.isdigit() for c in line[10:30]):
                parts = [p.strip() for p in line.split('\u2502')]
                print(f'V{i} TOTAL: {parts[1:5]}...')
                break
