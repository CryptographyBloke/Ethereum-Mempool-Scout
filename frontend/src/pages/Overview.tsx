import { api, type Params } from "../api";
import { ColumnChart, Legend, LineChart, RateCompare } from "../components/charts";
import { Card, ChartOrTable, Empty, ErrorState, Hash, Loading, StatTile } from "../components/ui";
import { compact, eth, num, pct, time } from "../format";
import { useApi, usePref, type LiveState } from "../hooks";

const BUCKETS = [
  { s: 300, label: "5 min" },
  { s: 3600, label: "1 hour" },
  { s: 86400, label: "1 day" },
];

function fmtBucket(ts: number, bucketS: number): string {
  const d = new Date(ts * 1000);
  if (bucketS >= 86400) return d.toLocaleDateString("en-GB", { month: "short", day: "numeric" });
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function Overview({ params, live }: { params: Params; live: LiveState }) {
  const [bucketS, setBucketS] = usePref("scout.bucket", 300);
  const refresh = 15_000;
  const ov = useApi(() => api.overview(params), [params.warmupMin, params.graceMs, live.blockCount], undefined);
  const ts = useApi(() => api.timeseries(params, bucketS), [params.warmupMin, params.graceMs, bucketS], refresh);
  const delay = useApi(() => api.delay(params), [params.warmupMin, params.graceMs], refresh);
  const exp = useApi(() => api.exposure(params), [params.warmupMin, params.graceMs], refresh);

  if (ov.error) return <ErrorState error={ov.error} retry={ov.reload} />;
  if (!ov.data) return <Loading />;
  const o = ov.data;

  if (o.blocks_stored === 0) {
    return (
      <Card title="No data yet">
        <Empty>
          Start the collector to begin measuring:
          <pre className="code">mempool-scout collect --wss wss://YOUR_NODE --db data/scout.sqlite</pre>
          Blocks appear here within ~12 seconds.
        </Empty>
      </Card>
    );
  }

  return (
    <div className="stack">
      <section className="hero card">
        <div>
          <div className="stat-label">Included transactions first seen in the public mempool</div>
          <div className="hero-value">{pct(o.public_share)}</div>
          {o.eligible_blocks > 0 ? (
            <p className="muted">
              {num(o.public_txs)} of {num(o.txs)} transactions in {num(o.eligible_blocks)} observed blocks. The rest reached
              builders privately (or never reached this node).
            </p>
          ) : (
            <p className="notice">
              Warming up: {num(o.blocks_stored)} blocks stored so far. Blocks count once the collector has been running for{" "}
              {params.warmupMin} min, so its mempool view is complete. Set warm-up to 0 to preview them now.
            </p>
          )}
        </div>
        <div className="stat-grid">
          <StatTile label="Uniswap router swaps seen publicly" value={pct(o.router_swap_public_share)}
            note={`${num(o.public_router_swaps)} of ${num(o.router_swaps)}`} />
          <StatTile label="Sandwich attacks detected" value={num(o.sandwiches)}
            note={`${num(o.sandwich_attackers)} attackers · ${eth(o.sandwich_net_profit_eth)} net of gas`} />
          <StatTile label="Sandwich victims seen publicly" value={pct(o.sandwich_victim_public_share)}
            note={`${num(o.sandwich_victims_public)} of ${num(o.sandwiches)}`} />
          <StatTile label="Pending hashes recorded" value={compact(o.pending_hashes)}
            note={`${o.runtime_hours.toFixed(1)} h across ${o.sessions} session${o.sessions === 1 ? "" : "s"}`} />
        </div>
      </section>

      <Card
        title="Public-mempool share over time"
        subtitle="Share of included transactions whose hash this node saw before the block's timestamp."
        actions={
          <label className="field">
            Bucket
            <select value={bucketS} onChange={(e) => setBucketS(Number(e.target.value))}>
              {BUCKETS.map((b) => <option key={b.s} value={b.s}>{b.label}</option>)}
            </select>
          </label>
        }
      >
        {ts.error ? <ErrorState error={ts.error} retry={ts.reload} /> : !ts.data ? <Loading /> : ts.data.length === 0 ? (
          <Empty>No eligible blocks yet. Blocks within the warm-up window are excluded.</Empty>
        ) : (
          <ChartOrTable
            chart={
              <>
                <Legend items={[{ label: "All transactions", color: "var(--series-1)" }, { label: "Uniswap router swaps", color: "var(--series-2)" }]} />
                <LineChart
                  ariaLabel="Public share of included transactions and of router swaps over time"
                  x={ts.data.map((p) => p.bucket_ts)}
                  formatX={(v) => fmtBucket(v, bucketS)}
                  series={[
                    { key: "all", label: "All transactions", color: "var(--series-1)", values: ts.data.map((p) => p.public_share),
                      detail: (i) => `${num(ts.data![i].public_txs)} / ${num(ts.data![i].txs)}` },
                    { key: "swaps", label: "Router swaps", color: "var(--series-2)", values: ts.data.map((p) => p.swap_public_share),
                      detail: (i) => `${num(ts.data![i].public_swaps)} / ${num(ts.data![i].swaps)}` },
                  ]}
                />
              </>
            }
            table={
              <table>
                <thead><tr><th>Bucket</th><th className="num">Blocks</th><th className="num">Txs</th><th className="num">Public</th><th className="num">Swaps</th><th className="num">Swaps public</th></tr></thead>
                <tbody>
                  {ts.data.map((p) => (
                    <tr key={p.bucket_ts}>
                      <td>{time(p.bucket_ts * 1000)}</td><td className="num">{num(p.blocks)}</td><td className="num">{num(p.txs)}</td>
                      <td className="num">{pct(p.public_share)}</td><td className="num">{num(p.swaps)}</td><td className="num">{pct(p.swap_public_share)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            }
          />
        )}
      </Card>

      <div className="grid-2">
        <Card title="How long public transactions waited" subtitle={delay.data ? `Median ${delay.data.median_s?.toFixed(1) ?? "–"} s · p90 ${delay.data.p90_s?.toFixed(1) ?? "–"} s from first sighting to block timestamp` : undefined}>
          {delay.error ? <ErrorState error={delay.error} /> : !delay.data ? <Loading /> : delay.data.count === 0 ? <Empty>No public transactions yet.</Empty> : (
            <ChartOrTable
              chart={
                <ColumnChart
                  ariaLabel="Histogram of inclusion delay for public transactions"
                  labels={delay.data.bins.map((b) => (b.hi_s === null ? `${b.lo_s}+` : `${b.lo_s}–${b.hi_s}`))}
                  values={delay.data.bins.map((b) => b.count)}
                  formatValue={compact}
                  tooltip={(i) => {
                    const b = delay.data!.bins[i];
                    return <><div className="tooltip-title">{b.hi_s === null ? `≥ ${b.lo_s} s` : `${b.lo_s}–${b.hi_s} s`}</div>{num(b.count)} txs · {pct(b.count / delay.data!.count)}</>;
                  }}
                />
              }
              table={
                <table>
                  <thead><tr><th>Delay (s)</th><th className="num">Txs</th><th className="num">Share</th></tr></thead>
                  <tbody>{delay.data.bins.map((b) => (
                    <tr key={b.lo_s}><td>{b.hi_s === null ? `≥ ${b.lo_s}` : `${b.lo_s}–${b.hi_s}`}</td><td className="num">{num(b.count)}</td><td className="num">{pct(b.count / delay.data!.count)}</td></tr>
                  ))}</tbody>
                </table>
              }
            />
          )}
          <p className="muted small">Seconds, log-spaced bins.</p>
        </Card>

        <Card title="Are public swaps sandwiched more often?" subtitle="Sandwich rate of successful Uniswap router swaps, with 95% Wilson intervals.">
          {exp.error ? <ErrorState error={exp.error} /> : !exp.data ? <Loading /> : (
            <>
              <RateCompare
                ariaLabel="Sandwich rate for publicly visible versus private router swaps"
                groups={[
                  { label: "Seen publicly", rate: exp.data.public.rate, ci: exp.data.public.ci95, detail: `${num(exp.data.public.sandwiched)} of ${num(exp.data.public.swaps)} swaps sandwiched` },
                  { label: "Private", rate: exp.data.private.rate, ci: exp.data.private.ci95, detail: `${num(exp.data.private.sandwiched)} of ${num(exp.data.private.swaps)} swaps sandwiched` },
                ]}
              />
              <dl className="facts">
                <div><dt>Relative risk</dt><dd>{exp.data.relative_risk === null ? "–" : `${exp.data.relative_risk.toFixed(2)}×`}</dd></div>
                <div><dt>z-test</dt><dd>{exp.data.test ? `z = ${exp.data.test.z.toFixed(2)}, p = ${exp.data.test.p_value.toPrecision(2)}` : "not enough data"}</dd></div>
              </dl>
            </>
          )}
        </Card>
      </div>

      <Card title="Live feed" subtitle={live.connected ? "Streaming new blocks and alerts from the collector." : "Waiting for the live stream…"}>
        {live.lastBlock && (
          <p>
            Latest block <a href={`#/blocks/${live.lastBlock.number}`}>{num(live.lastBlock.number)}</a> by {live.lastBlock.builder_tag}:{" "}
            {num(live.lastBlock.tx_count)} txs, {pct(live.lastBlock.public_share)} public, {live.lastBlock.sandwiches} sandwiches.
          </p>
        )}
        {live.alerts.length === 0 ? <Empty>New alerts appear here as they happen.</Empty> : (
          <ul className="feed">
            {live.alerts.map((a) => (
              <li key={a.id}>
                <span className="muted mono">{time(a.created_ms)}</span>
                <span className={`feed-kind kind-${a.kind}`}>{a.kind === "large_swap" ? "Large swap" : a.kind === "sandwich" ? "Sandwich" : "Deploy"}</span>
                <span>
                  {a.kind === "large_swap" && `${Number(a.payload.eth_notional).toFixed(2)} ETH via ${a.payload.function}`}
                  {a.kind === "sandwich" && `block ${a.payload.block} · ${a.payload.gross_profit_eth == null ? "non-WETH pool" : eth(a.payload.gross_profit_eth as number, 4)}`}
                  {a.kind === "deploy" && `${num(a.payload.bytecode_len as number)} bytes of init code`}
                </span>
                <Hash value={a.hash} internal />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
