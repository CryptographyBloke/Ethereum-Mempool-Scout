# 以太坊 Mempool 侦察兵（Ethereum Mempool Scout）

[English](README.md) · [研究方法](docs/methodology.md)

**一个测量以太坊交易隐私与 MEV 的全栈系统。** 它记录每笔交易出现在公共 mempool 的时间，
与最终打包它的区块进行匹配，基于链上 Swap 事件识别三明治攻击，并通过 REST API 和 Web
仪表盘展示结果。

## 研究问题

| | 问题 | 输出 |
|---|---|---|
| **RQ1** | 被打包的交易中，有多少比例在上链前出现在公共 mempool？按交易类型、区块构建者（builder）有何差异？ | 公开比例、上链延迟分布、按 builder 统计 |
| **RQ1b** | 单一观测点会低估多少公开交易？ | 各观测点与所有观测点并集的差距、独有观测、传播延迟 |
| **RQ2** | 在公共 mempool 中可见的 Uniswap swap，是否比私有提交的 swap 更容易被三明治攻击？ | 两组攻击率及 95% Wilson 置信区间、相对风险、双比例 z 检验 |
| **RQ2b** | 滑点容忍度越宽松，是否越容易被三明治攻击？ | 首次出现时对 swap 报价，按容忍度分组统计攻击率 |
| **RQ3** | 区块构建的集中度如何？哪些 builder 更依赖私有订单流？ | 各 builder 出块占比与公开比例 |

## 系统组成

- **采集器**（Python asyncio）：自研 WebSocket JSON-RPC 客户端，订阅 `newPendingTransactions` 与 `newHeads`；每个 pending 哈希立即打时间戳；有界并发拉取交易详情；节点滞后时自动重试；断线自动重连，每次连接记为一个 session。
- **解码器**：Uniswap V2 Router（11 个函数）、V3 SwapRouter / SwapRouter02（含 `multicall`）、Universal Router 命令；以 WETH 一侧计算交易规模（修复了 v1 把代币数量当作 ETH 比较的问题）。
- **三明治检测**：基于收据中的 V2/V3 `Swap` 事件，覆盖通过自有合约调用资金池的 MEV 机器人；计算扣除 Gas 后的净利润；可通过人工标注样本（`label-sample` / `validate`）测量检测精度。
- **多观测点**：多个采集器（不同节点服务商）可写入同一数据库，量化单一观测点的测量误差。
- **滑点报价**：在交易首次出现时对其报价，得到用户的滑点容忍度。
- **存储**：SQLite（WAL 模式），采集器写、API 与报告读。
- **后端 API**：FastAPI，14 个 REST 接口 + Server-Sent Events 实时推送，`/docs` 自动生成接口文档。
- **前端**：React + TypeScript + Vite 仪表盘，SVG 图表，支持明暗主题，每个图表都可切换为表格。
- **报告**：`mempool-scout report` 生成 Markdown + JSON 研究报告。

## 快速开始

```bash
export SCOUT_WSS_URL="wss://eth-mainnet.g.alchemy.com/v2/<YOUR_KEY>"
docker compose up --build        # 打开 http://localhost:8000
```

本地运行：

```bash
pip install -e ".[dev]"
mempool-scout collect --db data/scout.sqlite --vantage home-node
mempool-scout serve   --db data/scout.sqlite
cd frontend && npm install && npm run dev      # http://localhost:5173
mempool-scout report  --db data/scout.sqlite --out reports
```

## 测试

```bash
pytest -q                      # 38 个测试：解码、三明治识别、统计方法、端到端流程、API
cd frontend && npm run build   # 类型检查 + 构建
```

## 长期测量

在 VPS 上进行多周测量的完整步骤（服务器配置、多观测点、时钟同步、备份、监控、研究流程）见 [docs/deployment.md](docs/deployment.md)。

## 注意事项

- 只读工具，不会签名或发送任何交易。
- 单一观测点会低估公开交易比例，详见 [研究方法](docs/methodology.md) 中的“有效性威胁”。
- 本项目不构成任何投资建议。

## License

MIT
