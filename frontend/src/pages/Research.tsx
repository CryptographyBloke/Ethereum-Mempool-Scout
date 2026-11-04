import { api, type Params } from "../api";
import { Meter, RateCompare } from "../components/charts";
import { Card, ChartOrTable, Empty, ErrorState, Loading } from "../components/ui";
import { ago, num, pct } from "../format";
import { useApi } from "../hooks";
import { useI18n } from "../i18n";

/** The measurement-quality and mechanism analyses behind RQ1 and RQ2. */
export function Research({ params }: { params: Params }) {
  const { t } = useI18n();
  const v = useApi(() => api.vantages(params), [params.warmupMin, params.graceMs], 30_000);
  const s = useApi(() => api.slippage(params), [params.warmupMin, params.graceMs], 30_000);

  return (
    <div className="stack">
      <Card
        title={t("How much does one vantage point miss?")}
        subtitle={t("Each collector (node or provider) records its own sightings. On blocks that every vantage observed, the union of all vantages is the best estimate of the public mempool; the gap to it is that vantage's measurement error.")}
      >
        {v.error ? <ErrorState error={v.error} retry={v.reload} /> : !v.data ? <Loading /> : v.data.per_vantage.length < 2 ? (
          <Empty>
            {t("Only one vantage point so far. Add another collector on a different provider:")}
            <pre className="code">mempool-scout collect --mempool-only --fetch-mode hash --vantage provider-b --wss wss://…</pre>
          </Empty>
        ) : (
          <>
            <p className="muted small">
              {t("{blocks} blocks and {txs} transactions observed by all {vantages} vantages. Union:", { blocks: num(v.data.common_blocks), txs: num(v.data.txs), vantages: v.data.vantages.length })} <strong>{pct(v.data.union?.public_share)}</strong> {t("of transactions and")}{" "}
              <strong>{pct(v.data.union?.swap_public_share)}</strong> {t("of router swaps were public.")}
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("Vantage")}</th><th>{t("Endpoint")}</th><th>{t("Status")}</th><th style={{ minWidth: 150 }}>{t("Public share")}</th>
                    <th className="num">{t("Under-estimate")}</th><th className="num">{t("Seen only here")}</th><th className="num">{t("First to see")}</th><th className="num">{t("Median lag")}</th><th className="num">{t("Mean lag")}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="union-row">
                    <td><strong>{t("All (union)")}</strong></td><td className="muted">–</td><td />
                    <td><div className="bar-cell"><Meter value={v.data.union?.public_share ?? null} label={t("Union public share")} /><span className="num">{pct(v.data.union?.public_share)}</span></div></td>
                    <td className="num">–</td><td className="num">–</td><td className="num">–</td><td className="num">–</td><td className="num">–</td>
                  </tr>
                  {v.data.per_vantage.map((p) => {
                    const active = p.last_heartbeat_ms !== null && Date.now() - p.last_heartbeat_ms < 60_000;
                    return (
                      <tr key={p.vantage}>
                        <td>{p.vantage}</td>
                        <td className="muted truncate" title={p.endpoints ?? ""}>{p.endpoints ?? "–"}</td>
                        <td>{active ? <span className="live on"><span className="dot" aria-hidden /> {t("active")}</span> : <span className="muted">{t("stopped {elapsed}", { elapsed: ago(p.last_heartbeat_ms) })}</span>}</td>
                        <td><div className="bar-cell"><Meter value={p.public_share} label={`${p.vantage} ${t("Public share")}`} /><span className="num">{pct(p.public_share)}</span></div></td>
                        <td className="num">{p.underestimate_pp === null ? "–" : `${p.underestimate_pp.toFixed(1)} pp`}</td>
                        <td className="num">{num(p.exclusive)}</td>
                        <td className="num">{pct(p.first_seen_share)}</td>
                        <td className="num">{p.median_lag_ms === null ? "–" : `${Math.round(p.median_lag_ms)} ms`}</td>
                        <td className="num">{p.avg_lag_ms === null ? "–" : `${Math.round(p.avg_lag_ms)} ms`}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="muted small">
              {t("Seen only here: public transactions no other vantage saw. First to see: share of this vantage's sightings where it was earliest. Lag: delay behind the fastest vantage; the mean is pulled up by transactions one vantage saw much later, so read the median first.")}
            </p>
          </>
        )}
      </Card>

      <Card
        title={t("Does a looser slippage tolerance get you sandwiched?")}
        subtitle={t("Each public router swap is quoted against current pool state when first seen. Tolerance = 1 − minimum output ÷ quoted output: the headroom an attacker can take. Rate of being sandwiched per tolerance band, with 95% Wilson intervals.")}
      >
        {s.error ? <ErrorState error={s.error} retry={s.reload} /> : !s.data ? <Loading /> : s.data.quoted === 0 ? (
          <Empty>{t("No quoted swaps yet. Quotes are taken by collectors that ingest full transactions (not")} <code>--fetch-mode hash</code>).</Empty>
        ) : (
          <>
            <ChartOrTable
              chart={
                <RateCompare
                  ariaLabel={t("Sandwich rate by slippage tolerance band")}
                  groups={s.data.buckets.map((b) => ({
                    label: b.label, rate: b.rate, ci: b.ci95,
                    detail: t("{count} of {total} swaps sandwiched", {count: num(b.sandwiched), total: num(b.swaps)}),
                  }))}
                />
              }
              table={
                <table>
                  <thead><tr><th>{t("Tolerance")}</th><th className="num">{t("Swaps")}</th><th className="num">{t("Sandwiched")}</th><th className="num">{t("Rate")}</th><th className="num">{t("95% CI")}</th></tr></thead>
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
              <div><dt>{t("Quoted")}</dt><dd>{t("{count} of {total} public swaps ({coverage})", {count: num(s.data.quoted), total: num(s.data.public_router_swaps), coverage: pct(s.data.quote_coverage)})}</dd></div>
              <div><dt>{t("Median tolerance")}</dt><dd>{t("sandwiched {victims} · others {others}", {victims: pct(s.data.median_tolerance_sandwiched, 2), others: pct(s.data.median_tolerance_other, 2)})}</dd></div>
              <div>
                <dt>{t("Loose vs tight (≥ {threshold}%)", {threshold: (s.data.tight_vs_loose.threshold * 100).toFixed(1)})}</dt>
                <dd>
                  {pct(s.data.tight_vs_loose.loose.rate)} vs {pct(s.data.tight_vs_loose.tight.rate)}
                  {s.data.tight_vs_loose.test ? `, z = ${s.data.tight_vs_loose.test.z.toFixed(2)}, p = ${s.data.tight_vs_loose.test.p_value.toPrecision(2)}` : t(", not enough data for a test")}
                </dd>
              </div>
            </dl>
          </>
        )}
      </Card>

      <Card title={t("Validate the sandwich detector")} subtitle={t("A labelled sample turns the heuristic into a measured instrument: report its precision with a confidence interval.")}>
        <ol className="steps">
          <li>{t("Export a random sample:")} <code>mempool-scout label-sample --db data/scout.sqlite --n 100 --out labels.csv</code></li>
          <li>{t("Open each victim / front / back link on Etherscan and set")} <code>label</code> {t("to")} <code>TP</code> {t("or")} <code>FP</code>.</li>
          <li>{t("Compute precision:")} <code>mempool-scout validate labels.csv</code>, {t("or include it in the report with")} <code>report --labels labels.csv</code>.</li>
        </ol>
      </Card>
    </div>
  );
}
