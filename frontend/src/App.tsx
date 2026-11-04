import { useEffect, useState, type FormEvent } from "react";
import type { Params } from "./api";
import { ago } from "./format";
import { useI18n, type Language } from "./i18n";
import { useLiveStream, usePref, useRoute } from "./hooks";
import { BlockDetail, Blocks } from "./pages/Blocks";
import { Overview } from "./pages/Overview";
import { Builders, LargeSwaps, Sandwiches, TxPage } from "./pages/Tables";

const NAV = [
  { path: "", label: "Overview" },
  { path: "blocks", label: "Blocks" },
  { path: "builders", label: "Builders" },
  { path: "sandwiches", label: "Sandwiches" },
  { path: "swaps", label: "Large swaps" },
];

type Theme = "system" | "light" | "dark";

export function App() {
  const { language, setLanguage, t } = useI18n();
  const route = useRoute();
  const live = useLiveStream();
  const [warmupMin, setWarmup] = usePref("scout.warmup", 5);
  const [graceMs, setGrace] = usePref("scout.grace", 0);
  const [theme, setTheme] = usePref<Theme>("scout.theme", "system");
  const [query, setQuery] = useState("");
  const [, setNow] = useState(Date.now());
  const params: Params = { warmupMin, graceMs };

  useEffect(() => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(id);
  }, []);

  const search = (e: FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (/^0x[0-9a-fA-F]{64}$/.test(q)) window.location.hash = `#/tx/${q.toLowerCase()}`;
    else if (/^\d[\d,]*$/.test(q)) window.location.hash = `#/blocks/${q.replace(/,/g, "")}`;
    setQuery("");
  };

  const [page, arg] = route;
  let body;
  if (!page) body = <Overview params={params} live={live} />;
  else if (page === "blocks" && arg) body = <BlockDetail number={Number(arg)} params={params} />;
  else if (page === "blocks") body = <Blocks params={params} liveCount={live.blockCount} />;
  else if (page === "builders") body = <Builders params={params} />;
  else if (page === "sandwiches") body = <Sandwiches params={params} liveCount={live.blockCount} />;
  else if (page === "swaps") body = <LargeSwaps />;
  else if (page === "tx" && arg) body = <TxPage hash={arg.toLowerCase()} />;
  else body = <p>{t("Page not found.")} <a href="#/">{t("Go to overview")}</a></p>;

  const usesParams = !page || page === "builders";

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">
          <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden>
            <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
            <path d="M16 16l5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            <circle cx="11" cy="11" r="2.5" fill="var(--series-1)" />
          </svg>
          Mempool Scout
        </a>
        <nav aria-label={t("Main")}>
          {NAV.map((n) => (
            <a key={n.path} href={`#/${n.path}`} aria-current={(page ?? "") === n.path ? "page" : undefined}>{t(n.label)}</a>
          ))}
        </nav>
        <form className="search" onSubmit={search} role="search">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("Tx hash or block number")} aria-label={t("Search by transaction hash or block number")} />
        </form>
        <div className="topbar-right">
          <span className={`live ${live.connected ? "on" : "off"}`} title={live.connected ? t("Live stream connected") : t("Live stream disconnected")}>
            <span className="dot" aria-hidden /> {live.connected ? (live.lastBlock ? t("block {number} · {elapsed}", { number: live.lastBlock.number.toLocaleString("en-US"), elapsed: ago(live.lastBlock.timestamp * 1000) }) : t("live")) : t("offline")}
          </span>
          <select aria-label={t("Theme")} value={theme} onChange={(e) => setTheme(e.target.value as Theme)}>
            <option value="system">{t("System")}</option>
            <option value="light">{t("Light")}</option>
            <option value="dark">{t("Dark")}</option>
          </select>
          <select aria-label={t("Language")} value={language} onChange={(e) => setLanguage(e.target.value as Language)}>
            <option value="en">English</option>
            <option value="zh-CN">简体中文</option>
            <option value="zh-TW">繁體中文</option>
          </select>
        </div>
      </header>

      {usesParams && (
        <div className="filters" role="group" aria-label={t("Measurement settings")}>
          <label className="field" title={t("Ignore blocks produced shortly after the collector started, while its mempool view is still filling up.")}>
            {t("Warm-up")}
            <select value={warmupMin} onChange={(e) => setWarmup(Number(e.target.value))}>
              {[0, 5, 15, 30, 60].map((v) => <option key={v} value={v}>{v} min</option>)}
            </select>
          </label>
          <label className="field" title={t("Count a transaction as public if it was seen up to this long after the block timestamp.")}>
            {t("Grace period")}
            <select value={graceMs} onChange={(e) => setGrace(Number(e.target.value))}>
              {[0, 1000, 2000, 4000].map((v) => <option key={v} value={v}>{v / 1000} s</option>)}
            </select>
          </label>
          <span className="muted small">{t("A transaction is public if this node saw its hash before the block timestamp (+ grace).")}</span>
        </div>
      )}

      <main>{body}</main>

      <footer className="muted small">
        {t("Read-only research tool · data from a single vantage point; see")} <a href="https://github.com/CryptographyBloke/Ethereum-Mempool-Scout/blob/main/docs/methodology.md" target="_blank" rel="noreferrer">{t("methodology")}</a> {t("for definitions and limitations.")}
      </footer>
    </div>
  );
}
