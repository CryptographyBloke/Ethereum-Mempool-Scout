import { useState } from "react";
import { api, type Params } from "../api";
import { Meter } from "../components/charts";
import { Badge, Card, Empty, ErrorState, Hash, Loading, Visibility } from "../components/ui";
import { eth, num, pct, short, time } from "../format";
import { useApi } from "../hooks";

export function Builders({ params }: { params: Params }) {
  const r = useApi(() => api.builders(params), [params.warmupMin, params.graceMs], 30_000);
  if (r.error) return <ErrorState error={r.error} retry={r.reload} />;
  if (!r.data) return <Loading />;
  return (
    <Card title="Block builders" subtitle="Builders are identified by the block's extraData tag. Low public share means the builder relies on private order flow.">
      {r.data.length === 0 ? <Empty>No eligible blocks yet.</Empty> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Builder</th><th className="num">Blocks</th><th className="num">Block share</th><th style={{ minWidth: 150 }}>Public tx share</th><th className="num">Router swaps</th><th className="num">Swaps public</th><th className="num">Sandwiches</th></tr>
            </thead>
            <tbody>
              {r.data.map((b) => (
                <tr key={b.builder_tag}>
                  <td className="truncate" title={b.builder_tag}>{b.builder_tag}</td>
                  <td className="num">{num(b.blocks)}</td>
                  <td className="num">{pct(b.block_share)}</td>
                  <td><div className="bar-cell"><Meter value={b.public_share} label={`${b.builder_tag} public share`} /><span className="num">{pct(b.public_share, 0)}</span></div></td>
                  <td className="num">{num(b.swaps)}</td>
                  <td className="num">{pct(b.swap_public_share, 0)}</td>
                  <td className="num">{num(b.sandwiches)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function Sandwiches({ params, liveCount }: { params: Params; liveCount: number }) {
  const r = useApi(() => api.sandwiches(params), [params.graceMs, liveCount]);
  if (r.error) return <ErrorState error={r.error} retry={r.reload} />;
  if (!r.data) return <Loading />;
  return (
    <Card title="Detected sandwich attacks" subtitle="Front-run and back-run by the same bot around a victim swap in the same pool. Profit is shown when the pool's profit token is WETH; net profit subtracts the gas of the front- and back-run, but not direct payments to the builder.">
      {r.data.length === 0 ? <Empty>No sandwiches detected yet.</Empty> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Block</th><th>Time</th><th>Victim</th><th>Victim visibility</th><th>Victim swap</th><th>Attacker</th><th>Front / back</th><th className="num">Gross profit</th><th className="num">Gas</th><th className="num">Net profit</th><th>Builder</th></tr>
            </thead>
            <tbody>
              {r.data.map((s) => (
                <tr key={`${s.victim_hash}-${s.pool}`}>
                  <td><a href={`#/blocks/${s.block_number}`}>{num(s.block_number)}</a></td>
                  <td className="muted">{time(s.timestamp * 1000)}</td>
                  <td><Hash value={s.victim_hash} internal /></td>
                  <td><Visibility isPublic={!!s.victim_public} /></td>
                  <td className="truncate">{s.victim_function ?? <span className="muted">unknown router</span>}{s.victim_eth_notional ? ` · ${s.victim_eth_notional.toFixed(2)} ETH` : ""}</td>
                  <td><Hash value={s.attacker} kind="addr" /></td>
                  <td className="mono small"><Hash value={s.front_hash} internal /> / <Hash value={s.back_hash} internal /></td>
                  <td className="num">{s.gross_profit_eth === null ? <span className="muted">non-WETH</span> : eth(s.gross_profit_eth, 4)}</td>
                  <td className="num muted">{s.gas_cost_eth === null ? "–" : eth(s.gas_cost_eth, 4)}</td>
                  <td className="num">{s.net_profit_eth === null ? "–" : eth(s.net_profit_eth, 4)}</td>
                  <td className="truncate" title={s.builder_tag}>{s.builder_tag}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function LargeSwaps() {
  const [minEth, setMinEth] = useState(10);
  const r = useApi(() => api.largeSwaps(minEth), [minEth], 15_000);
  return (
    <Card title="Large swaps seen in the mempool" subtitle="Decoded from pending router calldata. Size is measured on the WETH side of the trade."
      actions={
        <label className="field">Minimum
          <select value={minEth} onChange={(e) => setMinEth(Number(e.target.value))}>
            {[1, 5, 10, 50, 100].map((v) => <option key={v} value={v}>{v} ETH</option>)}
          </select>
        </label>
      }>
      {r.error ? <ErrorState error={r.error} retry={r.reload} /> : !r.data ? <Loading /> : r.data.length === 0 ? <Empty>No swaps above {minEth} ETH yet.</Empty> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Seen</th><th>Hash</th><th>Router</th><th>Function</th><th>Path</th><th className="num">Size</th><th>Outcome</th></tr>
            </thead>
            <tbody>
              {r.data.map((s) => (
                <tr key={s.hash}>
                  <td className="muted">{time(s.seen_ms)}</td>
                  <td><Hash value={s.hash} internal /></td>
                  <td className="truncate">{s.router}</td>
                  <td className="truncate">{s.function}</td>
                  <td className="mono small">{s.path.map((p) => short(p, 6, 4)).join(" → ")}</td>
                  <td className="num">{eth(s.eth_notional, 2)}</td>
                  <td>
                    {s.block_number === null ? <span className="muted">not included (yet)</span> : (
                      <>
                        <a href={`#/blocks/${s.block_number}`}>block {num(s.block_number)}</a>{" "}
                        {s.sandwiched > 0 && <Badge tone="critical" icon="▲">sandwiched</Badge>}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function TxPage({ hash }: { hash: string }) {
  const r = useApi(() => api.tx(hash), [hash]);
  if (r.error) return <ErrorState error={r.error} />;
  if (!r.data) return <Loading />;
  const { pending, included, swap_intents, sandwiches } = r.data;
  const firstSeen = pending?.first_seen_ms as number | undefined;
  return (
    <div className="stack">
      <Card title="Transaction" subtitle={<span className="mono break">{hash}</span>}>
        <dl className="facts">
          <div><dt>Public mempool</dt><dd>{firstSeen ? <>first seen {time(firstSeen)}</> : <Badge tone="private" icon="◆">never seen by this node</Badge>}</dd></div>
          <div><dt>Included</dt><dd>{included ? <a href={`#/blocks/${included.block_number}`}>block {num(included.block_number as number)}, position {String(included.tx_index)}</a> : "not in a stored block"}</dd></div>
          {included && <div><dt>Status</dt><dd>{included.status === 1 ? "success" : included.status === 0 ? "reverted" : "–"}</dd></div>}
          {included?.priority_fee_gwei != null && <div><dt>Priority fee</dt><dd>{(included.priority_fee_gwei as number).toFixed(3)} gwei</dd></div>}
          <div><dt>Etherscan</dt><dd><Hash value={hash} /></dd></div>
        </dl>
      </Card>
      {swap_intents.length > 0 && (
        <Card title="Decoded swap intent">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Function</th><th>Router</th><th>Token in</th><th>Token out</th><th>Exact</th><th className="num">ETH size</th></tr></thead>
              <tbody>{swap_intents.map((s, i) => (
                <tr key={i}>
                  <td>{String(s.function)}</td><td>{String(s.router)}</td>
                  <td><Hash value={s.token_in as string} kind="addr" /></td><td><Hash value={s.token_out as string} kind="addr" /></td>
                  <td>{s.exact_input ? "input" : "output"}</td><td className="num">{s.eth_notional == null ? "–" : eth(s.eth_notional as number, 3)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Card>
      )}
      {sandwiches.length > 0 && (
        <Card title="Sandwich involvement">
          <ul className="feed">{sandwiches.map((s) => (
            <li key={s.pool + s.victim_hash}>
              <Badge tone="critical" icon="▲">{s.victim_hash === hash ? "victim" : s.front_hash === hash ? "front-run" : "back-run"}</Badge>
              <span>pool <Hash value={s.pool} kind="addr" />, attacker <Hash value={s.attacker} kind="addr" /></span>
              <span>{s.gross_profit_eth == null ? "" : eth(s.gross_profit_eth, 4)}</span>
            </li>
          ))}</ul>
        </Card>
      )}
    </div>
  );
}
