# Short Prompt for Harness

Use this after the repository is ready.

```text
请 clone 并读取这个规格仓库：

https://github.com/Dreaminmaster/ai-autonomous-trading-os.git

先读：
1. AGENTS.md
2. README.md
3. docs/00_overview.md
4. docs/09_mvp_plan.md
5. tests/safety_tests.md

目标：按规格实现 OKX AI Autonomous Trading OS。

注意：
- 先做设计、脚手架、schema、risk manager、paper trading。
- 不要真实下单。
- 不要调用 OKX live order API。
- 不要把 OKX/API key 写进代码、日志、报告或 Git。
- AI 只能输出结构化 trade_intent JSON。
- 所有交易意图必须经过确定性 Python 风控。
- 默认模式必须是 paper 或 design，不是 live。

请先输出实现计划、文件结构、阶段目标和安全检查清单。
```
