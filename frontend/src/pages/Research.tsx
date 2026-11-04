import { api, type Params } from "../api";
import { Meter, RateCompare } from "../components/charts";
import { Card, ChartOrTable, Empty, ErrorState, Loading } from "../components/ui";
import { ago, num, pct } from "../format";
import { useApi } from "../hooks";

/** The measurement-quality and mechanism analyses behind RQ1 and RQ2. */
export function Research({ params }: { params: Params }) {
  const v = useApi(() => api.vantages(params), [params.warmupMin, params.graceMs], 30_000);
  const s = useApi(() => api.slippage(params), [params.warmupMin, params.graceMs], 30_000);

  return (
    <div className="stack">
      <Card
        title="How much does one vantage point miss?"
        subtitle="Each collector (node or provider) records its own sightings. On blocks that every vantage observed, the union of all vantages is the best estimate of the public mempool; the gap to it is that vantage's measurement error."
      >
        {v.error ? <ErrorState error={v.error} retry={v.reload} /> : !v.data ? <Loading /> : v.data.per_vantage.length < 2 ? (
          <Empty>
            Only one vantage point so far. Add another collector on a different provider:
            <pre className="code">mempool-scout collect --mempool-only --fetch-mode hash --vantage provider-b --wss wss://…</pre>
          </Empty>
        ) : (
          <>
            <p className="muted small">
              {num(v.data.common_blocks)} blocks and {num(v.data.txs)} transactions observed by all {v.data.vantages.length} vantages.
              Union: <strong>{pct(v.data.union?.public_share)}</strong> of transactions and{" "}
              <strong>{pct(v.data.union?.swap_public_share)}</strong> of router swaps were public.
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Vantage</th><th>Endpoint</th><th>Status</th><th style={{ minWidth: 150 }}>Public share</th>
                    <th className="num">Under-estimate</th><th className="num">Seen only here</th><th className="num">First to see</th><th className="num">Mean lag</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="union-row">
                    <td><strong>All (union)</strong></td><td className="muted">–</td><td />
                    <td><div className="bar-cell"><Meter value={v.data.union?.public_share ?? null} label="Union public share" /><span className="num">{pct(v.data.union?.public_share)}</span></div></td>
                    <td className="num">–</td><td className="num">–</td><td className="num">–</td><td className="num">–</td>
                  </tr>
                  {v.data.per_vantage.map((p) => {
                    const active = p.last_heartbeat_ms !== null && Date.now() - p.last_heartbeat_ms < 60_000;
                    return (
                      <tr key={p.vantage}>
                        <td>{p.vantage}</td>
                        <td className="muted truncate" title={p.endpoints ?? ""}>{p.endpoints ?? "–"}</td>
                        <td>{active ? <span className="live on"><span className="dot" aria-hidden /> active</span> : <span className="muted">stopped {ago(p.last_heartbeat_ms)}</span>}</td>
                        <td><div className="bar-cell"><Meter value={p.public_share} label={`${p.vantage} public share`} /><span className="num">{pct(p.public_share)}</span></div></td>
                        <td className="num">{p.underestimate_pp === null ? "–" : `${p.underestimate_pp.toFixed(1)} pp`}</td>
                        <td className="num">{num(p.exclusive)}</td>
                        <td className="num">{pct(p.first_seen_share)}</td>
                        <td className="num">{p.avg_lag_ms === null ? "–" : `${Math.round(p.avg_lag_ms)} ms`}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="muted small">
              <em>Seen only here</em>: public transactions no other vantage saw. <em>First to see</em>: share of this vantage's
              sightings where it was earliest. <em>Mean lag</em>: average delay behind the fastest vantage.
            </p>
          </>
        )}
      </Card>

      <Card
        title="Does a looser slippage tolerance get you sandwiched?"
        subtitle="Each public router swap is quoted against current pool state when first seen. Tolerance = 1 − minimum output ÷ quoted output: the headroom an attacker can take. Rate of being sandwiched per tolerance band, with 95% Wilson intervals."
      >
        {s.error ? <ErrorState error={s.error} retry={s.reload} /> : !s.data ? <Loading /> : s.data.quoted === 0 ? (
          <Empty>No quoted swaps yet. Quotes are taken by collectors that ingest full transactions (not <code>--fetch-mode hash</code>).</Empty>
        ) : (
          <>
            <ChartOrTable
              chart={
                <RateCompare
                  ariaLabel="Sandwich rate by slippage tolerance band"
                  groups={s.data.buckets.map((b) => ({
                    label: b.label, rate: b.rate, ci: b.ci95,
                    detail: `${num(b.sandwiched)} of ${num(b.swaps)} swaps sandwiched`,
                  }))}
                />
              }
              table={
                <table>
                  <thead><tr><th>Tolerance</th><th className="num">Swaps</th><th className="num">Sandwiched</th><th className="num">Rate</th><th className="num">95% CI</th></tr></thead>
                  <tbody>{s.data.buckets.map((b) => (
                    <tr key={b.label}>
                      <td>{b.label}</td><td className="num">{num(b.swaps)}</td><td className="num">{num(b.sandwiched)}</td>
                      <td className="num">{pct(b.rate)}</td><td className="num">{b.ci95 ? `${pct(b.ci95[0])} – ${pct(b.ci95[1])}` : "–"}</td>
                    </tr>
                  ))}</tbody>
                </table>
              }
            />
            <dl className="facts">
              <div><dt>Quoted</dt><dd>{num(s.data.quoted)} of {num(s.data.public_router_swaps)} public swaps ({pct(s.data.quote_coverage)})</dd></div>
              <div><dt>Median tolerance</dt><dd>sandwiched {pct(s.data.median_tolerance_sandwiched, 2)} · others {pct(s.data.median_tolerance_other, 2)}</dd></div>
              <div>
                <dt>Loose vs tight (≥ {(s.data.tight_vs_loose.threshold * 100).toFixed(1)}%)</dt>
                <dd>
                  {pct(s.data.tight_vs_loose.loose.rate)} vs {pct(s.data.tight_vs_loose.tight.rate)}
                  {s.data.tight_vs_loose.test ? `, z = ${s.data.tight_vs_loose.test.z.toFixed(2)}, p = ${s.data.tight_vs_loose.test.p_value.toPrecision(2)}` : ", not enough data for a test"}
                </dd>
              </div>
            </dl>
          </>
        )}
      </Card>

      <Card title="Validate the sandwich detector" subtitle="A labelled sample turns the heuristic into a measured instrument: report its precision with a confidence interval.">
        <ol className="steps">
          <li>Export a random sample: <code>mempool-scout label-sample --db data/scout.sqlite --n 100 --out labels.csv</code></li>
          <li>Open each victim / front / back link on Etherscan and set <code>label</code> to <code>TP</code> or <code>FP</code>.</li>
          <li>Compute precision: <code>mempool-scout validate labels.csv</code>, or include it in the report with <code>report --labels labels.csv</code>.</li>
        </ol>
      </Card>
    </div>
  );
}
