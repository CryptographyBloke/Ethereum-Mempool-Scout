// Typed client for the FastAPI backend (mempool_scout/api.py).

export interface Params {
  warmupMin: number;
  graceMs: number;
}

export interface Overview {
  sessions: number;
  first_ms: number | null;
  last_ms: number | null;
  runtime_hours: number;
  pending_hashes: number;
  pending_fetched: number;
  blocks_stored: number;
  block_range: [number | null, number | null];
  eligible_blocks: number;
  txs: number;
  public_txs: number;
  public_share: number | null;
  router_swaps: number;
  public_router_swaps: number;
  router_swap_public_share: number | null;
  sandwiches: number;
  sandwich_attackers: number;
  sandwich_gross_profit_eth: number;
  sandwich_net_profit_eth: number;
  sandwich_victims_public: number;
  sandwich_victim_public_share: number | null;
  large_swaps_seen: number;
  large_swap_threshold_eth: number;
}

export interface TimePoint {
  bucket_ts: number;
  blocks: number;
  txs: number;
  public_txs: number;
  swaps: number;
  public_swaps: number;
  public_share: number | null;
  swap_public_share: number | null;
}

export interface DelayBin {
  lo_s: number;
  hi_s: number | null;
  count: number;
}

export interface Delay {
  count: number;
  median_s: number | null;
  p90_s: number | null;
  p99_s: number | null;
  bins: DelayBin[];
}

export interface Group {
  swaps: number;
  sandwiched: number;
  rate: number | null;
  ci95: [number, number] | null;
}

export interface Exposure {
  public: Group;
  private: Group;
  test: { z: number; p_value: number } | null;
  relative_risk: number | null;
}

export interface Builder {
  builder_tag: string;
  blocks: number;
  block_share: number;
  txs: number;
  public_txs: number;
  public_share: number | null;
  swaps: number;
  public_swaps: number;
  swap_public_share: number | null;
  sandwiches: number;
}

export interface BlockRow {
  number: number;
  hash: string;
  timestamp: number;
  builder_tag: string;
  fee_recipient: string;
  tx_count: number;
  gas_used: number;
  base_fee: string | null;
  public_txs: number;
  stored_txs: number;
  swaps: number;
  sandwiches: number;
  public_share: number | null;
}

export interface BlockTx {
  hash: string;
  tx_index: number;
  sender: string;
  to_addr: string | null;
  tx_type: number;
  value_wei: string;
  status: number | null;
  gas_used: number | null;
  priority_fee_gwei: number | null;
  is_router_swap: number;
  is_deploy: number;
  first_seen_ms: number | null;
  is_public: number;
  swap_function: string | null;
  eth_notional: number | null;
  sandwich_role: "front-run" | "victim" | "back-run" | null;
  inclusion_delay_s: number | null;
}

export interface SandwichRow {
  victim_hash: string;
  pool: string;
  block_number: number;
  protocol: string;
  front_hash: string;
  back_hash: string;
  attacker: string;
  profit_token: string | null;
  gross_profit: string;
  gross_profit_eth: number | null;
  gas_cost_eth: number | null;
  net_profit_eth: number | null;
  timestamp: number;
  builder_tag: string;
  victim_public: number;
  victim_function: string | null;
  victim_eth_notional: number | null;
}

export interface BlockDetail extends Omit<BlockRow, "public_txs" | "stored_txs" | "swaps" | "public_share" | "sandwiches"> {
  parent_hash: string;
  gas_limit: number;
  received_ms: number;
  txs: BlockTx[];
  sandwiches: SandwichRow[];
}

export interface LargeSwap {
  hash: string;
  router: string;
  protocol: string;
  function: string;
  token_in: string | null;
  token_out: string | null;
  exact_input: number;
  amount_in: string | null;
  amount_out: string | null;
  eth_notional: number;
  seen_ms: number;
  path: string[];
  block_number: number | null;
  tx_index: number | null;
  sandwiched: number;
}

export interface Alert {
  id: number;
  created_ms: number;
  kind: "large_swap" | "deploy" | "sandwich";
  hash: string | null;
  payload: Record<string, unknown>;
}

export interface TxLookup {
  hash: string;
  pending: Record<string, unknown> | null;
  included: Record<string, unknown> | null;
  swap_intents: Record<string, unknown>[];
  sandwiches: SandwichRow[];
}

export interface VantageStat {
  vantage: string;
  sessions: number;
  runtime_hours: number;
  last_heartbeat_ms: number | null;
  endpoints: string | null;
  public_txs: number;
  public_share: number | null;
  public_swaps: number;
  swap_public_share: number | null;
  underestimate_pp: number | null;
  exclusive: number;
  first_seen_share: number | null;
  avg_lag_ms: number | null;
}

export interface VantageReport {
  vantages: string[];
  common_blocks: number;
  txs: number;
  router_swaps: number;
  union: { public_txs: number; public_share: number | null; public_swaps: number; swap_public_share: number | null } | null;
  per_vantage: VantageStat[];
}

export interface Bucket {
  label: string;
  lo: number | null;
  hi: number | null;
  swaps: number;
  sandwiched: number;
  rate: number | null;
  ci95: [number, number] | null;
}

export interface SlippageReport {
  public_router_swaps: number;
  quoted: number;
  quote_coverage: number | null;
  buckets: Bucket[];
  median_tolerance_sandwiched: number | null;
  median_tolerance_other: number | null;
  tight_vs_loose: {
    threshold: number;
    tight: { swaps: number; sandwiched: number; rate: number | null };
    loose: { swaps: number; sandwiched: number; rate: number | null };
    test: { z: number; p_value: number } | null;
  };
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function qs(params?: Partial<Params>, extra: Record<string, string | number | undefined> = {}): string {
  const q = new URLSearchParams();
  if (params?.warmupMin !== undefined) q.set("warmup_min", String(params.warmupMin));
  if (params?.graceMs !== undefined) q.set("grace_ms", String(params.graceMs));
  for (const [k, v] of Object.entries(extra)) if (v !== undefined) q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  overview: (p: Params) => get<Overview>(`/overview${qs(p)}`),
  timeseries: (p: Params, bucketS: number) => get<TimePoint[]>(`/visibility/timeseries${qs(p, { bucket_s: bucketS })}`),
  delay: (p: Params) => get<Delay>(`/visibility/delay${qs(p)}`),
  exposure: (p: Params) => get<Exposure>(`/exposure${qs(p)}`),
  builders: (p: Params) => get<Builder[]>(`/builders${qs(p, { limit: 25 })}`),
  blocks: (p: Params, before?: number) => get<BlockRow[]>(`/blocks${qs({ graceMs: p.graceMs }, { limit: 30, before })}`),
  block: (n: number, p: Params) => get<BlockDetail>(`/blocks/${n}${qs({ graceMs: p.graceMs })}`),
  sandwiches: (p: Params) => get<SandwichRow[]>(`/sandwiches${qs({ graceMs: p.graceMs }, { limit: 100 })}`),
  largeSwaps: (minEth: number) => get<LargeSwap[]>(`/swaps/large${qs(undefined, { min_eth: minEth, limit: 100 })}`),
  alerts: () => get<Alert[]>(`/alerts?limit=30`),
  tx: (hash: string) => get<TxLookup>(`/tx/${hash}`),
  vantages: (p: Params) => get<VantageReport>(`/vantages${qs(p)}`),
  slippage: (p: Params) => get<SlippageReport>(`/slippage${qs(p)}`),
};
