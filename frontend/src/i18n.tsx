import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

/** UI translations only; chain identifiers, addresses, hashes and methodology stay unchanged. */
export type Language = "en" | "zh-CN" | "zh-TW";

const entries: [string, string, string][] = [
  [
    "Overview",
    "概览",
    "總覽"
  ],
  [
    "Blocks",
    "区块",
    "區塊"
  ],
  [
    "Builders",
    "构建者",
    "建構者"
  ],
  [
    "Sandwiches",
    "三明治攻击",
    "三明治攻擊"
  ],
  [
    "Large swaps",
    "大额兑换",
    "大額兌換"
  ],
  [
    "Tx hash or block number",
    "交易哈希或区块高度",
    "交易雜湊或區塊高度"
  ],
  [
    "Search by transaction hash or block number",
    "按交易哈希或区块高度搜索",
    "依交易雜湊或區塊高度搜尋"
  ],
  [
    "Main",
    "主导航",
    "主導覽"
  ],
  [
    "Theme",
    "主题",
    "主題"
  ],
  [
    "System",
    "跟随系统",
    "跟隨系統"
  ],
  [
    "Light",
    "浅色",
    "淺色"
  ],
  [
    "Dark",
    "深色",
    "深色"
  ],
  [
    "Language",
    "语言",
    "語言"
  ],
  [
    "Live stream connected",
    "实时连接正常",
    "即時連線正常"
  ],
  [
    "Live stream disconnected",
    "实时连接断开",
    "即時連線中斷"
  ],
  [
    "live",
    "实时",
    "即時"
  ],
  [
    "offline",
    "离线",
    "離線"
  ],
  [
    "block {number} · {elapsed}",
    "区块 {number} · {elapsed}",
    "區塊 {number} · {elapsed}"
  ],
  [
    "Measurement settings",
    "测量参数",
    "測量參數"
  ],
  [
    "Warm-up",
    "预热时间",
    "預熱時間"
  ],
  [
    "Grace period",
    "宽限时间",
    "寬限時間"
  ],
  [
    "Ignore blocks produced shortly after the collector started, while its mempool view is still filling up.",
    "忽略采集器启动后短时间内的区块，此时交易池视图仍在填充。",
    "忽略採集器啟動後短時間內的區塊，此時交易池視圖仍在填充。"
  ],
  [
    "Count a transaction as public if it was seen up to this long after the block timestamp.",
    "允许交易在区块时间戳之后这段时间内被观测到，仍计为公开。",
    "允許交易在區塊時間戳後這段時間內被觀測到，仍計為公開。"
  ],
  [
    "A transaction is public if this node saw its hash before the block timestamp (+ grace).",
    "如果节点在区块时间戳（加宽限时间）之前观测到交易哈希，则将该交易归为公开。",
    "若節點在區塊時間戳（加寬限時間）之前觀測到交易雜湊，則將該交易歸為公開。"
  ],
  [
    "Page not found.",
    "页面不存在。",
    "找不到頁面。"
  ],
  [
    "Go to overview",
    "返回概览",
    "返回總覽"
  ],
  [
    "Read-only research tool · data from a single vantage point; see",
    "只读研究工具 · 数据来自单一观测节点；参见",
    "唯讀研究工具 · 資料來自單一觀測節點；參見"
  ],
  [
    "methodology",
    "研究方法",
    "研究方法"
  ],
  [
    "for definitions and limitations.",
    "了解定义与局限性。",
    "瞭解定義與限制。"
  ],
  [
    "Chart",
    "图表",
    "圖表"
  ],
  [
    "Table",
    "表格",
    "表格"
  ],
  [
    "View",
    "视图",
    "檢視"
  ],
  [
    "public",
    "公开",
    "公開"
  ],
  [
    "private",
    "私有",
    "私有"
  ],
  [
    "Public",
    "公开",
    "公開"
  ],
  [
    "Private",
    "私有",
    "私有"
  ],
  [
    "Loading…",
    "加载中…",
    "載入中…"
  ],
  [
    "Could not load data.",
    "数据加载失败。",
    "資料載入失敗。"
  ],
  [
    "Retry",
    "重试",
    "重試"
  ],
  [
    "No data yet",
    "暂无数据",
    "尚無資料"
  ],
  [
    "Start the collector to begin measuring:",
    "启动采集器后即可开始测量：",
    "啟動採集器後即可開始測量："
  ],
  [
    "Blocks appear here within ~12 seconds.",
    "新区块通常会在约 12 秒内显示。",
    "新區塊通常會在約 12 秒內顯示。"
  ],
  [
    "Included transactions first seen in the public mempool",
    "被公开交易池提前观测到的已打包交易",
    "已打包交易中先被公開交易池觀測到的比例"
  ],
  [
    "{public} of {total} transactions in {blocks} observed blocks. The rest reached builders privately (or never reached this node).",
    "在观测到的 {blocks} 个区块中，{total} 笔交易有 {public} 笔提前可见。其余交易可能经私有渠道提交，或未经过当前节点。",
    "在觀測到的 {blocks} 個區塊中，{total} 筆交易有 {public} 筆提前可見。其餘交易可能經私有管道提交，或未經過目前節點。"
  ],
  [
    "Warming up: {blocks} blocks stored so far. Blocks count once the collector has been running for {minutes} min, so its mempool view is complete. Set warm-up to 0 to preview them now.",
    "预热中：已存储 {blocks} 个区块。采集器运行满 {minutes} 分钟后，这些区块才纳入统计。将预热时间设为 0 可立即预览。",
    "預熱中：已儲存 {blocks} 個區塊。採集器執行滿 {minutes} 分鐘後，這些區塊才納入統計。將預熱時間設為 0 可立即預覽。"
  ],
  [
    "Uniswap router swaps seen publicly",
    "公开可见的 Uniswap 路由兑换",
    "公開可見的 Uniswap 路由兌換"
  ],
  [
    "Sandwich attacks detected",
    "检测到的三明治攻击",
    "偵測到的三明治攻擊"
  ],
  [
    "Sandwich victims seen publicly",
    "公开可见的三明治受害交易",
    "公開可見的三明治受害交易"
  ],
  [
    "Pending hashes recorded",
    "已记录的待确认交易哈希",
    "已記錄的待確認交易雜湊"
  ],
  [
    "{count} attackers · {profit} gross",
    "{count} 个攻击者 · 毛利润 {profit}",
    "{count} 個攻擊者 · 毛利潤 {profit}"
  ],
  [
    "{hours} h across {sessions} sessions",
    "{hours} 小时 · {sessions} 个会话",
    "{hours} 小時 · {sessions} 個工作階段"
  ],
  [
    "{first} of {second}",
    "{first} / {second}",
    "{first} / {second}"
  ],
  [
    "Public-mempool share over time",
    "公开交易池可见率趋势",
    "公開交易池可見率趨勢"
  ],
  [
    "Share of included transactions whose hash this node saw before the block's timestamp.",
    "已打包交易中，本节点在区块时间戳之前观测到哈希的比例。",
    "已打包交易中，本節點在區塊時間戳前觀測到雜湊的比例。"
  ],
  [
    "Bucket",
    "统计周期",
    "統計週期"
  ],
  [
    "5 min",
    "5 分钟",
    "5 分鐘"
  ],
  [
    "1 hour",
    "1 小时",
    "1 小時"
  ],
  [
    "1 day",
    "1 天",
    "1 天"
  ],
  [
    "No eligible blocks yet. Blocks within the warm-up window are excluded.",
    "暂无符合条件的区块，预热窗口内的区块已排除。",
    "尚無符合條件的區塊，預熱期間內的區塊已排除。"
  ],
  [
    "All transactions",
    "全部交易",
    "全部交易"
  ],
  [
    "Uniswap router swaps",
    "Uniswap 路由兑换",
    "Uniswap 路由兌換"
  ],
  [
    "Router swaps",
    "路由兑换",
    "路由兌換"
  ],
  [
    "Public share of included transactions and of router swaps over time",
    "已打包交易和路由兑换的公开可见率趋势",
    "已打包交易與路由兌換的公開可見率趨勢"
  ],
  [
    "Block",
    "区块",
    "區塊"
  ],
  [
    "Time",
    "时间",
    "時間"
  ],
  [
    "Builder",
    "构建者",
    "建構者"
  ],
  [
    "Txs",
    "交易数",
    "交易數"
  ],
  [
    "Swaps",
    "兑换数",
    "兌換數"
  ],
  [
    "Swaps public",
    "公开兑换占比",
    "公開兌換占比"
  ],
  [
    "Delay (s)",
    "延迟（秒）",
    "延遲（秒）"
  ],
  [
    "Share",
    "占比",
    "占比"
  ],
  [
    "How long public transactions waited",
    "公开交易的打包等待时间",
    "公開交易的打包等待時間"
  ],
  [
    "Median {median} s · p90 {p90} s from first sighting to block timestamp",
    "首次观测到被打包：中位数 {median} 秒 · P90 {p90} 秒",
    "首次觀測至打包：中位數 {median} 秒 · P90 {p90} 秒"
  ],
  [
    "No public transactions yet.",
    "暂无公开可见的交易。",
    "尚無公開可見的交易。"
  ],
  [
    "Histogram of inclusion delay for public transactions",
    "公开交易打包延迟直方图",
    "公開交易打包延遲直方圖"
  ],
  [
    "{count} txs · {share}",
    "{count} 笔交易 · {share}",
    "{count} 筆交易 · {share}"
  ],
  [
    "Seconds, log-spaced bins.",
    "单位：秒；采用对数间隔分箱。",
    "單位：秒；採用對數間隔分箱。"
  ],
  [
    "Are public swaps sandwiched more often?",
    "公开兑换更容易遭遇三明治攻击吗？",
    "公開兌換更容易遭遇三明治攻擊嗎？"
  ],
  [
    "Sandwich rate of successful Uniswap router swaps, with 95% Wilson intervals.",
    "成功执行的 Uniswap 路由兑换遭受三明治攻击的比例，含 95% Wilson 置信区间。",
    "成功執行的 Uniswap 路由兌換遭受三明治攻擊的比例，含 95% Wilson 信賴區間。"
  ],
  [
    "Sandwich rate for publicly visible versus private router swaps",
    "公开与私有路由兑换的三明治攻击率",
    "公開與私有路由兌換的三明治攻擊率"
  ],
  [
    "Seen publicly",
    "公开可见",
    "公開可見"
  ],
  [
    "{count} of {total} swaps sandwiched",
    "{total} 笔兑换中 {count} 笔遭攻击",
    "{total} 筆兌換中 {count} 筆遭攻擊"
  ],
  [
    "Relative risk",
    "相对风险",
    "相對風險"
  ],
  [
    "z-test",
    "z 检验",
    "z 檢定"
  ],
  [
    "not enough data",
    "数据不足",
    "資料不足"
  ],
  [
    "Live feed",
    "实时动态",
    "即時動態"
  ],
  [
    "Streaming new blocks and alerts from the collector.",
    "持续接收采集器推送的区块和告警。",
    "持續接收採集器推送的區塊與警示。"
  ],
  [
    "Waiting for the live stream…",
    "正在等待实时数据流…",
    "正在等待即時資料流…"
  ],
  [
    "Latest block {number} by {builder}: {txs} txs, {share} public, {sandwiches} sandwiches.",
    "最新区块 {number}，构建者 {builder}：{txs} 笔交易，公开占比 {share}，三明治攻击 {sandwiches} 次。",
    "最新區塊 {number}，建構者 {builder}：{txs} 筆交易，公開占比 {share}，三明治攻擊 {sandwiches} 次。"
  ],
  [
    "New alerts appear here as they happen.",
    "新告警将在这里实时显示。",
    "新警示將在此即時顯示。"
  ],
  [
    "Large swap",
    "大额兑换",
    "大額兌換"
  ],
  [
    "Sandwich",
    "三明治攻击",
    "三明治攻擊"
  ],
  [
    "Deploy",
    "合约部署",
    "合約部署"
  ],
  [
    "block {block} · {profit}",
    "区块 {block} · {profit}",
    "區塊 {block} · {profit}"
  ],
  [
    "non-WETH pool",
    "非 WETH 池",
    "非 WETH 池"
  ],
  [
    "{count} bytes of init code",
    "初始化代码 {count} 字节",
    "初始化程式碼 {count} 位元組"
  ],
  [
    "Recent blocks",
    "最近区块",
    "最新區塊"
  ],
  [
    "Each row shows how much of the block was visible in the public mempool before inclusion.",
    "逐个区块查看打包前在公开交易池中的可见比例。",
    "逐個區塊查看打包前在公開交易池中的可見比例。"
  ],
  [
    "Public / private",
    "公开 / 私有",
    "公開 / 私有"
  ],
  [
    "No blocks yet.",
    "暂无区块。",
    "尚無區塊。"
  ],
  [
    "Load older blocks",
    "加载更早的区块",
    "載入更早的區塊"
  ],
  [
    "All blocks",
    "全部区块",
    "全部區塊"
  ],
  [
    "built by",
    "构建者",
    "建構者"
  ],
  [
    "Transactions",
    "交易",
    "交易"
  ],
  [
    "Seen publicly first",
    "提前公开可见",
    "提前公開可見"
  ],
  [
    "Fee recipient",
    "手续费接收地址",
    "手續費接收地址"
  ],
  [
    "Filter transactions",
    "筛选交易",
    "篩選交易"
  ],
  [
    "all",
    "全部",
    "全部"
  ],
  [
    "swaps",
    "兑换",
    "兌換"
  ],
  [
    "sandwich",
    "三明治攻击",
    "三明治攻擊"
  ],
  [
    "No transactions match this filter.",
    "没有符合筛选条件的交易。",
    "沒有符合篩選條件的交易。"
  ],
  [
    "Hash",
    "哈希",
    "雜湊"
  ],
  [
    "From",
    "发送方",
    "發送方"
  ],
  [
    "To",
    "接收方",
    "接收方"
  ],
  [
    "Type",
    "类型",
    "類型"
  ],
  [
    "Mempool",
    "交易池",
    "交易池"
  ],
  [
    "Waited",
    "等待时间",
    "等待時間"
  ],
  [
    "Tip (gwei)",
    "小费 (gwei)",
    "小費 (gwei)"
  ],
  [
    "Swap",
    "兑换",
    "兌換"
  ],
  [
    "contract deploy",
    "合约部署",
    "合約部署"
  ],
  [
    "victim",
    "受害交易",
    "受害交易"
  ],
  [
    "front-run",
    "抢跑交易",
    "搶跑交易"
  ],
  [
    "back-run",
    "尾随交易",
    "尾隨交易"
  ],
  [
    "Block builders",
    "区块构建者",
    "區塊建構者"
  ],
  [
    "Builders are identified by the block's extraData tag. Low public share means the builder relies on private order flow.",
    "通过区块 extraData 标签识别构建者。公开可见率较低通常意味着更多交易通过私有订单流提交。",
    "透過區塊 extraData 標籤辨識建構者。公開可見率較低通常代表更多交易經由私有訂單流提交。"
  ],
  [
    "No eligible blocks yet.",
    "暂无符合条件的区块。",
    "尚無符合條件的區塊。"
  ],
  [
    "Block share",
    "区块占比",
    "區塊占比"
  ],
  [
    "Public tx share",
    "公开交易占比",
    "公開交易占比"
  ],
  [
    "Detected sandwich attacks",
    "已检测的三明治攻击",
    "已偵測的三明治攻擊"
  ],
  [
    "Front-run and back-run by the same bot around a victim swap in the same pool. Profit is gross (before gas and builder tips), shown when the pool's profit token is WETH.",
    "同一机器人在同一资金池中对受害兑换实施抢跑和尾随。利润为毛利润（未扣 Gas 和 Builder 小费）；仅在收益代币为 WETH 时显示。",
    "同一機器人在同一資金池中對受害兌換進行搶跑與尾隨。利潤為毛利潤（未扣 Gas 與 Builder 小費）；僅在收益代幣為 WETH 時顯示。"
  ],
  [
    "No sandwiches detected yet.",
    "尚未检测到三明治攻击。",
    "尚未偵測到三明治攻擊。"
  ],
  [
    "Victim",
    "受害交易",
    "受害交易"
  ],
  [
    "Victim visibility",
    "受害交易可见性",
    "受害交易可見性"
  ],
  [
    "Victim swap",
    "受害兑换",
    "受害兌換"
  ],
  [
    "Attacker",
    "攻击者",
    "攻擊者"
  ],
  [
    "Front / back",
    "抢跑 / 尾随",
    "搶跑 / 尾隨"
  ],
  [
    "Gross profit",
    "毛利润",
    "毛利潤"
  ],
  [
    "unknown router",
    "未知路由",
    "未知路由"
  ],
  [
    "non-WETH",
    "非 WETH",
    "非 WETH"
  ],
  [
    "Large swaps seen in the mempool",
    "交易池内的大额兑换",
    "交易池中的大額兌換"
  ],
  [
    "Decoded from pending router calldata. Size is measured on the WETH side of the trade.",
    "根据待确认交易的路由调用数据解码。交易规模按 WETH 一侧计算。",
    "依待確認交易的路由呼叫資料解碼。交易規模以 WETH 一側計算。"
  ],
  [
    "Minimum",
    "最低金额",
    "最低金額"
  ],
  [
    "No swaps above {minEth} ETH yet.",
    "暂无超过 {minEth} ETH 的兑换。",
    "尚無超過 {minEth} ETH 的兌換。"
  ],
  [
    "Seen",
    "观测时间",
    "觀測時間"
  ],
  [
    "Router",
    "路由合约",
    "路由合約"
  ],
  [
    "Function",
    "函数",
    "函式"
  ],
  [
    "Path",
    "路径",
    "路徑"
  ],
  [
    "Size",
    "规模",
    "規模"
  ],
  [
    "Outcome",
    "结果",
    "結果"
  ],
  [
    "not included (yet)",
    "尚未打包",
    "尚未打包"
  ],
  [
    "sandwiched",
    "遭三明治攻击",
    "遭三明治攻擊"
  ],
  [
    "Transaction",
    "交易详情",
    "交易詳情"
  ],
  [
    "Public mempool",
    "公开交易池",
    "公開交易池"
  ],
  [
    "first seen {time}",
    "首次观测于 {time}",
    "首次觀測於 {time}"
  ],
  [
    "never seen by this node",
    "本节点未观测到",
    "本節點未觀測到"
  ],
  [
    "Included",
    "打包情况",
    "打包情況"
  ],
  [
    "block {number}, position {index}",
    "区块 {number}，位置 {index}",
    "區塊 {number}，位置 {index}"
  ],
  [
    "not in a stored block",
    "未在已存储区块中发现",
    "未在已儲存區塊中發現"
  ],
  [
    "Status",
    "状态",
    "狀態"
  ],
  [
    "success",
    "成功",
    "成功"
  ],
  [
    "reverted",
    "回滚",
    "回滾"
  ],
  [
    "Priority fee",
    "优先费",
    "優先費"
  ],
  [
    "Decoded swap intent",
    "解码后的兑换意图",
    "解碼後的兌換意圖"
  ],
  [
    "Token in",
    "输入代币",
    "輸入代幣"
  ],
  [
    "Token out",
    "输出代币",
    "輸出代幣"
  ],
  [
    "Exact",
    "精确数量类型",
    "精確數量類型"
  ],
  [
    "ETH size",
    "ETH 规模",
    "ETH 規模"
  ],
  [
    "input",
    "精确输入",
    "精確輸入"
  ],
  [
    "output",
    "精确输出",
    "精確輸出"
  ],
  [
    "Sandwich involvement",
    "三明治攻击关联",
    "三明治攻擊關聯"
  ],
  [
    "pool",
    "资金池",
    "資金池"
  ],
  [
    "attacker",
    "攻击者",
    "攻擊者"
  ],
  [
    "no data",
    "暂无数据",
    "尚無資料"
  ],
  [
    "{seconds}s ago",
    "{seconds} 秒前",
    "{seconds} 秒前"
  ],
  [
    "{minutes}m ago",
    "{minutes} 分钟前",
    "{minutes} 分鐘前"
  ],
  [
    "{hours}h ago",
    "{hours} 小时前",
    "{hours} 小時前"
  ],
  [
    "{days}d ago",
    "{days} 天前",
    "{days} 天前"
  ]
];

const zhCN = Object.fromEntries(entries.map(([key, simple]) => [key, simple])) as Record<string, string>;
const zhTW = Object.fromEntries(entries.map(([key, , traditional]) => [key, traditional])) as Record<string, string>;

function preferredLanguage(): Language {
  try {
    const saved = localStorage.getItem("scout.language");
    if (saved === "en" || saved === "zh-CN" || saved === "zh-TW") return saved;
  } catch { /* storage may be disabled */ }
  const userLanguage = navigator.language.toLowerCase();
  if (userLanguage.startsWith("zh")) {
    return /(?:-tw|-hk|-mo|-hant)/.test(userLanguage) ? "zh-TW" : "zh-CN";
  }
  return "en";
}

export interface I18nContextValue {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: string, values?: Record<string, string | number>) => string;
}
const context = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, updateLanguage] = useState<Language>(preferredLanguage);
  const setLanguage = useCallback((next: Language) => {
    updateLanguage(next);
    try { localStorage.setItem("scout.language", next); } catch { /* private mode */ }
  }, []);
  useEffect(() => {
    document.documentElement.lang = language;
    document.title = language === "en" ? "Ethereum Mempool Scout" : language === "zh-CN" ? "以太坊交易池侦察" : "以太坊交易池偵察";
  }, [language]);
  const t = useCallback((key: string, values?: Record<string, string | number>): string => {
    const translated = language === "zh-CN" ? zhCN[key] : language === "zh-TW" ? zhTW[key] : undefined;
    return (translated ?? key).replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g, (full, name: string) =>
      values?.[name] === undefined ? full : String(values[name]));
  }, [language]);
  const value = useMemo(() => ({ language, setLanguage, t }), [language, setLanguage, t]);
  return <context.Provider value={value}>{children}</context.Provider>;
}

export function useI18n(): I18nContextValue {
  const value = useContext(context);
  if (!value) throw new Error("useI18n must be used within I18nProvider");
  return value;
}
