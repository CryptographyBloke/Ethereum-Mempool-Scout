# 🔭 Ethereum Mempool Scout

以太坊 Mempool 实时侦察工具，基于 `web3.py` 异步 WebSocket 订阅，监控链上大额 Uniswap V2 Swap 交易与新合约部署事件。

---

## 功能特性

- **实时 Pending 交易监听** — 通过 WebSocket 订阅 `newPendingTransactions`，在交易被打包进区块之前捕获
- **Uniswap V2 大额 Swap 检测** — 自动解码发往 V2 Router 的 5 种 swap 函数，超过阈值（默认 10 ETH）立即告警
- **新合约部署监控** — 捕获所有 `to == null` 的部署交易，显示部署者、字节码大小和 Gas 信息
- **高并发无阻塞** — 每条交易哈希通过 `asyncio.create_task` 独立调度，信号量限制最大 200 路并发
- **定期统计报告** — 每 30 秒打印处理数量、命中数、错误数汇总
- **优雅退出** — `Ctrl+C` 后输出最终统计并干净退出

---

## 环境要求

| 项目 | 版本 |
|------|------|
| Python | ≥ 3.10 |
| web3.py | ≥ 7.0（已测试 7.16.0）|

---

## 快速开始

### 1. 安装依赖

```bash
pip install web3
```

### 2. 获取 WebSocket 节点 URL

需要一个支持 WebSocket 的以太坊全节点接入地址。以下提供商均有**免费套餐**：

| 提供商 | WebSocket 地址格式 |
|--------|-------------------|
| [Alchemy](https://www.alchemy.com/) | `wss://eth-mainnet.g.alchemy.com/v2/<YOUR_KEY>` |
| [Infura](https://www.infura.io/) | `wss://mainnet.infura.io/ws/v3/<YOUR_KEY>` |
| [QuickNode](https://www.quicknode.com/) | `wss://<YOUR_ENDPOINT>.quiknode.pro/<YOUR_KEY>/` |
| [Chainstack](https://www.chainstack.com/) | `wss://nd-xxx.p2pify.com/<YOUR_KEY>` |
| 自建节点 (geth/erigon) | `ws://127.0.0.1:8546` |

### 3. 配置节点地址

打开 `scout.py`，将顶部的占位符替换为你的真实地址：

```python
# 修改前
WSS_NODE_URL = "wss://YOUR_NODE_URL_HERE"

# 修改后（示例）
WSS_NODE_URL = "wss://eth-mainnet.g.alchemy.com/v2/abcd1234efgh5678"
```

### 4. 启动运行

```bash
python3 scout.py
```

正常启动后，终端会显示：

```
============================================================
  🔭 Ethereum Mempool Scout 启动中…
  节点       : wss://eth-mainnet.g.alchemy.com/v2/abcd…
  监控路由器  : 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D
  大额阈值    : 10 ETH
============================================================
✅ 已连接  Chain ID=1  当前区块=21,847,302

📡 已订阅 pendingTransactions  subscription_id=0x...
```

---

## 输出示例

**大额 Swap 告警：**
```
[14:32:07.841] 💱 大额 Swap 检测！
         函数       : swapExactTokensForETH
         卖出数量   : 15.3200 ETH
         最小获得   : 14.9800 ETH
         兑换路径   : 0xC02a…WETH → 0xA0b8…USDC
         发送者     : 0xd8dA…6045
         Gas Price  : 23 Gwei
         Hash       : 0x4fa71c3b8e2d09a1…
```

**新合约部署：**
```
[14:33:15.012] 🚀 新合约部署  发送者=0xd8dA…6045  字节码长度=4821 bytes  Gas=800,000  Nonce=47  Hash=0x9c2b1a4f7e3d…
```

**定期统计：**
```
[14:40:07.000] 📊 统计 | 已处理=12,483  大额Swap=7  新合约=23  错误=41
```

---

## 配置项说明

所有配置集中在 `scout.py` 顶部的配置区：

```python
WSS_NODE_URL            = "wss://..."   # WebSocket 节点地址
UNISWAP_V2_ROUTER       = "0x7a25..."  # Uniswap V2 Router 合约地址（一般无需修改）
LARGE_SWAP_THRESHOLD_ETH = 10          # 大额 Swap 告警阈值（ETH）
MAX_CONCURRENT_TASKS     = 200         # 最大并发解析任务数
```

---

## 监控的 Uniswap V2 函数

| 函数名 | 说明 |
|--------|------|
| `swapExactTokensForETH` | 卖出精确数量的 Token，换取 ETH |
| `swapExactETHForTokens` | 卖出精确数量的 ETH，换取 Token |
| `swapExactTokensForTokens` | Token 对 Token 精确输入兑换 |
| `swapTokensForExactETH` | 换取精确数量的 ETH，输入 Token |
| `swapETHForExactTokens` | 换取精确数量的 Token，输入 ETH |

---

## 工作原理

```
以太坊节点
    │  WebSocket 推送 pending tx hash
    ▼
scout.py 主循环
    │  asyncio.create_task()  ← 非阻塞，立即返回继续监听
    ▼
parse_tx()（并发执行，最多 200 个）
    ├─ eth_getTransaction(hash)   ← RPC 异步调用
    ├─ 判断 to == null            → 打印合约部署
    └─ 判断 to == UniswapV2Router → ABI 解码 input → 判断金额 → 打印 Swap
```

---

## 常见问题

**Q: 启动后没有任何输出？**  
A: Mempool 数据量大，但大额交易相对稀少。可以先把 `LARGE_SWAP_THRESHOLD_ETH` 调低（如改为 `0.1`）来验证数据流是否正常。

**Q: 提示 `无法连接到节点`？**  
A: 检查 `WSS_NODE_URL` 是否正确，以及节点提供商的 API Key 是否有效。注意地址必须以 `wss://` 开头，不是 `https://`。

**Q: 错误计数很高？**  
A: 属于正常现象。Pending 交易中有相当一部分会在查询前被丢弃或已被打包，`eth_getTransaction` 返回空是预期行为，这类错误已被静默过滤。

**Q: 如何同时监控多个 DEX？**  
A: 在 `parse_tx` 函数中增加对其他路由合约地址（如 Uniswap V3、Curve、1inch 等）的判断分支，并为每个合约加载对应 ABI 即可。

---

## 注意事项

- 本工具仅作**只读监控**用途，不会发送任何交易
- Mempool 数据量极大（主网每秒可达数百笔），请确保节点提供商的 API 调用额度充足
- 本工具不构成任何投资或交易建议

---

## License

MIT
