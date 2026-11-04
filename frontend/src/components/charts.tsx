import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

/* Shared chart primitives.  Marks follow one spec everywhere: 2px lines, columns
 * <= 24px with a 4px rounded data-end, >= 8px markers with a 2px surface ring,
 * hairline solid gridlines, text in ink tokens (never the series colour). */

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function Tooltip({ x, y, width, children }: { x: number; y: number; width: number; children: ReactNode }) {
  const tipW = 200;
  const left = Math.min(Math.max(x + 14, 0), Math.max(0, width - tipW));
  const flip = x + 14 + tipW > width;
  return (
    <div className="tooltip" style={{ left: flip ? Math.max(0, x - tipW - 14) : left, top: Math.max(0, y - 10), width: tipW }}>
      {children}
    </div>
  );
}

export interface Series {
  key: string;
  label: string;
  color: string; // CSS var, e.g. "var(--series-1)"
  values: (number | null)[];
  detail?: (i: number) => string; // extra tooltip text, e.g. "412 / 980 txs"
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="legend" role="list">
      {items.map((it) => (
        <span key={it.label} className="legend-item" role="listitem">
          <span className="legend-key" style={{ background: it.color }} aria-hidden />
          {it.label}
        </span>
      ))}
    </div>
  );
}

/* ── Line chart (time on x, share 0–100% on y) ─────────────────────────── */
export function LineChart({ x, series, height = 240, formatX, formatY = (v) => `${Math.round(v * 100)}%`,
  yMax = 1, ariaLabel }: {
  x: number[];
  series: Series[];
  height?: number;
  formatX: (v: number) => string;
  formatY?: (v: number) => string;
  yMax?: number;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 40, r: 16, t: 12, b: 26 };
  const iw = Math.max(0, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const n = x.length;
  const sx = (i: number) => m.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  const sy = (v: number) => m.t + ih - (v / yMax) * ih;
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);
  const xTickIdx = useMemo(() => {
    if (n === 0) return [];
    const want = Math.max(2, Math.min(6, Math.floor(iw / 110)));
    const step = Math.max(1, Math.round((n - 1) / (want - 1)));
    const idx: number[] = [];
    for (let i = 0; i < n; i += step) idx.push(i);
    if (idx[idx.length - 1] !== n - 1 && n - 1 - idx[idx.length - 1] > step / 2) idx.push(n - 1);
    return idx;
  }, [n, iw]);

  const path = (vals: (number | null)[]) => {
    let d = "";
    let pen = false;
    vals.forEach((v, i) => {
      if (v === null || v === undefined) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const r = (e.target as SVGRectElement).getBoundingClientRect();
    const px = e.clientX - r.left;
    setHover(n <= 1 ? 0 : Math.max(0, Math.min(n - 1, Math.round((px / iw) * (n - 1)))));
  };

  return (
    <div className="chart" ref={ref} style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} className={t === 0 ? "axis" : "grid"} />
              <text x={m.l - 8} y={sy(t)} className="tick" textAnchor="end" dominantBaseline="middle">{formatY(t)}</text>
            </g>
          ))}
          {xTickIdx.map((i) => (
            <text key={i} x={sx(i)} y={height - 6} className="tick" textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>
              {formatX(x[i])}
            </text>
          ))}
          {series.map((s) => (
            <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {/* isolated points (or a single bucket) still need a visible mark */}
          {series.map((s) =>
            s.values.map((v, i) =>
              v !== null && (s.values[i - 1] ?? null) === null && (s.values[i + 1] ?? null) === null ? (
                <circle key={`${s.key}-${i}`} cx={sx(i)} cy={sy(v)} r={4} fill={s.color} stroke="var(--surface-1)" strokeWidth={2} />
              ) : null,
            ),
          )}
          {hover !== null && (
            <g pointerEvents="none">
              <line x1={sx(hover)} x2={sx(hover)} y1={m.t} y2={m.t + ih} className="crosshair" />
              {series.map((s) =>
                s.values[hover] !== null && s.values[hover] !== undefined ? (
                  <circle key={s.key} cx={sx(hover)} cy={sy(s.values[hover] as number)} r={5} fill={s.color} stroke="var(--surface-1)" strokeWidth={2} />
                ) : null,
              )}
            </g>
          )}
          <rect x={m.l} y={m.t} width={iw} height={ih} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
        </svg>
      )}
      {hover !== null && width > 0 && (
        <Tooltip x={sx(hover)} y={m.t} width={width}>
          <div className="tooltip-title">{formatX(x[hover])}</div>
          {series.map((s) => (
            <div key={s.key} className="tooltip-row">
              <span className="legend-key" style={{ background: s.color }} aria-hidden />
              <span className="tooltip-label">{s.label}</span>
              <span className="tooltip-value">{s.values[hover] === null ? "–" : formatY(s.values[hover] as number)}</span>
              {s.detail && <span className="tooltip-detail">{s.detail(hover)}</span>}
            </div>
          ))}
        </Tooltip>
      )}
    </div>
  );
}

/* ── Column chart (histogram) ───────────────────────────────────────────── */
export function ColumnChart({ labels, values, height = 220, color = "var(--series-1)", formatValue = String,
  tooltip, ariaLabel }: {
  labels: string[];
  values: number[];
  height?: number;
  color?: string;
  formatValue?: (v: number) => string;
  tooltip?: (i: number) => ReactNode;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 44, r: 8, t: 18, b: 26 };
  const iw = Math.max(0, width - m.l - m.r);
  const ih = height - m.t - m.b;
  const max = Math.max(1, ...values);
  const nice = niceMax(max);
  const band = values.length ? iw / values.length : 0;
  const bw = Math.min(24, band * 0.6);
  const sy = (v: number) => m.t + ih - (v / nice) * ih;
  const ticks = [0, 0.5, 1].map((f) => f * nice);
  const peak = values.indexOf(max);

  return (
    <div className="chart" ref={ref} style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.l} x2={m.l + iw} y1={sy(t)} y2={sy(t)} className={t === 0 ? "axis" : "grid"} />
              <text x={m.l - 8} y={sy(t)} className="tick" textAnchor="end" dominantBaseline="middle">{formatValue(t)}</text>
            </g>
          ))}
          {values.map((v, i) => {
            const cx = m.l + band * i + band / 2;
            const top = sy(v);
            const h = m.t + ih - top;
            const r = Math.min(4, h, bw / 2);
            const x0 = cx - bw / 2;
            const d = h <= 0 ? "" :
              `M${x0},${m.t + ih} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x0 + bw - r} Q${x0 + bw},${top} ${x0 + bw},${top + r} V${m.t + ih} Z`;
            return (
              <g key={i}>
                {d && <path d={d} fill={color} opacity={hover === null || hover === i ? 1 : 0.55} />}
                {i === peak && v > 0 && (
                  <text x={cx} y={top - 5} className="tick strong" textAnchor="middle">{formatValue(v)}</text>
                )}
                <text x={cx} y={height - 6} className="tick" textAnchor="middle">{labels[i]}</text>
                <rect x={m.l + band * i} y={m.t} width={band} height={ih} fill="transparent"
                  onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
              </g>
            );
          })}
        </svg>
      )}
      {hover !== null && width > 0 && (
        <Tooltip x={m.l + band * hover + band / 2} y={sy(values[hover])} width={width}>
          {tooltip ? tooltip(hover) : <><div className="tooltip-title">{labels[hover]}</div>{formatValue(values[hover])}</>}
        </Tooltip>
      )}
    </div>
  );
}

function niceMax(v: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const k of [1, 2, 2.5, 5, 10]) if (k * p >= v) return k * p;
  return 10 * p;
}

/* ── Rate comparison: dot + 95% CI whisker per group ────────────────────── */
export function RateCompare({ groups, ariaLabel }: {
  groups: { label: string; rate: number | null; ci: [number, number] | null; detail: string }[];
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const rowH = 44;
  const m = { l: 120, r: 24, t: 8, b: 26 };
  const height = m.t + m.b + rowH * groups.length;
  const iw = Math.max(0, width - m.l - m.r);
  const hi = Math.max(0.01, ...groups.map((g) => g.ci?.[1] ?? g.rate ?? 0));
  const xmax = niceMax(hi * 1.1);
  const sx = (v: number) => m.l + (v / xmax) * iw;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * xmax);
  const fmt = (v: number) => `${(v * 100).toFixed(xmax < 0.05 ? 1 : 0)}%`;

  return (
    <div className="chart" ref={ref} style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={sx(t)} x2={sx(t)} y1={m.t} y2={height - m.b} className={t === 0 ? "axis" : "grid"} />
              <text x={sx(t)} y={height - 6} className="tick" textAnchor="middle">{fmt(t)}</text>
            </g>
          ))}
          {groups.map((g, i) => {
            const cy = m.t + rowH * i + rowH / 2;
            return (
              <g key={g.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <rect x={0} y={cy - rowH / 2} width={width} height={rowH} fill="transparent" />
                <text x={m.l - 12} y={cy} className="tick label" textAnchor="end" dominantBaseline="middle">{g.label}</text>
                {g.ci && (
                  <g stroke="var(--series-1)" strokeWidth={2} strokeLinecap="round">
                    <line x1={sx(g.ci[0])} x2={sx(g.ci[1])} y1={cy} y2={cy} />
                    <line x1={sx(g.ci[0])} x2={sx(g.ci[0])} y1={cy - 6} y2={cy + 6} />
                    <line x1={sx(g.ci[1])} x2={sx(g.ci[1])} y1={cy - 6} y2={cy + 6} />
                  </g>
                )}
                {g.rate !== null && (
                  <>
                    <circle cx={sx(g.rate)} cy={cy} r={hover === i ? 6 : 5} fill="var(--series-1)" stroke="var(--surface-1)" strokeWidth={2} />
                    <text x={sx(g.rate)} y={cy - 12} className="tick strong" textAnchor="middle">{pct1(g.rate)}</text>
                  </>
                )}
                {g.rate === null && <text x={m.l} y={cy} className="tick" dominantBaseline="middle">no data</text>}
              </g>
            );
          })}
        </svg>
      )}
      {hover !== null && width > 0 && (
        <Tooltip x={sx(groups[hover].rate ?? 0)} y={m.t + rowH * hover} width={width}>
          <div className="tooltip-title">{groups[hover].label}</div>
          <div>{groups[hover].detail}</div>
          {groups[hover].ci && <div className="muted">95% CI {pct1(groups[hover].ci![0])} – {pct1(groups[hover].ci![1])}</div>}
        </Tooltip>
      )}
    </div>
  );
}

const pct1 = (v: number) => `${(v * 100).toFixed(1)}%`;

/* ── Thin segmented bar: public vs private share of one block ───────────── */
export function SplitBar({ share, label }: { share: number | null; label: string }) {
  if (share === null) return <span className="muted">–</span>;
  const pub = Math.round(share * 1000) / 10;
  return (
    <div className="splitbar" role="img" aria-label={`${label}: ${pub}% public, ${(100 - pub).toFixed(1)}% private`} title={`${pub}% public · ${(100 - pub).toFixed(1)}% private`}>
      {pub > 0 && <span style={{ width: `${pub}%`, background: "var(--series-1)" }} />}
      {pub < 100 && <span style={{ width: `${100 - pub}%`, background: "var(--series-2)" }} />}
    </div>
  );
}

/* ── Meter: one value against 0–100% ────────────────────────────────────── */
export function Meter({ value, label }: { value: number | null; label: string }) {
  if (value === null) return <span className="muted">–</span>;
  return (
    <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)} aria-label={label}>
      <span style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </div>
  );
}
