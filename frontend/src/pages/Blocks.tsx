import { useEffect, useMemo, useState } from "react";
import { api, type BlockRow, type BlockTx, type Params } from "../api";
import { Legend, SplitBar } from "../components/charts";
import { Badge, Card, Empty, ErrorState, Hash, Loading, StatTile, Visibility } from "../components/ui";
import { etherscanBlock, num, pct, short, time, txTypeName } from "../format";
import { useApi } from "../hooks";

export function Blocks({ params, liveCount }: { params: Params; liveCount: number }) {
  const first = useApi(() => api.blocks(params), [params.graceMs, liveCount]);
  const [older, setOlder] = useState<BlockRow[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  useEffect(() => setOlder([]), [params.graceMs]);

  if (first.error) return <ErrorState error={first.error} retry={first.reload} />;
  if (!first.data) return <Loading />;
  const rows = [...first.data, ...older.filter((o) => !first.data!.some((f) => f.number === o.number))];

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const more = await api.blocks(params, rows[rows.length - 1]?.number);
      setOlder((o) => [...o, ...more]);
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <Card title="Recent blocks" subtitle="Each row shows how much of the block was visible in the public mempool before inclusion."
      actions={<Legend items={[{ label: "Public", color: "var(--series-1)" }, { label: "Private", color: "var(--series-2)" }]} />}>
      {rows.length === 0 ? <Empty>No blocks yet.</Empty> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Block</th><th>Time</th><th>Builder</th><th className="num">Txs</th><th style={{ minWidth: 160 }}>Public / private</th><th className="num">Swaps</th><th className="num">Sandwiches</th></tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.number}>
                  <td><a href={`#/blocks/${b.number}`}>{num(b.number)}</a></td>
                  <td className="muted">{time(b.timestamp * 1000)}</td>
                  <td className="truncate" title={b.builder_tag}>{b.builder_tag}</td>
                  <td className="num">{num(b.tx_count)}</td>
                  <td><div className="bar-cell"><SplitBar share={b.public_share} label={`Block ${b.number}`} /><span className="num">{pct(b.public_share, 0)}</span></div></td>
                  <td className="num">{num(b.swaps)}</td>
                  <td className="num">{b.sandwiches > 0 ? <Badge tone="critical" icon="▲">{b.sandwiches}</Badge> : <span className="muted">0</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length >= 30 && (
        <button className="btn" onClick={loadMore} disabled={loadingMore}>{loadingMore ? "Loading…" : "Load older blocks"}</button>
      )}
    </Card>
  );
}

type Filter = "all" | "private" | "public" | "swaps" | "sandwich";

export function BlockDetail({ number, params }: { number: number; params: Params }) {
  const b = useApi(() => api.block(number, params), [number, params.graceMs]);
  const [filter, setFilter] = useState<Filter>("all");
  const txs = useMemo(() => {
    const all = b.data?.txs ?? [];
    const keep: Record<Filter, (t: BlockTx) => boolean> = {
      all: () => true,
      private: (t) => !t.is_public,
      public: (t) => !!t.is_public,
      swaps: (t) => !!t.is_router_swap,
      sandwich: (t) => t.sandwich_role !== null,
    };
    return all.filter(keep[filter]);
  }, [b.data, filter]);

  if (b.error) return <ErrorState error={b.error} retry={b.reload} />;
  if (!b.data) return <Loading />;
  const d = b.data;
  const pub = d.txs.filter((t) => t.is_public).length;

  return (
    <div className="stack">
      <p><a href="#/blocks">← All blocks</a></p>
      <Card title={`Block ${num(d.number)}`} subtitle={<>{time(d.timestamp * 1000)} · built by <strong>{d.builder_tag}</strong> · <a href={etherscanBlock(d.number)} target="_blank" rel="noreferrer">Etherscan ↗</a></>}>
        <div className="stat-grid">
          <StatTile label="Transactions" value={num(d.tx_count)} />
          <StatTile label="Seen publicly first" value={pct(d.txs.length ? pub / d.txs.length : null)} note={`${num(pub)} of ${num(d.txs.length)}`} />
          <StatTile label="Router swaps" value={num(d.txs.filter((t) => t.is_router_swap).length)} />
          <StatTile label="Sandwiches" value={num(d.sandwiches.length)} />
        </div>
        <p className="muted small mono">Fee recipient {short(d.fee_recipient, 10, 8)} · gas {num(d.gas_used)} / {num(d.gas_limit)}</p>
      </Card>

      <Card title="Transactions" actions={
        <div className="seg" role="group" aria-label="Filter transactions">
          {(["all", "public", "private", "swaps", "sandwich"] as Filter[]).map((f) => (
            <button key={f} aria-pressed={filter === f} onClick={() => setFilter(f)}>{f}</button>
          ))}
        </div>
      }>
        {txs.length === 0 ? <Empty>No transactions match this filter.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th className="num">#</th><th>Hash</th><th>From</th><th>To</th><th>Type</th><th>Mempool</th><th className="num">Waited</th><th className="num">Tip (gwei)</th><th>Swap</th><th>Sandwich</th></tr>
              </thead>
              <tbody>
                {txs.map((t) => (
                  <tr key={t.hash} className={t.sandwich_role ? `role-${t.sandwich_role}` : ""}>
                    <td className="num">{t.tx_index}</td>
                    <td><Hash value={t.hash} internal /></td>
                    <td><Hash value={t.sender} kind="addr" /></td>
                    <td><Hash value={t.to_addr} kind="addr" /></td>
                    <td className="muted">{txTypeName[t.tx_type] ?? t.tx_type}</td>
                    <td><Visibility isPublic={!!t.is_public} /></td>
                    <td className="num">{t.inclusion_delay_s !== null && t.is_public ? `${t.inclusion_delay_s.toFixed(1)} s` : "–"}</td>
                    <td className="num">{t.priority_fee_gwei === null ? "–" : t.priority_fee_gwei.toFixed(2)}</td>
                    <td className="truncate">{t.swap_function ?? (t.is_deploy ? "contract deploy" : "")}{t.eth_notional ? ` · ${t.eth_notional.toFixed(2)} ETH` : ""}</td>
                    <td>{t.sandwich_role && <Badge tone={t.sandwich_role === "victim" ? "critical" : "neutral"} icon={t.sandwich_role === "victim" ? "▲" : undefined}>{t.sandwich_role}</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
