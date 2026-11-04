"""Synthetic calldata, logs and a fake async node used across tests."""

from __future__ import annotations

from typing import Any

from eth_abi import encode
from eth_utils import keccak

from mempool_scout.constants import UNISWAP_V2_SWAP_TOPIC, UNISWAP_V3_SWAP_TOPIC, WETH

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
V2_ROUTER = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"
V3_ROUTER = "0xe592427a0aece92de3edee1f18e0157c05861564"
UNIVERSAL = "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad"
POOL = "0x" + "11" * 20
BOT = "0x" + "b0" * 20
ATTACKER = "0x" + "a1" * 20
VICTIM = "0x" + "5e" * 20
OTHER = "0x" + "77" * 20
ETH = 10**18


def sel(sig: str) -> bytes:
    return keccak(text=sig)[:4]


def v3_path(tokens: list[str], fees: list[int]) -> bytes:
    out = bytes.fromhex(tokens[0][2:])
    for fee, tok in zip(fees, tokens[1:]):
        out += fee.to_bytes(3, "big") + bytes.fromhex(tok[2:])
    return out


def v2_swap_exact_eth_for_tokens(amount_out_min: int, path: list[str]) -> bytes:
    return sel("swapExactETHForTokens(uint256,address[],address,uint256)") + encode(
        ["uint256", "address[]", "address", "uint256"], [amount_out_min, path, VICTIM, 2**32])


def v2_swap_exact_tokens_for_eth(amount_in: int, amount_out_min: int, path: list[str]) -> bytes:
    return sel("swapExactTokensForETH(uint256,uint256,address[],address,uint256)") + encode(
        ["uint256", "uint256", "address[]", "address", "uint256"], [amount_in, amount_out_min, path, VICTIM, 2**32])


def v2_log(tx_hash: str, tx_index: int, log_index: int, a0_in: int, a1_in: int, a0_out: int, a1_out: int,
           pool: str = POOL) -> dict[str, Any]:
    return {
        "address": pool,
        "topics": [UNISWAP_V2_SWAP_TOPIC, "0x" + "00" * 32, "0x" + "00" * 32],
        "data": "0x" + encode(["uint256"] * 4, [a0_in, a1_in, a0_out, a1_out]).hex(),
        "transactionHash": tx_hash,
        "transactionIndex": tx_index,
        "logIndex": log_index,
    }


def v3_log(tx_hash: str, tx_index: int, log_index: int, amount0: int, amount1: int, pool: str = POOL) -> dict[str, Any]:
    return {
        "address": pool,
        "topics": [UNISWAP_V3_SWAP_TOPIC, "0x" + "00" * 32, "0x" + "00" * 32],
        "data": "0x" + encode(["int256", "int256", "uint160", "uint128", "int24"],
                              [amount0, amount1, 2**96, 10**18, 0]).hex(),
        "transactionHash": tx_hash,
        "transactionIndex": tx_index,
        "logIndex": log_index,
    }


def h(n: int) -> str:
    return "0x" + f"{n:064x}"


def sandwich_block(number: int = 100, timestamp: int = 1_700_000_000) -> dict[str, Any]:
    """Block with: 0 = front-run (bot), 1 = victim (router swap), 2 = back-run (bot), 3 = unrelated.

    Pool token0 = WETH, token1 = USDC.  Attacker sells 10 WETH, victim sells 50 WETH,
    attacker sells back the USDC and ends with 10.4 WETH.
    """
    victim_input = v2_swap_exact_eth_for_tokens(1, [WETH, USDC])
    txs = [
        {"hash": h(1), "transactionIndex": 0, "from": ATTACKER, "to": BOT, "input": "0x01", "value": 0, "type": 2},
        {"hash": h(2), "transactionIndex": 1, "from": VICTIM, "to": V2_ROUTER, "input": "0x" + victim_input.hex(),
         "value": 50 * ETH, "type": 2},
        {"hash": h(3), "transactionIndex": 2, "from": ATTACKER, "to": BOT, "input": "0x02", "value": 0, "type": 2},
        {"hash": h(4), "transactionIndex": 3, "from": OTHER, "to": DAI, "input": "0x", "value": 0, "type": 2},
    ]
    receipts = [
        {"transactionHash": h(1), "transactionIndex": 0, "status": 1, "gasUsed": 100_000, "from": ATTACKER, "to": BOT,
         "effectiveGasPrice": 30 * 10**9, "logs": [v2_log(h(1), 0, 0, 10 * ETH, 0, 0, 20_000 * 10**6)]},
        {"transactionHash": h(2), "transactionIndex": 1, "status": 1, "gasUsed": 120_000, "from": VICTIM,
         "to": V2_ROUTER, "effectiveGasPrice": 21 * 10**9,
         "logs": [v2_log(h(2), 1, 1, 50 * ETH, 0, 0, 95_000 * 10**6)]},
        {"transactionHash": h(3), "transactionIndex": 2, "status": 1, "gasUsed": 100_000, "from": ATTACKER, "to": BOT,
         "effectiveGasPrice": 20 * 10**9, "logs": [v2_log(h(3), 2, 2, 0, 20_000 * 10**6, 10_400_000_000_000_000_000, 0)]},
        {"transactionHash": h(4), "transactionIndex": 3, "status": 1, "gasUsed": 21_000, "from": OTHER, "to": DAI,
         "effectiveGasPrice": 20 * 10**9, "logs": []},
    ]
    block = {
        "number": number, "hash": h(1000 + number), "parentHash": h(999 + number), "timestamp": timestamp,
        "miner": "0x" + "be" * 20, "extraData": "0x" + b"beaverbuild.org".hex(), "baseFeePerGas": 20 * 10**9,
        "gasUsed": 341_000, "gasLimit": 30_000_000, "transactions": txs,
    }
    return {"block": block, "receipts": receipts}


class FakeEth:
    """Test double with the same methods as ``mempool_scout.rpc.EthRpc``."""

    def __init__(self, blocks: dict[int, dict[str, Any]], pool_tokens: dict[str, tuple[str, str]]):
        self.blocks = blocks
        self.pool_tokens = pool_tokens

    async def get_block(self, number: int, full_transactions: bool = False) -> dict[str, Any]:
        return self.blocks[number]["block"]

    async def get_block_receipts(self, number: int) -> list[dict[str, Any]]:
        return self.blocks[number]["receipts"]

    async def get_transaction(self, tx_hash: str) -> dict[str, Any] | None:
        for b in self.blocks.values():
            for t in b["block"]["transactions"]:
                if t["hash"] == tx_hash:
                    return t
        return None

    async def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        for b in self.blocks.values():
            for r in b["receipts"]:
                if r["transactionHash"] == tx_hash:
                    return r
        return None

    async def call(self, tx: dict[str, Any]) -> bytes:
        t0, t1 = self.pool_tokens[tx["to"].lower()]
        token = t0 if tx["data"] == "0x0dfe1681" else t1
        return b"\x00" * 12 + bytes.fromhex(token[2:])
