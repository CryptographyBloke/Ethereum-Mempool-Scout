"""
=============================================================
  Ethereum Mempool Scout — 以太坊 Mempool 侦察兵
=============================================================
⚠️  使用前请替换下方 WSS_NODE_URL 为你自己的 WebSocket 节点地址。
    推荐节点提供商（均有免费套餐）：
      - Alchemy :  wss://eth-mainnet.g.alchemy.com/v2/<your>
      - Infura   :  wss://mainnet.infura.io/ws/v3/<YOUR_KEY>
      - Chainstack, QuickNode 等
=============================================================
"""

import asyncio
import json
import signal
import sys
from datetime import datetime

from web3 import AsyncWeb3
from web3.providers import WebSocketProvider

# ─── 🔧 配置区 ──────────────────────────────────────────────
WSS_NODE_URL = "wss://eth-mainnet.g.alchemy.com/v2/ZjU7VuvJQPgMNFdYFJcE6"          # ← 替换这里！

UNISWAP_V2_ROUTER = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
LARGE_SWAP_THRESHOLD_ETH = 10                      # 大额 Swap 阈值（ETH）
MAX_CONCURRENT_TASKS = 200                         # 最大并发解析任务数
# ────────────────────────────────────────────────────────────

# Uniswap V2 Router 关键函数 ABI（仅列出需要解码的函数）
UNISWAP_V2_ABI = json.loads("""[
  {
    "name": "swapExactTokensForETH",
    "type": "function",
    "inputs": [
      {"name": "amountIn",        "type": "uint256"},
      {"name": "amountOutMin",    "type": "uint256"},
      {"name": "path",            "type": "address[]"},
      {"name": "to",              "type": "address"},
      {"name": "deadline",        "type": "uint256"}
    ]
  },
  {
    "name": "swapExactETHForTokens",
    "type": "function",
    "inputs": [
      {"name": "amountOutMin",    "type": "uint256"},
      {"name": "path",            "type": "address[]"},
      {"name": "to",              "type": "address"},
      {"name": "deadline",        "type": "uint256"}
    ]
  },
  {
    "name": "swapExactTokensForTokens",
    "type": "function",
    "inputs": [
      {"name": "amountIn",        "type": "uint256"},
      {"name": "amountOutMin",    "type": "uint256"},
      {"name": "path",            "type": "address[]"},
      {"name": "to",              "type": "address"},
      {"name": "deadline",        "type": "uint256"}
    ]
  },
  {
    "name": "swapTokensForExactETH",
    "type": "function",
    "inputs": [
      {"name": "amountOut",       "type": "uint256"},
      {"name": "amountInMax",     "type": "uint256"},
      {"name": "path",            "type": "address[]"},
      {"name": "to",              "type": "address"},
      {"name": "deadline",        "type": "uint256"}
    ]
  },
  {
    "name": "swapETHForExactTokens",
    "type": "function",
    "inputs": [
      {"name": "amountOut",       "type": "uint256"},
      {"name": "path",            "type": "address[]"},
      {"name": "to",              "type": "address"},
      {"name": "deadline",        "type": "uint256"}
    ]
  }
]""")

# ─── 统计计数器 ──────────────────────────────────────────────
stats = {"seen": 0, "swaps": 0, "deploys": 0, "errors": 0}


def ts() -> str:
    """返回当前时间戳字符串"""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def fmt_eth(wei: int) -> str:
    return f"{wei / 1e18:.4f} ETH"


def fmt_addr(addr: str) -> str:
    """缩短地址显示"""
    return f"{addr[:6]}…{addr[-4:]}"


# ─── 核心解析逻辑 ────────────────────────────────────────────

async def parse_tx(w3: AsyncWeb3, router_contract, tx_hash: bytes) -> None:
    """异步获取并解析单笔交易，由 create_task 调度执行"""
    try:
        tx = await w3.eth.get_transaction(tx_hash)
        if tx is None:
            return

        stats["seen"] += 1
        value_wei: int = tx.get("value", 0)
        to_addr = tx.get("to")

        # ── 1. 检测新合约部署（to 为空）──────────────────────
        if to_addr is None:
            stats["deploys"] += 1
            sender = tx.get("from", "unknown")
            data_len = len(tx.get("input", b""))
            print(
                f"[{ts()}] 🚀 新合约部署  "
                f"发送者={fmt_addr(sender)}  "
                f"字节码长度={data_len} bytes  "
                f"Gas={tx.get('gas', 0):,}  "
                f"Nonce={tx.get('nonce', '?')}  "
                f"Hash={tx_hash.hex()[:16]}…"
            )
            return

        # ── 2. 检测 Uniswap V2 大额 Swap ─────────────────────
        if to_addr and to_addr.lower() == UNISWAP_V2_ROUTER.lower():
            input_data = tx.get("input", b"")
            if not input_data or len(input_data) < 4:
                return

            try:
                func_obj, decoded = router_contract.decode_function_input(input_data)
                func_name: str = func_obj.fn_name

                # 判断交易价值或 amountIn 是否超过阈值
                amount_in_wei = decoded.get("amountIn", value_wei)
                if amount_in_wei < LARGE_SWAP_THRESHOLD_ETH * 1e18:
                    # 对于以 ETH 输入的函数，用 tx.value 判断
                    if value_wei < LARGE_SWAP_THRESHOLD_ETH * 1e18:
                        return

                stats["swaps"] += 1
                path: list = decoded.get("path", [])
                path_str = " → ".join(fmt_addr(a) for a in path)
                amount_in = decoded.get("amountIn", value_wei)
                amount_out_min = decoded.get("amountOutMin", decoded.get("amountOut", 0))

                print(
                    f"[{ts()}] 💱 大额 Swap 检测！\n"
                    f"         函数       : {func_name}\n"
                    f"         卖出数量   : {fmt_eth(amount_in)}\n"
                    f"         最小获得   : {fmt_eth(amount_out_min)}\n"
                    f"         兑换路径   : {path_str}\n"
                    f"         发送者     : {fmt_addr(tx.get('from','?'))}\n"
                    f"         Gas Price  : {tx.get('gasPrice',0)//10**9} Gwei\n"
                    f"         Hash       : {tx_hash.hex()[:20]}…\n"
                )

            except Exception:
                # 不认识的函数签名，跳过
                pass

    except Exception as e:
        stats["errors"] += 1
        # 静默处理常见的"交易未找到"错误
        err_str = str(e)
        if "not found" not in err_str.lower() and "does not exist" not in err_str.lower():
            print(f"[{ts()}] ⚠️  解析错误: {err_str[:80]}")


# ─── 主侦听循环 ──────────────────────────────────────────────

async def scout() -> None:
    print("=" * 60)
    print("  🔭 Ethereum Mempool Scout 启动中…")
    print(f"  节点       : {WSS_NODE_URL[:40]}…" if len(WSS_NODE_URL) > 40 else f"  节点: {WSS_NODE_URL}")
    print(f"  监控路由器  : {UNISWAP_V2_ROUTER}")
    print(f"  大额阈值    : {LARGE_SWAP_THRESHOLD_ETH} ETH")
    print("=" * 60)

    async with AsyncWeb3(WebSocketProvider(WSS_NODE_URL)) as w3:
        # 检查连接
        if not await w3.is_connected():
            print("❌ 无法连接到节点，请检查 WSS_NODE_URL。")
            return

        chain_id = await w3.eth.chain_id
        block = await w3.eth.block_number
        print(f"✅ 已连接  Chain ID={chain_id}  当前区块={block:,}\n")

        # 实例化路由合约（仅用于 ABI 解码，不需要真实部署地址交互）
        router_contract = w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(UNISWAP_V2_ROUTER),
            abi=UNISWAP_V2_ABI,
        )

        # 订阅 pending 交易哈希流
        subscription_id = await w3.eth.subscribe("newPendingTransactions")
        print(f"📡 已订阅 pendingTransactions  subscription_id={subscription_id}\n")

        # 信号量控制并发
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
        pending_tasks: set = set()

        async def bounded_parse(tx_hash):
            async with semaphore:
                await parse_tx(w3, router_contract, tx_hash)

        # 定期打印统计
        async def print_stats():
            while True:
                await asyncio.sleep(30)
                print(
                    f"[{ts()}] 📊 统计 | "
                    f"已处理={stats['seen']:,}  "
                    f"大额Swap={stats['swaps']}  "
                    f"新合约={stats['deploys']}  "
                    f"错误={stats['errors']}"
                )

        asyncio.create_task(print_stats())

        # 监听哈希流，每条哈希 create_task 异步解析
        async for response in w3.socket.process_subscriptions():
            tx_hash = response.get("result")
            if tx_hash is None:
                continue

            task = asyncio.create_task(bounded_parse(tx_hash))
            pending_tasks.add(task)
            task.add_done_callback(pending_tasks.discard)


# ─── 入口 ────────────────────────────────────────────────────

def main():
    loop = asyncio.new_event_loop()

    def _shutdown(sig, frame):
        print(f"\n\n[{ts()}] 🛑 收到退出信号，正在关闭…")
        print(f"  最终统计 | 已处理={stats['seen']:,}  大额Swap={stats['swaps']}  新合约={stats['deploys']}  错误={stats['errors']}")
        loop.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(scout())
    except KeyboardInterrupt:
        _shutdown(None, None)
    finally:
        loop.close()


if __name__ == "__main__":
    main()
