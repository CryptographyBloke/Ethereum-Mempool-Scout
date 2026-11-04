export const pct = (x: number | null | undefined, digits = 1): string =>
  x === null || x === undefined ? "–" : `${(x * 100).toFixed(digits)}%`;

export const num = (x: number | null | undefined): string =>
  x === null || x === undefined ? "–" : x.toLocaleString("en-US");

export function compact(x: number | null | undefined): string {
  if (x === null || x === undefined) return "–";
  const abs = Math.abs(x);
  if (abs >= 1e9) return `${(x / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(x / 1e6).toFixed(1)}M`;
  if (abs >= 1e4) return `${(x / 1e3).toFixed(1)}K`;
  return x.toLocaleString("en-US");
}

export const eth = (x: number | null | undefined, digits = 3): string =>
  x === null || x === undefined ? "–" : `${x.toFixed(digits)} ETH`;

export const short = (s: string | null | undefined, head = 6, tail = 4): string =>
  !s ? "–" : s.length <= head + tail + 1 ? s : `${s.slice(0, head)}…${s.slice(-tail)}`;

export function time(ms: number | null | undefined): string {
  if (!ms) return "–";
  return new Date(ms).toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function ago(ms: number | null | undefined, now = Date.now()): string {
  if (!ms) return "–";
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const txTypeName: Record<number, string> = {
  0: "legacy",
  1: "access list",
  2: "EIP-1559",
  3: "blob",
  4: "EIP-7702",
};

export const etherscanTx = (h: string) => `https://etherscan.io/tx/${h}`;
export const etherscanAddr = (a: string) => `https://etherscan.io/address/${a}`;
export const etherscanBlock = (n: number) => `https://etherscan.io/block/${n}`;
