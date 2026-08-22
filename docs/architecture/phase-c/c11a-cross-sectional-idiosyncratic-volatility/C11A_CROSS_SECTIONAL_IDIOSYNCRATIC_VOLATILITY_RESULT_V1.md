# C11A Cross-Sectional Idiosyncratic Volatility — Authoritative Result V1

## 1. Final classification

C11A completed its single authorized official-public OKX H1–H5 capture,
strict replay, physically separate independent recomputation, immutable
artifact upload, and post-download custody audit. The only valid result is:

- Stage: `C11A_H1_H5_AUTHORITY`
- Classification: `ECONOMIC_FAIL`
- Status: `FAIL`
- Official-public data custody: `PASS`
- Historical replay: `PASS`
- Independent recomputation: `PASS`
- Historical economic pass: `false`
- Selected policy: `null`
- Shadow eligible: `false`
- Best-window selection: `NOT_PERFORMED`
- Retuning: `NOT_AUTHORIZED`
- Authoritative rerun: `NOT_AUTHORIZED`
- Execution feasibility: `NOT_ESTABLISHED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This is a valid negative economic result, not a data failure and not a program
failure. It establishes no trading edge and authorizes no execution mode.

## 2. Exact implementation and one-shot run

- Repository: `Dreaminmaster/ai-autonomous-trading-os`
- Design PR: `#118`
- Design PR head: `907fcd49f443fc3c8cb7d0d9d8675f245c5cb01c`
- Exact merged design commit: `5787aab66eb06068d93b1f61e17435c3bf4cc7d4`
- Implementation PR: `#119`
- Implementation PR head: `ee469a3040a8ba8d9b28e399bfc1f231117dddef`
- Exact merged implementation commit: `55defac09a2001acfa644da9f68e7aa0d8f13caa`
- Authoritative workflow run: `32566697392`
- C11A authority job: `97016244490`
- ATOS test job: `97016244251` (`success`)
- Workflow URL: <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32566697392>
- Authority job URL: <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32566697392/job/97016244490>

The checkout binding records the requested implementation SHA and observed
repository head as the same exact commit and records a clean tracked
worktree. Capture started at `2026-08-22T10:06:00Z` and completed at
`10:22:40Z`. Replay and independent recomputation completed at `10:23:51Z`;
the immutable artifact upload completed at `10:23:57Z`; the authority job
finished successfully at `10:23:59Z`.

This was the only C11A authority dispatch. It must not be retriggered,
replayed on the same exposed interval, or altered after inspecting the result.

## 3. Immutable custody and post-download audit

The retained artifact is:

- Artifact ID: `9474465568`
- Name: `c11a-h1-h5-authoritative-32566697392`
- GitHub ZIP digest: `sha256:83a0b6ecdcd64c04ef3116cb62e54b819444aa7a70cada45266381c81411edbb`
- Independently computed ZIP SHA-256: `83a0b6ecdcd64c04ef3116cb62e54b819444aa7a70cada45266381c81411edbb`
- ZIP size: `23,981,108` bytes
- Created: `2026-08-22T10:23:57Z`
- Scheduled expiry: `2026-09-21T10:23:53Z`

An independent download outside the repository established:

- outer manifest: `2,906 / 2,906` files matched exact path, size, and
  SHA-256, with zero missing, extra, duplicate, escaping, or symlink entries;
- capture manifest: `2,883 / 2,883` files matched under the same checks;
- evidence manifest: `18 / 18` files matched under the same checks;
- outer sealed bytes: `116,427,967`;
- capture sealed bytes: `90,306,812`;
- evidence sealed bytes: `25,622,511`;
- outer manifest SHA-256:
  `97d84912a21629fe82cf83998ef2acc4829d214add8e5796f00f64990bccc248`;
- capture manifest SHA-256:
  `a9bff7a9f45ae7cb3e5f5789b67f415694e64daa9d9acf62b4e00b59c563614b`;
- capture index SHA-256:
  `5a345d5be893155599a6b63a3c20d825d19a08c378737d95930027bbc46edcf4`;
- checkout binding SHA-256:
  `ef040e2a8493c3b3e1040eca0ddb2e77cbc2209f0d3ede47402d57f4d2abfa49`;
- formation universe SHA-256:
  `9ab767e2726a27ba209a38af2cf28f58896a9cc29d16723c10ecfaa5e3f0193c`;
- evidence manifest SHA-256:
  `3ff9583de875ebfa6ee71404777710df994123b45aafd083c13a8b18a0cb9d6f`;
- final classification SHA-256:
  `a3cfa625cb777a7466bdaa6200df1f2d06fdfacb3de2c6be8c7dc81fcba7e86d`;
- pooled summary SHA-256:
  `16d419d1bdddf39f0f1bcbf0ab7c790e7ac6183fa4406c1c3f8b413785a35d1f`;
- pooled independent review SHA-256:
  `8b81923ab91da62fae2dfe1b09eb44ffad2275b17d32ecfa874b71d3e165e877`;
- capture log SHA-256:
  `12ad161dc91fceb380235b814a31e2189260ee08552e64e5300bbedaa6a5f318`;
- evaluator log SHA-256:
  `e3d62ffcaae1b3e33006ae5bf6ccfb8ad0f2302c11b7dd850cbdc974c044f1e9`;
- full authority-job log SHA-256:
  `95afe47c84b4171a5bbddf6ac2243ff402cbe24c3f763ef34739dc7ac7acf5f8`.

The frozen source inventory contained `16 / 16` exact implementation files;
each independently matched the same path, size, and SHA-256 at the exact
implementation commit.

## 4. Public source custody and coverage

The capture index contains `2,844` unique first-attempt records and zero retry
events:

- `764` OKX history-candle API responses;
- `1,808` OKX history mark-price-candle API responses;
- `32` OKX historical-data manifest responses;
- `240` official OKX funding archive downloads.

All `32,264,075` retained raw bytes matched the recorded size and SHA-256.
Every requested and final URL used HTTPS, remained on `openapi.okx.com` or
`static.okx.com`, and retained identical host/path/query semantics. No URL or
query contained authentication, signature, account, or order material.

The six-month formation interval retained `4,368` strictly ordered,
gap-free, confirmed hourly trade rows for each of twelve frozen candidates.
The fixed quote-volume rank independently reselected, in order:

1. `BTC-USDT-SWAP`
2. `ETH-USDT-SWAP`
3. `SOL-USDT-SWAP`
4. `BCH-USDT-SWAP`
5. `DOGE-USDT-SWAP`
6. `XRP-USDT-SWAP`
7. `LTC-USDT-SWAP`
8. `LINK-USDT-SWAP`

For each selected instrument the capture retained:

- `21,841` gap-free confirmed hourly trade rows from
  `2024-01-01T00:00:00Z` through the terminal open at
  `2026-06-29T00:00:00Z`;
- `22,514` gap-free hourly mark rows from `2023-12-03T22:00:00Z` through
  `2026-06-28T23:00:00Z`;
- `2,730` actual realized funding settlements through
  `2026-06-28T16:00:00Z`.

The independent audit matched all `21,840` normalized funding timestamp/rate
pairs to the official one-member monthly CSV archives. It preserved the
actual OKX `funding_time`; observed consecutive intervals ranged from
`28,795` to `28,803` seconds and remained within the frozen eight-hour plus
one-minute tolerance. No funding timestamp was synthesized or snapped to an
hour.

## 5. Independent recomputation

The formation review returned `PASS`, reselected the exact same eight assets,
and records `imports_production_capture_or_selector=false` and
`rank_recompute_match=true`.

The pooled independent review returned `PASS` and records:

- `imports_production_replay=false`;
- `imports_production_signal=false`;
- `imports_production_ledger=false`;
- `imports_production_gate_or_finalizer=false`;
- `pooled_metrics_match=true`;
- `gate_recompute_match=true`;
- `btc_beta_match=true`;
- `reference_final_verdict=ECONOMIC_FAIL`.

The independent implementation reconstructs event types, exact timestamps,
cash/equity paths, costs, funding, returns, statistics, concentration,
comparators, gates, and the final verdict from primitive normalized rows. It
does not merely compare producer constants.

## 6. Economic result

At the expected `1.0x` cost assumption:

- aggregate return: `0.006166906981397257228663436` (`+0.6167%`);
- annualized weekly Sharpe: `0.08580246151230693`;
- weekly PSR: `0.5542506298588398`;
- program-level Bonferroni-adjusted PSR: `0`;
- maximum drawdown: `0.1335740447674885457112033505` (`13.3574%`);
- annualized one-way turnover: `11.02318229760344332579173286`;
- candidate BTC beta: `0.06811817469323657656472533925`;
- price PnL: `57.1887506673405360420592461`;
- funding PnL: `14.70567335512716715931807205`;
- costs: `41.05988911548141705806016867`.

The five fixed window returns at expected cost were:

| Window | Return |
|---|---:|
| H1 | `-0.0261911096735856314959900333` |
| H2 | `0.181379767069185862851882985` |
| H3 | `0.029620868024926237382655653` |
| H4 | `-0.0329692213623419588508227437` |
| H5 | `-0.1210057691511982237444086796` |

The `1.5x` aggregate return was only
`0.001995480956244491970230499`; the `2.0x` aggregate return was negative at
`-0.0021602367909994844693008944`. Three of five windows lost money at every
cost level.

The frozen evaluator rejected C11A on eight required gates:

1. all five windows positive;
2. nonnegative aggregate return at `2.0x` cost;
3. annualized weekly Sharpe;
4. weekly PSR;
5. Bonferroni-adjusted PSR;
6. positive-instrument breadth;
7. instrument concentration;
8. window concentration.

The largest positive instrument contribution share was `0.3684502372`; the
largest positive window share was `0.8596171618`. The strategy passed its
absolute BTC-beta, expected/stressed `1.0x` and `1.5x` return, turnover,
drawdown, decision/activity, comparator-delta, weekly concentration, and
zero-equity-buffer-breach checks. Passing those mechanical checks cannot
override any failed required economic gate.

## 7. Closed actions and next admissible work

The following actions are permanently closed:

1. triggering another C11A H1–H5 authority run;
2. replaying or selecting a subset of the exposed H1–H5 result;
3. tuning C11A's volatility horizon, residual construction, universe,
   rebalance, sizing, costs, comparators, or gates after inspection;
4. describing C11A as profitable, selected, validated edge,
   execution-feasible, Paper-ready, Shadow-ready, or Live-ready;
5. enabling account access, private APIs, orders, Paper, Shadow, or Live for
   C11A.

The one-time C11A dispatch input and authority job are removed in this
closeout. Any next research candidate must be separately preregistered and
structurally distinct, disclose the complete observed Phase C history, and
must not be a renamed C11A volatility-rank retune. A different economic
mechanism and frozen evidence contract are required before any new data
authority.

`C11A_H1_H5_COMPLETE`

`C11A_ECONOMIC_FAIL`

`HISTORICAL_EDGE_NOT_ESTABLISHED`

`RETUNING_NOT_AUTHORIZED`

`AUTHORITATIVE_RERUN_NOT_AUTHORIZED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
