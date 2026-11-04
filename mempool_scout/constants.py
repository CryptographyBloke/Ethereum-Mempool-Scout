"""Mainnet addresses and event signatures used across the project."""

from eth_utils import keccak

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"

# Router address (lower-case) -> protocol label.  Decoding is dispatched on the
# function selector, so any router that shares one of the supported ABIs (e.g.
# Uniswap V2 forks) can be added here or via ``--router`` on the CLI.
KNOWN_ROUTERS: dict[str, str] = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "uniswap-v2-router02",
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": "sushiswap-router",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "uniswap-v3-swaprouter",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "uniswap-v3-swaprouter02",
    "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b": "uniswap-universal-router-v1",
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "uniswap-universal-router-v1.2",
    "0x66a9893cc07d91d95644aedd05d03f95e1dba8af": "uniswap-universal-router-v2",
}


def topic(signature: str) -> str:
    return "0x" + keccak(text=signature).hex()


# Pool-level swap events (emitted no matter which router or bot called the pool).
UNISWAP_V2_SWAP_TOPIC = topic("Swap(address,uint256,uint256,uint256,uint256,address)")
UNISWAP_V3_SWAP_TOPIC = topic("Swap(address,address,int256,int256,uint160,uint128,int24)")

TOKEN0_SELECTOR = "0x0dfe1681"  # token0()
TOKEN1_SELECTOR = "0xd21220a7"  # token1()
