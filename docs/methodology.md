# Methodology

This document defines every number the dashboard and `mempool-scout report` produce,
so results can be reproduced, criticised and cited.

## Research questions

* **RQ1 — Visibility.** What share of the transactions included in Ethereum blocks
  were visible in the public peer-to-peer mempool before inclusion, and how does
  this differ by transaction type and by block builder?
* **RQ1b — Measurement error.** How much does a single vantage point
  under-estimate public visibility, and how much do vantage points differ in
  what they see and how fast?
* **RQ2 — Exposure.** Are Uniswap swaps that were visible in the public mempool
  sandwiched more often than swaps that were submitted privately?
* **RQ2b — Mechanism.** Among public swaps, does a looser slippage tolerance
  predict being sandwiched?
* **RQ3 — Builders.** How concentrated is block building, and do builders that
  win more blocks include a larger share of private order flow?

## Data collection

The collector (`mempool_scout/collector.py`) keeps one WebSocket connection to an
Ethereum node and runs two subscriptions:

| Stream | What is recorded |
|---|---|
| `newPendingTransactions` | For every announced hash: the local wall-clock time it was first seen (`pending_tx.first_seen_ms`). Optionally the full transaction (sender, fees, calldata length) and decoded swap intent. |
| `newHeads` | For every new block: header fields, all transactions, all receipts, Uniswap V2/V3 `Swap` events, detected sandwiches. |

Hash timestamps are written before any further RPC work, so rate limits or a full
fetch queue never bias the visibility measurement (they only reduce how many
transactions are *decoded*).

Each connection is a **session** (`sessions` table: start time, heartbeat, end
time, vantage label, endpoint host).  Reconnects start a new session, so gaps in
coverage are explicit.

**Vantage points.** Several collectors, each connected to a different node or
provider, can write to the same database.  Each records its own sightings in
`pending_sighting(hash, vantage, first_seen_ms)`; `pending_tx.first_seen_ms` keeps
the earliest sighting over all vantages.  Usually one collector ingests blocks and
the others run `--mempool-only`.  All collectors should run on one host, so they
share one NTP-synchronised clock.

**Clock.** Timestamps come from the collector host's clock.  Run it on a machine
synchronised with NTP; skew shifts every inclusion delay by the same offset.

## Definitions

**Eligible block.** A block whose timestamp falls inside some session, at least
`warmup` after that session started (default 5 min).  Right after start-up the
local mempool view is empty, which would wrongly classify old pending
transactions as private.

**Public transaction.** An included transaction whose hash was first seen, by any
vantage, before `block.timestamp + grace` (default grace 0 s).  The block timestamp is the start
of the slot, roughly when the proposer commits to a block, so a transaction
first seen after it could not have influenced the builder's view of the public
mempool.  Both parameters can be changed in the dashboard and the report.

**Private transaction.** Every other included transaction.  This class mixes
(a) order flow sent directly to builders or through private RPCs (Flashbots
Protect, MEV Blocker, …) and (b) public transactions that never reached our node.
(b) is a measurement error that shrinks with more, better-connected vantage
points (see *Threats to validity*).

**Inclusion delay.** `block.timestamp × 1000 − first_seen_ms` for public transactions.

**Router swap.** A transaction sent to one of the routers in
`mempool_scout/constants.py` whose calldata decodes to at least one swap:
Uniswap V2 Router02 and forks (9 functions), V3 SwapRouter and SwapRouter02
(single/multi-hop, exact in/out, `multicall`), and the Universal Router
(`V2_SWAP_*`, `V3_SWAP_*` commands).

**ETH notional.** For a swap intent, the amount on the WETH side of the trade
(exact amount, or the bound — minimum out / maximum in).  Token-to-token swaps
without WETH have no ETH notional; converting them would need price data.

## Comparing vantage points (RQ1b)

The comparison uses only **common blocks**: blocks whose timestamp lies inside a
warmed-up session of *every* vantage.  On those blocks, with `U` the set of
transactions seen publicly by at least one vantage:

* **Union share** `|U| / txs`, the best available estimate of public visibility;
* **Vantage share** for vantage `v`, and its **under-estimate**
  `union share − vantage share` (percentage points), a lower bound on the error
  of a single-vantage study;
* **Exclusive** sightings: transactions only `v` saw publicly;
* **First to see**: share of `v`'s public sightings where `v` was earliest;
* **Mean lag**: mean of `first_seen(v) − min over vantages(first_seen)`.

## Slippage tolerance (RQ2b)

When a collector first decodes a public exact-input router swap, it quotes the same
trade against current pool state with an `eth_call`: `getAmountsOut` on the
Uniswap V2 (or SushiSwap) router for V2 paths, `quoteExactInput` on Uniswap
QuoterV2 for V3 paths.  With the user's minimum output `amountOutMin`:

    tolerance = 1 − amountOutMin / quoted_output

This is the price impact the user agreed to absorb, so it is an upper bound on
what a sandwich can extract from them.  Swaps are grouped into tolerance bands
(below quote, 0–0.1%, 0.1–0.5%, 0.5–1%, 1–2%, 2–5%, ≥ 5%) and the sandwich rate
of each band is reported with Wilson intervals; *tight* (< 0.5%) and *loose*
swaps are compared with a two-proportion z-test.  Multi-intent transactions use
their loosest leg.

Limitations: quotes use `latest` state, which may be up to one block older than
the state the swap executes against; exact-output swaps and token-to-token swaps
through other venues are not quoted; quotes are only taken by collectors that
fetch full transactions.

## Sandwich detection

Detection uses executed `Swap` events from receipts, so it also sees bots that
call pools through private contracts.  For each block and pool, swaps are
ordered by (transaction index, log index) and a triple
`(front, victim, back)` at positions `i < j < k` is labelled a sandwich if:

1. `front` and `victim` swap in the same direction, `back` in the opposite direction;
2. `front` and `back` share an attacker: same `tx.to` (bot contract) or same `tx.from`;
3. the victim has a different sender and a different `tx.to` from the attacker;
4. the back-run sells approximately what the front-run bought:
   `|sold − bought| / bought ≤ 0.2`.

Each victim is counted once per pool.  **Gross profit** is
`received_in_back − paid_in_front` in the front-run's input token, converted to ETH
only when that token is WETH.  **Net profit** subtracts the gas the front- and
back-run paid (`gasUsed × effectiveGasPrice`).  Direct payments to the builder
(coinbase transfers inside the bot's transaction) are *not* subtracted, because
they require execution traces that most hosted endpoints do not serve.

**Validation.** `mempool-scout label-sample` exports a random sample of detections
with Etherscan links; after labelling each as TP or FP by hand,
`mempool-scout validate` reports the detector's precision with a 95% Wilson
interval, and `report --labels` includes it in the report.

This follows the heuristics of Torres et al. (2021) and Qin et al. (2022) and
inherits their limits: multi-pool or multi-block sandwiches and attackers that
rotate both EOA and contract are missed; unrelated back-to-back trades by one
market maker can produce false positives.

## Statistics

* Proportions are reported with **95% Wilson score intervals**.
* RQ2 compares sandwich rates of public vs private successful router swaps with
  a **two-sided two-proportion z-test** and reports the **relative risk**
  (public rate / private rate).
* All analysis SQL lives in `mempool_scout/analysis.py` and is covered by tests.

## Threats to validity

| Threat | Effect | Mitigation |
|---|---|---|
| Single vantage point | Some public transactions never reach our node → private share is over-estimated | Several vantages in one database; the RQ1b analysis quantifies the remaining error |
| Provider filtering | Hosted RPC endpoints may sample or delay the pending stream | Record the endpoint per session; compare against a self-hosted node |
| Blob transactions | Blob transactions are announced but not broadcast in full, so propagation differs | Report results by transaction type |
| Re-orgs | A block may be replaced | Blocks are stored by height and replaced atomically; affected sandwiches are recomputed |
| Router coverage | Swaps via aggregators, Uniswap V4, Curve, Balancer are not decoded | Treated as non-router transactions; extendable via `--router` and new decoders |
| Heuristic labels | False positives/negatives in sandwich detection | Precision measured on a labelled random sample (`label-sample`, `validate`); recall is not measured |

## Ethics

The tool is strictly read-only: it never signs or sends transactions, and it
uses only data that the Ethereum network makes public.  Addresses are
pseudonymous; the dashboard does not attempt to link them to real-world
identities.  Results should be reported in aggregate.

## Related work

* P. Daian et al., *Flash Boys 2.0: Frontrunning in Decentralized Exchanges, Miner
  Extractable Value, and Consensus Instability*, IEEE S&P 2020.
* C. F. Torres, R. Camino, R. State, *Frontrunner Jones and the Raiders of the Dark
  Forest: An Empirical Study of Frontrunning on the Ethereum Blockchain*, USENIX
  Security 2021.
* K. Qin, L. Zhou, A. Gervais, *Quantifying Blockchain Extractable Value: How dark
  is the forest?*, IEEE S&P 2022.
* B. Weintraub et al., *A Flash(bot) in the Pan: Measuring Maximal Extractable
  Value in Private Pools*, ACM IMC 2022.
* L. Heimbach et al., *Ethereum's Proposer-Builder Separation: Promises and
  Realities*, ACM IMC 2023.
