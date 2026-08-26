# C13A Cross-Sectional Lottery-Demand Reversal — Authoritative Result V1

## 1. Final classification

C13A completed its single authorized official-public OKX H1–H5 capture,
strict replay, physically separate recomputation, and immutable artifact
upload. Data custody and independent recomputation passed, but the frozen
candidate failed its preregistered economic gates. The only valid result is:

- Stage: `C13A_H1_H5_FINAL_CLASSIFICATION`
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
- Design PR: `#124`
- Design PR head: `1178918c5f31cb1f632ef8e25ce1028ee9408f8b`
- Exact merged design commit:
  `469020a5e496df23ddd7474c7fdd23cc5a6d21f5`
- Implementation PR: `#125`
- Implementation PR head:
  `971fa3add76557e6011cd15c9fd0c8607323c9f4`
- Exact merged implementation commit:
  `cb401b3f6d9b0e71ef9beb887329962bae9eccbc`
- Authoritative workflow run: `32975423962`
- C13A authority job: `98198866199` (`success`)
- ATOS test job: `98198866231` (`success`)
- Freqtrade validation job: `98198865827` (`success`)
- Same-run validation-summary job: `98228864283` (`success`)
- Notification job: `98229033540` (`success`; correctly suppressed for the
  non-PR authority dispatch)
- Workflow URL:
  <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32975423962>
- Authority job URL:
  <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32975423962/job/98198866199>

The authority ran on the exact clean merged implementation commit above. It
was the only C13A authority dispatch. It must never be retriggered, replayed on
the exposed interval, or altered after inspecting this result.

## 3. Immutable custody and independent audit

The retained authority artifact is:

- Artifact ID: `9609883268`
- Name: `c13a-h1-h5-authoritative-32975423962`
- GitHub ZIP digest:
  `sha256:d1f6afe6e101b253b4cc7b2ef35681c8478369dd76bcc6644bedb4d88ccb83c5`
- Independently computed ZIP SHA-256:
  `d1f6afe6e101b253b4cc7b2ef35681c8478369dd76bcc6644bedb4d88ccb83c5`
- ZIP size: `21,593,915` bytes
- Created: `2026-08-26T13:55:11Z`
- Scheduled expiry: `2026-09-25T13:55:07Z`

An independent download outside the repository established:

- outer manifest: `2664 / 2664` files matched exact path, size, and SHA-256;
- outer sealed bytes: `103,236,241`;
- outer manifest SHA-256:
  `fba91ed2daf302626a53ee0b7a70385d43293c77dc41e73b0ad3a01376853486`;
- capture manifest: `2642 / 2642` files verified;
- capture manifest SHA-256:
  `57d3ed01274f7a7894ca1e4a0b876bda0e783dc5830145f7ffa65854350dbd87`;
- capture index SHA-256:
  `a0c9a583ac19e9b111d78a3825f0476fdf3ed79fe49cd2e584d8dcfaa8eeed00`;
- checkout binding SHA-256:
  `6f957e8d4f67aef8b8fe1d5e2afec25170315fb177f039d107ec16f4f2a47b44`;
- evidence manifest: `17 / 17` files verified;
- evidence manifest SHA-256:
  `176c73531a9bdac5293abb9352d905615ab8292daf74bb2e3b405dc2b14c67f5`;
- frozen source inventory: `16 / 16` files matched exact `git show` bytes at
  the implementation commit;
- source inventory SHA-256:
  `9737625f56c0b33a14030a74d9583486c5989177f127eda44971774111f7860e`;
- capture log SHA-256:
  `74fcdde12901424f60bc246ef9bde96a5476ec9ecbaee50b0bee4f8042f31c74`;
- evaluation log SHA-256:
  `e74bbb0ad1fd6d2fd12a25cc9ff5460ca3b546e295cd38da22b7b86a644c26a0`;
- full authority-job log SHA-256:
  `564389f16bdb9366f6ad3b829dabad1cba767e54f8a66bdb5cda34230f138a00`;
- full run-log ZIP SHA-256:
  `2a86bd74868b262b27dc2429aba4f3835f02ae84e0f4212ffe102c11abf07b38`.

The other same-run artifact ZIPs also matched their GitHub digests after
independent download:

- `atos-validation`:
  `5aa7c05f9f8ae24714f99028582ea3e55ff1bd4704dc0af77e8c79e804f17cf6`;
- `freqtrade-validation`:
  `eaca1fd7103e2310136df1a8bb8c1d4f190152846aab15b8b5850727516a22b8`;
- `validation-summary`:
  `38bd292b3ee40a81766eed1f9a416192cf1a8c27b4ab6e4ebcc9c99a75302b1f`.

## 4. Official data coverage

The capture retained `2616` raw response records totalling `27,311,129`
bytes:

- `32` official historical-data API records;
- `240` official historical-download records;
- `592` official history-candle API records;
- `1752` official historical mark-price-candle API records.

The exact fixed universe was BTC, ETH, SOL, BCH, DOGE, XRP, LTC, and LINK
USDT perpetual swaps. Strict normalization produced:

- `22,033` trade rows per instrument, `176,264` total;
- `21,841` mark rows per instrument, `174,728` total;
- `2,730` funding settlements per instrument, `21,840` total.

The retained funding timestamps were independently parsed again after
download. Every instrument was strictly ordered and duplicate-free, covering
its actual official first settlement near `2024-01-01T00:00:00Z` through
`2026-06-28T16:00:00Z`. Consecutive gaps were between `28,795` and `28,803`
seconds. The observed seconds were `0` through `8` as supplied by OKX; they
were not snapped to an hour or replaced with synthetic timestamps.

Trade data covered `2023-12-24T00:00:00Z` through
`2026-06-29T01:00:00Z`; mark data covered `2023-12-31T23:00:00Z` through
`2026-06-29T00:00:00Z`; scored H1–H5 windows remained exactly
`2024-01-01T00:00:00Z` through `2026-06-29T00:00:00Z`.

## 5. Independent economic result

The physically separate implementation reported `status=PASS`, with pooled
metrics, BTC beta, and every gate matching production. It imported none of
the production signal, replay, ledger, gate, or finalizer implementations.

At the preregistered `1.0x` cost:

- aggregate return: `-0.0314537466772627067064614708` (`-3.1454%`);
- annualized weekly Sharpe: `-0.4263113868422964`;
- raw weekly PSR: `0.24300280031444327`;
- program-level Bonferroni-adjusted PSR over 628 trials: `0`;
- maximum drawdown: `0.2267142110693375129962792941` (`22.6714%`);
- BTC beta: `-0.04817299223982737581265425129`;
- annualized one-way turnover: `17.97133192410293681282545282`;
- decisions/non-flat directions: `130 / 520`;
- funding settlements: `21,840`;
- equity-buffer breaches/forced closes: `0 / 0`;
- price PnL: `-21.77333191959226996487430460` USDT;
- funding PnL: `-2.261965227828955991321201285` USDT;
- transaction costs: `133.2334362388923075761118236` USDT;
- reconciliation residual:
  `-0.00000000000000000000002489` USDT.

Window returns were H1 `-3.1957%`, H2 `-15.8464%`, H3 `+3.8841%`, H4
`-2.2269%`, and H5 `+1.6579%`. Three of eight instruments had positive net
contribution. The largest positive instrument and window shares were
`0.5897573486325107492964616837` and
`0.7008448845064454168556757605`, both above the frozen `0.35` cap.

Cost stress remained negative:

| Cost | Aggregate return | Annualized weekly Sharpe | Maximum drawdown |
|---|---:|---:|---:|
| `1.0x` | `-3.1454%` | `-0.4263` | `22.6714%` |
| `1.5x` | `-4.4405%` | `-0.6188` | `23.1192%` |
| `2.0x` | `-5.7195%` | `-0.8109` | `23.5650%` |

At `1.0x`, the raw seven-day reversal comparator returned `-4.5470%`, while
the total-volatility comparator returned `-2.7760%`. C13A beat the raw
reversal on return and Sharpe but had worse drawdown. It failed all four
required comparisons against total volatility.

The failed gates were: all five windows positive; aggregate returns at
`1.0x`, `1.5x`, and `2.0x`; annualized Sharpe; raw and adjusted PSR; maximum
drawdown; positive-instrument breadth; instrument and window concentration;
return, Sharpe, drawdown, and turnover against total volatility; and drawdown
against raw reversal. Passing beta, turnover cap, observation counts,
zero-buffer-breach, and weekly-concentration gates cannot override those
failures.

The same workflow's ordinary validation path also passed: `1551` tests
passed and `7` were skipped, the secret scan was clean, same-run CI
equivalence passed, and production lookahead checks passed. These software
checks establish implementation health, not economic edge.

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

This closeout removes the one-time C13A workflow input and authority job. The
normal retained-PR notification remains fail-open under `always()` and uses
the requested `sound=8` without exposing its secret endpoint.

The following actions are permanently closed:

1. triggering another C13A H1–H5 authority run;
2. changing C13A's universe, signal, sizing, execution, costs, comparators,
   windows, or gates after inspecting this result;
3. selecting only H3/H5, excluding H2, or otherwise mining the exposed
   windows;
4. describing C13A as profitable, selected, validated edge, Paper-ready,
   Shadow-ready, or Live-ready;
5. enabling account access, private APIs, orders, Paper, Shadow, or Live for
   C13A.

Any next candidate must be separately preregistered, structurally distinct,
disclose the complete observed Phase C history, and define its data and
execution semantics before another authority window is accessed. It must not
be a renamed C13A retune.

`C13A_H1_H5_COMPLETE`

`C13A_ECONOMIC_FAIL`

`RETUNING_NOT_AUTHORIZED`

`AUTHORITATIVE_RERUN_NOT_AUTHORIZED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
