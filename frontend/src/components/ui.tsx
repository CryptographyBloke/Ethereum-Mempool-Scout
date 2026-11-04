import { useState, type ReactNode } from "react";
import { etherscanAddr, etherscanTx, short } from "../format";
import { useI18n } from "../i18n";

export function Card({ title, subtitle, actions, children, className = "" }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p className="muted">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function StatTile({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  );
}

/** Chart with a "Table" toggle so every value is reachable without colour or hover. */
export function ChartOrTable({ chart, table }: { chart: ReactNode; table: ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  const { t } = useI18n();
  return (
    <div>
      <div className="seg" role="group" aria-label={t("View")}>
        <button aria-pressed={!asTable} onClick={() => setAsTable(false)}>{t("Chart")}</button>
        <button aria-pressed={asTable} onClick={() => setAsTable(true)}>{t("Table")}</button>
      </div>
      {asTable ? <div className="table-wrap">{table}</div> : chart}
    </div>
  );
}

export function Hash({ value, kind = "tx", internal }: { value: string | null | undefined; kind?: "tx" | "addr"; internal?: boolean }) {
  if (!value) return <span className="muted">–</span>;
  const href = internal && kind === "tx" ? `#/tx/${value}` : kind === "tx" ? etherscanTx(value) : etherscanAddr(value);
  return (
    <a className="mono" href={href} title={value} {...(internal ? {} : { target: "_blank", rel: "noreferrer" })}>
      {short(value, 8, 6)}
    </a>
  );
}

export function Badge({ tone, children, icon }: { tone: "public" | "private" | "critical" | "neutral" | "good"; children: ReactNode; icon?: string }) {
  return (
    <span className={`badge badge-${tone}`}>
      {icon && <span aria-hidden>{icon}</span>}
      {children}
    </span>
  );
}

export function Visibility({ isPublic }: { isPublic: boolean }) {
  const { t } = useI18n();
  return isPublic ? <Badge tone="public" icon="●">{t("public")}</Badge> : <Badge tone="private" icon="◆">{t("private")}</Badge>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  const { t } = useI18n();
  return <div className="state" role="status">{t(label)}</div>;
}

export function ErrorState({ error, retry }: { error: Error; retry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="state state-error" role="alert">
      <strong>{t("Could not load data.")}</strong> {error.message}
      {retry && <button className="btn" onClick={retry}>{t("Retry")}</button>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state">{children}</div>;
}
