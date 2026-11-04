import { api, type Params } from "../api";
import { ColumnChart, Legend, LineChart, RateCompare } from "../components/charts";
import { Card, ChartOrTable, Empty, ErrorState, Hash, Loading, StatTile } from "../components/ui";
import { compact, eth, num, pct, time } from "../format";
import { useApi, usePref, type LiveState } from "../hooks";
import { useI18n } from "../i18n";

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
  const { t } = useI18n();
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
      <Card title={t("No data yet")}>
        <Empty>
          {t("Start the collector to begin measuring:")}
          <pre className="code">mempool-scout collect --wss wss://YOUR_NODE --db data/scout.sqlite</pre>
          {t("Blocks appear here within ~12 seconds.")}
        </Empty>
      </Card>
    );
  }

  return (
    <div className="stack">
      <section className="hero card">
        <div>
          <div className="stat-label">{t("Included transactions first seen in the public mempool")}</div>
          <div className="hero-value">{pct(o.public_share)}</div>
          {o.eligible_blocks > 0 ? (
            <p className="muted">
              {t("{public} of {total} transactions in {blocks} observed blocks. The rest reached builders privately (or never reached this node).", { public: num(o.public_txs), total: num(o.txs), blocks: num(o.eligible_blocks) })}
            </p>
          ) : (
            <p className="notice">
              {t("Warming up: {blocks} blocks stored so far. Blocks count once the collector has been running for {minutes} min, so its mempool view is complete. Set warm-up to 0 to preview them now.", { blocks: num(o.blocks_stored), minutes: params.warmupMin })}
            </p>
          )}
        </div>
        <div className="stat-grid">
          <StatTile label={t("Uniswap router swaps seen publicly")} value={pct(o.router_swap_public_share)}
            note={`${num(o.public_router_swaps)} of ${num(o.router_swaps)}`} />
          <StatTile label={t("Sandwich attacks detected")} value={num(o.sandwiches)}
            note={t("{count} attackers · {profit} gross", { count: num(o.sandwich_attackers), profit: eth(o.sandwich_gross_profit_eth) })} />
          <StatTile label={t("Sandwich victims seen publicly")} value={pct(o.sandwich_victim_public_share)}
            note={`${num(o.sandwich_victims_public)} of ${num(o.sandwiches)}`} />
          <StatTile label={t("Pending hashes recorded")} value={compact(o.pending_hashes)}
            note={t("{hours} h across {sessions} sessions", { hours: o.runtime_hours.toFixed(1), sessions: o.sessions })} />
        </div>
      </section>

      <Card
        title={t("Public-mempool share over time")}
        subtitle={t("Share of included transactions whose hash this node saw before the block's timestamp.")}
        actions={
          <label className="field">
            {t("Bucket")}
            <select value={bucketS} onChange={(e) => setBucketS(Number(e.target.value))}>
              {BUCKETS.map((b) => <option key={b.s} value={b.s}>{t(b.label)}</option>)}
            </select>
          </label>
        }
      >
        {ts.error ? <ErrorState error={ts.error} retry={ts.reload} /> : !ts.data ? <Loading /> : ts.data.length === 0 ? (
          <Empty>{t("No eligible blocks yet. Blocks within the warm-up window are excluded.")}</Empty>
        ) : (
          <ChartOrTable
            chart={
              <>
                <Legend items={[{ label: t("All transactions"), color: "var(--series-1)" }, { label: t("Uniswap router swaps"), color: "var(--series-2)" }]} />
                <LineChart
                  ariaLabel={t("Public share of included transactions and of router swaps over time")}
                  x={ts.data.map((p) => p.bucket_ts)}
                  formatX={(v) => fmtBucket(v, bucketS)}
                  series={[
                    { key: "all", label: t("All transactions"), color: "var(--series-1)", values: ts.data.map((p) => p.public_share),
                      detail: (i) => `${num(ts.data![i].public_txs)} / ${num(ts.data![i].txs)}` },
                    { key: "swaps", label: t("Router swaps"), color: "var(--series-2)", values: ts.data.map((p) => p.swap_public_share),
                      detail: (i) => `${num(ts.data![i].public_swaps)} / ${num(ts.data![i].swaps)}` },
                  ]}
                />
              </>
            }
            table={
              <table>
                <thead><tr><th>{t("Bucket")}</th><th className="num">{t("Blocks")}</th><th className="num">{t("Txs")}</th><th className="num">{t("Public")}</th><th className="num">{t("Swaps")}</th><th className="num">{t("Swaps public")}</th></tr></thead>
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
        <Card title={t("How long public transactions waited")} subtitle={delay.data ? t("Median {median} s · p90 {p90} s from first sighting to block timestamp", { median: delay.data.median_s?.toFixed(1) ?? "–", p90: delay.data.p90_s?.toFixed(1) ?? "–" }) : undefined}>
          {delay.error ? <ErrorState error={delay.error} /> : !delay.data ? <Loading /> : delay.data.count === 0 ? <Empty>{t("No public transactions yet.")}</Empty> : (
            <ChartOrTable
              chart={
                <ColumnChart
                  ariaLabel={t("Histogram of inclusion delay for public transactions")}
                  labels={delay.data.bins.map((b) => (b.hi_s === null ? `${b.lo_s}+` : `${b.lo_s}–${b.hi_s}`))}
                  values={delay.data.bins.map((b) => b.count)}
                  formatValue={compact}
                  tooltip={(i) => {
                    const b = delay.data!.bins[i];
                    return <><div className="tooltip-title">{b.hi_s === null ? `≥ ${b.lo_s} s` : `${b.lo_s}–${b.hi_s} s`}</div>{t("{count} txs · {share}", { count: num(b.count), share: pct(b.count / delay.data!.count) })}</>;
                  }}
                />
              }
              table={
                <table>
                  <thead><tr><th>{t("Delay (s)")}</th><th className="num">{t("Txs")}</th><th className="num">{t("Share")}</th></tr></thead>
                  <tbody>{delay.data.bins.map((b) => (
                    <tr key={b.lo_s}><td>{b.hi_s === null ? `≥ ${b.lo_s}` : `${b.lo_s}–${b.hi_s}`}</td><td className="num">{num(b.count)}</td><td className="num">{pct(b.count / delay.data!.count)}</td></tr>
                  ))}</tbody>
                </table>
              }
            />
          )}
          <p className="muted small">{t("Seconds, log-spaced bins.")}</p>
        </Card>

        <Card title={t("Are public swaps sandwiched more often?")} subtitle={t("Sandwich rate of successful Uniswap router swaps, with 95% Wilson intervals.")}>
          {exp.error ? <ErrorState error={exp.error} /> : !exp.data ? <Loading /> : (
            <>
              <RateCompare
                ariaLabel={t("Sandwich rate for publicly visible versus private router swaps")}
                groups={[
                  { label: t("Seen publicly"), rate: exp.data.public.rate, ci: exp.data.public.ci95, detail: t("{count} of {total} swaps sandwiched", { count: num(exp.data.public.sandwiched), total: num(exp.data.public.swaps) }) },
                  { label: t("Private"), rate: exp.data.private.rate, ci: exp.data.private.ci95, detail: t("{count} of {total} swaps sandwiched", { count: num(exp.data.private.sandwiched), total: num(exp.data.private.swaps) }) },
                ]}
              />
              <dl className="facts">
                <div><dt>{t("Relative risk")}</dt><dd>{exp.data.relative_risk === null ? "–" : `${exp.data.relative_risk.toFixed(2)}×`}</dd></div>
                <div><dt>{t("z-test")}</dt><dd>{exp.data.test ? `z = ${exp.data.test.z.toFixed(2)}, p = ${exp.data.test.p_value.toPrecision(2)}`  : t("not enough data")}</dd></div>
              </dl>
            </>
          )}
        </Card>
      </div>

      <Card title={t("Live feed")} subtitle={live.connected ? t("Streaming new blocks and alerts from the collector.") : t("Waiting for the live stream…")}>
        {live.lastBlock && (
          <p>
            {t("Latest block {number} by {builder}: {txs} txs, {share} public, {sandwiches} sandwiches.", { number: num(live.lastBlock.number), builder: live.lastBlock.builder_tag, txs: num(live.lastBlock.tx_count), share: pct(live.lastBlock.public_share), sandwiches: live.lastBlock.sandwiches })}
          </p>
        )}
        {live.alerts.length === 0 ? <Empty>{t("New alerts appear here as they happen.")}</Empty> : (
          <ul className="feed">
            {live.alerts.map((a) => (
              <li key={a.id}>
                <span className="muted mono">{time(a.created_ms)}</span>
                <span className={`feed-kind kind-${a.kind}`}>{a.kind === "large_swap" ? t("Large swap") : a.kind === "sandwich" ? t("Sandwich") : t("Deploy")}</span>
                <span>
                  {a.kind === "large_swap" && `${Number(a.payload.eth_notional).toFixed(2)} ETH via ${a.payload.function}`}
                  {a.kind === "sandwich" && t("block {block} · {profit}", { block: String(a.payload.block), profit: a.payload.gross_profit_eth == null ? t("non-WETH pool") : eth(a.payload.gross_profit_eth as number, 4) })}
                  {a.kind === "deploy" && t("{count} bytes of init code", { count: num(a.payload.bytecode_len as number) })}
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
