# C14A Cross-Sectional Liquidity Risk — Authoritative Result V1

## 1. Final classification

C14A completed its single authorized official-public OKX H1–H5 capture,
strict replay, physically separate recomputation, and immutable artifact
upload. Data custody and independent recomputation passed, but the frozen
candidate failed its preregistered economic gates. The only valid result is:

- Stage: `C14A_H1_H5_FINAL_CLASSIFICATION`
- Classification: `ECONOMIC_FAIL`
- Status: `FAIL`
- Official-public data custody: `PASS`
- Historical replay: `PASS`
- Independent economic recomputation: `PASS`
- Historical economic PASS: `false`
- Best-window selection: `NOT_PERFORMED`
- Retuning: `NOT_AUTHORIZED`
- Authoritative rerun: `NOT_AUTHORIZED`
- Execution feasibility: `NOT_ESTABLISHED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This is a valid negative economic result. It is not a data failure, program
failure, profitable strategy, selected edge, or authorization to execute.

## 2. Exact implementation and one-shot run

- Repository: `Dreaminmaster/ai-autonomous-trading-os`
- Design PR: `#127`
- Design PR head: `655407ac9b46c6962c0a21e2d29d769ea3721b06`
- Exact merged design commit:
  `d5f7548f37f01a7f5f34dd4e7cc9f9d16f7a1176`
- Implementation PR: `#128`
- Implementation PR head:
  `23e2fd54771206797218e30817d22c44bfdb9c92`
- Exact merged implementation commit:
  `ae454a4a0f65407c7b039e0575a08222be9e7e80`
- Authoritative workflow run: `33096963409`
- C14A authority job: `98604287667` (`success`; `19m35s`)
- ATOS test job: `98604287017` (`success`)
- Freqtrade validation job: `98604287474` (`success`; `1h17m31s`)
- Same-run validation-summary job: `98627245932` (`success`)
- Notification job: `98627490652` (`success`; non-PR delivery suppressed by
  the retained duplicate-notification guard)
- Workflow URL:
  <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/33096963409>
- Authority job URL:
  <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/33096963409/job/98604287667>

The authority ran on the exact clean merged implementation commit above. It
was the only C14A authority dispatch. It must never be retriggered, replayed on
the exposed interval, or altered after inspecting this result.

## 3. Immutable custody and independent audit

The retained authority artifact is:

- Artifact ID: `9657445380`
- Name: `c14a-h1-h5-authoritative-33096963409`
- GitHub ZIP digest:
  `sha256:c39c5d253997e8fbcc2b14b80995e640d0fb9688433f07140b64a2b38f5f5cb2`
- Independently computed ZIP SHA-256:
  `c39c5d253997e8fbcc2b14b80995e640d0fb9688433f07140b64a2b38f5f5cb2`
- ZIP size: `24,853,527` bytes
- Created: `2026-08-27T17:29:16Z`
- Scheduled expiry: `2026-09-26T17:29:11Z`

An independent download outside the repository established:

- outer manifest: `2680 / 2680` files matched exact path, size, and SHA-256;
- outer sealed bytes: `129,471,029`;
- outer manifest SHA-256:
  `accfbaa55801841190764d571f38e9554ef4a2bfbc13340639ab6994f7d4028c`;
- capture manifest: `2658 / 2658` files verified;
- capture manifest SHA-256:
  `426b4e2bc243617d19723b3d6f45bcb90f105f9e34e192b1da2725d244442495`;
- capture index SHA-256:
  `af2035c79bda3fa149e7586a16fa777d2a60066ef1e2f01c6eb2c7f197fde97e`;
- checkout binding SHA-256:
  `15c841ddb713529d5121a0e08ae0fbdc33ce004269104a24b2c3347da1fb5053`;
- all `2632` capture-index path/size/SHA rows exactly matched the raw-file
  subset of the capture manifest;
- evidence manifest: `17 / 17` files verified;
- evidence manifest SHA-256:
  `542c590f57414a88d5a3682e139bab6afa9fb164d99a7cc884977c40da89638a`;
- frozen source inventory: `16 / 16` files matched the exact implementation
  tree;
- source inventory SHA-256:
  `e89523109c25b1732dad1f1d86d3f550988d69a39a01fc626d75c3524ece2c9d`;
- capture log SHA-256:
  `8236a44908af21e4f5ea689040156a4df6a8d6833255e0ba5468484dc76c5705`;
- evaluation log SHA-256:
  `dfe325470be96aa5a8abb3093eeacf4563d518f0fe68fa7b930b601d05ca95f6`;
- full authority-job log SHA-256:
  `e313ed1af2d941eef256263596d9e46419de18558db5c247ed2f8e6962608cb7`;
- full run-log ZIP SHA-256:
  `54892a489ee844d1b82ee554336d4d1ec9ccc6fd4a6cb1ff089b376cecbfa39b`.

The same-run ordinary artifact ZIP hashes are recorded after the workflow
fully closes:

- `atos-validation`:
  `e58c362fd8dba1aa38c6b3ee613140d007e5cf42479fe73ac46f019b9ebc1dce`;
- `freqtrade-validation`:
  `76403bd4e9304df8833b00fc4e00af2592552512a64b325ca0cdd2a9423d1de5`;
- `validation-summary`:
  `9d92a27003963ba82f1b7deeb56c568caad12279a38168ab2d546242364ea4b6`.

## 4. Official data coverage

The capture retained `2632` raw official-public response records totalling
`27,740,160` bytes:

- `32` official historical-data API records;
- `240` official historical-download records;
- `608` official history-candle API records;
- `1752` official historical mark-price-candle API records.

Every requested URL equalled its retained final URL; all requests succeeded
on the first attempt with no retry event. The only hosts were
`openapi.okx.com` and `static.okx.com`. No authenticated or private endpoint
was used.

The exact fixed universe was BTC, ETH, SOL, BCH, DOGE, XRP, LTC, and LINK
USDT perpetual swaps. Strict normalization produced:

- `22,537` confirmed trade rows per instrument, `180,296` total;
- `21,841` mark rows per instrument, `174,728` total;
- `2,730` funding settlements per instrument, `21,840` total.

Every trade and mark series was strictly hourly, ordered, duplicate-free, and
complete. Every trade candle had `confirm=1` and positive OHLC and
`volCcyQuote` values.

The retained funding timestamps were independently parsed again after
download. Every instrument was strictly ordered and duplicate-free, covering
its actual official first settlement near `2024-01-01T00:00:00Z` through
`2026-06-28T16:00:00Z`. Consecutive gaps were between `28,795` and `28,803`
seconds. The observed seconds were preserved exactly as supplied by OKX; they
were not snapped to an hour or replaced with synthetic timestamps.

Trade data covered `2023-12-03T00:00:00Z` through
`2026-06-29T00:00:00Z`; mark data covered `2023-12-31T23:00:00Z` through
`2026-06-28T23:00:00Z`; scored H1–H5 windows remained exactly
`2024-01-01T00:00:00Z` through `2026-06-29T00:00:00Z`.

## 5. Independent economic result

The physically separate implementation reported `status=PASS`, with pooled
metrics, BTC beta, and every gate matching production. It imported none of
the production signal, replay, ledger, gate, or finalizer implementations.

At the preregistered `1.0x` cost:

- aggregate return: `0.008874215829700053088819143` (`+0.8874%`);
- annualized weekly Sharpe: `0.1931594026306487`;
- raw weekly PSR: `0.6215639102720059`;
- program-level Bonferroni-adjusted PSR over `629` trials: `0`;
- maximum drawdown: `0.0942053581960982546028112796` (`9.4205%`);
- BTC beta: `0.05062511962064760998674600520`;
- annualized one-way turnover: `2.869569682169013139694247944`;
- decisions/non-flat directions: `130 / 520`;
- funding settlements: `21,840`;
- equity-buffer breaches/forced closes: `0 / 0`;
- price PnL: `50.74625684615175079990290022` USDT;
- funding PnL: `15.30881821315260522912838075` USDT;
- transaction costs: `21.68399591080409058493553503` USDT;
- reconciliation residual:
  `-0.000000000000000000000033546` USDT.

Window returns were H1 `+2.3490%`, H2 `+3.7649%`, H3 `-0.6649%`, H4
`+4.6768%`, and H5 `-5.6887%`. Only three of eight instruments had positive
net contribution. The largest positive instrument and window shares were
`0.7118858280600553520217271728` and
`0.4334104166343731130677306521`, both above the frozen `0.35` cap.

The candidate remained nominally positive under cost stress, but that cannot
override the preregistered statistical, breadth, concentration, window, and
comparator gates:

| Cost | Aggregate return | Annualized weekly Sharpe | Maximum drawdown |
|---|---:|---:|---:|
| `1.0x` | `+0.8874%` | `0.1932` | `9.4205%` |
| `1.5x` | `+0.6692%` | `0.1577` | `9.5012%` |
| `2.0x` | `+0.4514%` | `0.1222` | `9.5818%` |

At `1.0x`, the fixed mean-absolute-return rank comparator returned
`+1.2432%` with annualized Sharpe `0.2024`; C14A was worse on both required
metrics. The inverse-quote-volume comparator returned `-0.1605%` with Sharpe
`0.0131`; C14A beat that comparator and had lower drawdown and turnover than
both active comparators. Those passing comparisons do not satisfy the whole
frozen gate set.

The failed gates were: all five windows positive; annualized weekly Sharpe;
raw weekly PSR; program-level Bonferroni-adjusted PSR; positive-instrument
breadth; instrument concentration; window concentration; return and Sharpe
delta versus the mean-absolute-return comparator. Passing aggregate returns,
cost stress, beta, drawdown, turnover, observation counts, zero-buffer-breach,
weekly concentration, and inverse-volume comparisons cannot override those
failures.

The same workflow's ordinary validation result was `PASS`: ATOS completed
`1605 passed, 7 skipped`, the secret scan reported no leakage, Freqtrade's
canonical baseline and strategy-fix round passed, lookahead status was
`PASS`, and same-run CI equivalence was verified. Software health does not
establish economic edge.

## 6. Safety and side-effect boundary

The outer manifest, capture manifest, evidence, and independent recomputation
all agree:

- `authenticated=false`;
- `contains_account_data=false`;
- `contains_order_data=false`;
- `paper_state=PAPER_CLOSED` and `paper_side_effect=false`;
- `shadow_state=SHADOW_CLOSED` and `shadow_side_effect=false`;
- `live_state=LIVE_FORBIDDEN`.

No credential, account endpoint, private API, order, Paper balance, Shadow
action, Live action, or real-funds effect occurred.

## 7. Closed actions and next admissible work

This closeout removes the one-time C14A workflow input and authority job. The
normal retained-PR notification remains fail-open under `always()` and uses
the requested `sound=8` without exposing its secret endpoint.

The following actions are permanently closed:

1. triggering another C14A H1–H5 authority run;
2. changing C14A's universe, signal, sizing, execution, costs, comparators,
   windows, or gates after inspecting this result;
3. selecting only H1/H2/H4, excluding H3/H5, or otherwise mining the exposed
   windows;
4. describing C14A as profitable, selected, validated edge, Paper-ready,
   Shadow-ready, or Live-ready;
5. enabling account access, private APIs, orders, Paper, Shadow, or Live for
   C14A.

Any next candidate must be separately preregistered, structurally distinct,
disclose the complete observed Phase C history, and define its data and
execution semantics before another authority window is accessed. It must not
be a renamed C14A retune.

`C14A_H1_H5_COMPLETE`

`C14A_ECONOMIC_FAIL`

`RETUNING_NOT_AUTHORIZED`

`AUTHORITATIVE_RERUN_NOT_AUTHORIZED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
