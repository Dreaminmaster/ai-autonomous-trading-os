# C12A Fixed-Maturity Basis Carry — Authoritative Result V1

## 1. Final classification

C12A completed its single authorized official-public OKX H1–H5 capture and
immutable artifact upload. The frozen capture failed closed before historical
replay because one required futures exit had no official trade within the
preregistered execution-delay bound. The only valid result is:

- Stage: `C12A_H1_H5_AUTHORITY`
- Classification: `DATA_FAILURE`
- Status: `FAIL`
- Official-public data custody: `PARTIAL_PASS`
- Historical replay: `NOT_STARTED`
- Independent economic recomputation: `NOT_STARTED`
- Economic PASS/FAIL: `NOT_PRODUCED`
- Best-window selection: `NOT_PERFORMED`
- Retuning: `NOT_AUTHORIZED`
- Authoritative rerun: `NOT_AUTHORIZED`
- Execution feasibility: `NOT_ESTABLISHED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This is a valid source-coverage failure under the frozen contract. It is not a
program failure, an economic loss, an economic pass, or evidence of trading
edge. It authorizes no execution mode.

## 2. Exact implementation and one-shot run

- Repository: `Dreaminmaster/ai-autonomous-trading-os`
- Design PR: `#121`
- Design PR head: `d626ceba20f52ba82f50ea4fc2d5a0af7ed29a3a`
- Exact merged design commit: `b6516cf53f610d3cba08ae7b72254d8ead1b9c55`
- Implementation PR: `#122`
- Implementation PR head: `d11cfaac48aabcb2bda558035f62296e90bc14ba`
- Exact merged implementation commit: `5f3d15138e0d35d0edecd22b97038e76d2a6f4d3`
- Authoritative workflow run: `32880189123`
- C12A authority job: `97907561162` (`failure`)
- ATOS test job: `97907560828` (`success`)
- Freqtrade validation job: `97907561105` (`success`)
- Same-run validation-summary job: `97937886451` (`success`)
- Pre-closeout notification job: `97938149823` (`skipped`)
- Workflow URL:
  <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32880189123>
- Authority job URL:
  <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32880189123/job/97907561162>

The authority ran on the exact clean merged implementation commit above. This
was the only C12A authority dispatch. It must not be retriggered, replayed on
the exposed interval, or changed after inspecting the retained result.

## 3. Immutable custody and post-download audit

The retained authority artifact is:

- Artifact ID: `9575697674`
- Name: `c12a-h1-h5-authoritative-32880189123`
- GitHub ZIP digest:
  `sha256:380f596ec59276dc2788f3593a9544dabef86bcf660d5505b9e890952293c1ac`
- Independently computed ZIP SHA-256:
  `380f596ec59276dc2788f3593a9544dabef86bcf660d5505b9e890952293c1ac`
- ZIP size: `265,206,898` bytes
- Created: `2026-08-25T17:56:35Z`
- Scheduled expiry: `2026-09-24T17:56:24Z`

An independent download outside the repository established:

- outer manifest: `232 / 232` files matched exact path, size, and SHA-256;
- zero missing, extra, duplicate, escaping, or symlink entries;
- outer sealed bytes: `473,985,411`;
- retained raw files: `222`;
- retained raw bytes: `251,696,228`;
- normalized files: `7`;
- outer manifest SHA-256:
  `9ec80144cb575d46557bc96b3d52943bc5f3f787761d5cf42d05abbf0132ce0d`;
- checkout binding SHA-256:
  `c710a62a76f13a3691cdfa05a56952ec29de3224b7936dad1bafcfb405dc06c0`;
- capture log SHA-256:
  `052cb290d14ee9fbefe9da03ceac4d850d24e3e55eb7537c073f0a70567a5ee4`;
- full authority-run log SHA-256:
  `2421a4aa152ed4b3e24dbf18a5e1aa3dde9954824bc39eb3364da858aaafb6a9`.

The other retained artifacts from the same exact run also matched their
GitHub digests after independent download:

- `atos-validation` ZIP SHA-256:
  `a47a3e51fe8c2549287ce0ea1895e4df9aa219cbe0f1290b9d7e3e7335379ddd`;
- `freqtrade-validation` ZIP SHA-256:
  `92038add313bd4d37fb5b9f32d7eada85c491ba28d0f4e857a048294f37e1d71`;
- `validation-summary` ZIP SHA-256:
  `ed25ff9ff146277c3f55973c5d060275424fa2c67872f0fe307c22b857ae8d7b`.

The source inventory comprised `38` official futures-chain API manifests,
`38` official futures-chain downloads, and `146` official history-candle API
responses. All retained source records were public and unauthenticated.

## 4. Data failure and exact root cause

The exact capture output was:

```json
{"classification":"DATA_FAILURE","error":"missing futures exit execution: 2024-09-27T07:00:00Z","live_state":"LIVE_FORBIDDEN","status":"FAIL"}
```

The required exit concerned fixed-maturity contract `ETH-USDT-240927`. The
official retained September 2024 futures archive proves the relevant trade
sequence:

- last trade before the required exit: ID `1308565` at
  `2024-09-27T06:59:33.254Z`;
- first trade after the required exit: ID `1308566` at
  `2024-09-27T07:11:19.444Z`.

The preregistered maximum execution delay was `300` seconds. There was
therefore no eligible official trade from `07:00:00Z` through `07:05:00Z`.
The same official archive continues with later records through `07:59`, so
the failure is not a truncated download, parser crash, premature end of file,
or missing manifest. It is a genuine absence of an executable trade inside
the frozen time bound.

The retained raw archive facts are:

- path:
  `capture/raw/okx_historical_futures_chain_download/c12a-futures-ETH-USDT-2024-09.bin`;
- raw archive SHA-256:
  `30f71082eab0bd13e79d31ef49645b6c9311f404c84893eee759b7014886ad71`;
- raw archive size: `2,794,808` bytes;
- associated response-manifest SHA-256:
  `87723396a9265fbd87c5a09a45e54b2ecd5807bc1725165c02ff7bfe07bc15d2`;
- response-manifest size: `500` bytes.

Failing closed is the contractually correct outcome. Substituting an earlier
print, widening the delay after inspection, using a later print, changing the
exit time, or selecting another maturity would be retrospective retuning and
is forbidden.

## 5. Economic result

Capture stopped before replay. Consequently, C12A produced no independent
economic recomputation, pooled result, return, Sharpe, PSR, drawdown,
turnover, comparator, attribution, or gate verdict. No economic PASS or FAIL
exists for this candidate.

The normal validation path in the same run remained healthy: `1,495` tests
passed and `7` were skipped, the secret scan was clean, the same-run
equivalence gate passed, baseline and lookahead checks passed, and Live
remained forbidden. Those software checks do not convert missing frozen
source coverage into an economic observation.

## 6. Safety and side-effect boundary

The audited outer manifest records:

- `authenticated=false`;
- `contains_account_data=false`;
- `contains_order_data=false`;
- `paper_state=PAPER_CLOSED` with no side effects;
- `shadow_state=SHADOW_CLOSED` with no side effects;
- `live_state=LIVE_FORBIDDEN`.

No account endpoint, private API, credential, order, Paper balance, Shadow
action, Live action, or real-funds effect occurred.

## 7. Closed actions and next admissible work

This closeout removes the one-time C12A workflow input and authority job. It
also makes the existing Freqtrade Validation notification job fail-open and
eligible under `if: ${{ always() }}`, so predecessor success, failure,
skipped, and ordinary cancelled results can be reported without changing the
underlying validation conclusion.

The following actions are permanently closed:

1. triggering another C12A H1–H5 authority run;
2. replaying or economically evaluating the retained partial C12A package;
3. widening the execution delay or changing maturity, exit, sizing, costs,
   comparators, windows, or gates after inspecting the failure;
4. describing C12A as profitable, unprofitable, selected, validated edge,
   execution-feasible, Paper-ready, Shadow-ready, or Live-ready;
5. enabling account access, private APIs, orders, Paper, Shadow, or Live for
   C12A.

Any next research candidate must be separately preregistered, structurally
distinct, disclose the complete observed Phase C history, and define its
source-coverage and execution semantics before accessing another frozen
authority window. It must not be a renamed C12A retune.

`C12A_H1_H5_COMPLETE`

`C12A_DATA_FAILURE`

`HISTORICAL_ECONOMIC_RESULT_NOT_PRODUCED`

`RETUNING_NOT_AUTHORIZED`

`AUTHORITATIVE_RERUN_NOT_AUTHORIZED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
