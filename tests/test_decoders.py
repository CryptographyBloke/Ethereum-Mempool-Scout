from eth_abi import encode

from mempool_scout.constants import WETH
from mempool_scout.decoders import CONTRACT_BALANCE, decode_calldata, decode_swap_tx, decode_v3_path

from .fixtures import (DAI, ETH, UNIVERSAL, USDC, V2_ROUTER, V3_ROUTER, VICTIM, sel, v2_swap_exact_eth_for_tokens,
                       v2_swap_exact_tokens_for_eth, v3_path)


def test_v2_eth_in_uses_msg_value():
    data = v2_swap_exact_eth_for_tokens(123, [WETH, USDC])
    [s] = decode_calldata(data, value=12 * ETH)
    assert s.function == "swapExactETHForTokens"
    assert (s.token_in, s.token_out) == (WETH, USDC)
    assert s.amount_in == 12 * ETH and s.amount_out == 123 and s.exact_input
    assert s.eth_notional_wei == 12 * ETH


def test_v2_token_amount_is_not_treated_as_eth():
    # v1 bug: 20,000 USDC (6 decimals) was compared with an ETH threshold.
    data = v2_swap_exact_tokens_for_eth(20_000 * 10**6, 5 * ETH, [USDC, WETH])
    [s] = decode_calldata(data)
    assert s.token_in == USDC and s.token_out == WETH
    assert s.eth_notional_wei == 5 * ETH  # measured on the WETH side (minimum out)


def test_v2_token_to_token_has_no_eth_notional():
    data = sel("swapExactTokensForTokens(uint256,uint256,address[],address,uint256)") + encode(
        ["uint256", "uint256", "address[]", "address", "uint256"], [1000, 990, [USDC, DAI], VICTIM, 1])
    [s] = decode_calldata(data)
    assert s.eth_notional_wei is None and s.path == [USDC, DAI]


def test_v3_exact_input_single_and_multicall():
    inner = sel("exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))") + encode(
        ["(address,address,uint24,address,uint256,uint256,uint256,uint160)"],
        [(WETH, USDC, 500, VICTIM, 1, 3 * ETH, 7000 * 10**6, 0)])
    [s] = decode_calldata(inner)
    assert s.protocol == "uniswap-v3" and s.fees == [500] and s.eth_notional_wei == 3 * ETH

    wrapped = sel("multicall(uint256,bytes[])") + encode(["uint256", "bytes[]"], [99, [inner, inner]])
    assert len(decode_calldata(wrapped)) == 2


def test_v3_exact_output_path_is_reversed():
    path = v3_path([USDC, WETH], [3000])  # exact-output: tokenOut first
    data = sel("exactOutput((bytes,address,uint256,uint256,uint256))") + encode(
        ["(bytes,address,uint256,uint256,uint256)"], [(path, VICTIM, 1, 1000 * 10**6, 2 * ETH)])
    [s] = decode_calldata(data)
    assert (s.token_in, s.token_out) == (WETH, USDC)
    assert s.amount_in == 2 * ETH and s.amount_out == 1000 * 10**6 and not s.exact_input


def test_v3_path_roundtrip():
    tokens, fees = decode_v3_path(v3_path([WETH, USDC, DAI], [500, 100]))
    assert tokens == [WETH, USDC, DAI] and fees == [500, 100]


def test_universal_router_wrap_then_v2_swap_with_contract_balance():
    commands = bytes([0x0B, 0x08])
    wrap = encode(["address", "uint256"], ["0x" + "00" * 19 + "02", 4 * ETH])
    swap = encode(["address", "uint256", "uint256", "address[]", "bool"],
                  [VICTIM, CONTRACT_BALANCE, 1, [WETH, USDC], False])
    data = sel("execute(bytes,bytes[],uint256)") + encode(["bytes", "bytes[]", "uint256"], [commands, [wrap, swap], 1])
    [s] = decode_swap_tx({"to": UNIVERSAL, "input": data, "value": 4 * ETH})
    assert s.function == "universal:V2_SWAP_EXACT_IN"
    assert s.amount_in == 4 * ETH and s.eth_notional_wei == 4 * ETH


def test_universal_router_v3_exact_in_with_allow_revert_flag():
    commands = bytes([0x80 | 0x00])
    swap = encode(["address", "uint256", "uint256", "bytes", "bool"],
                  [VICTIM, 6 * ETH, 1, v3_path([WETH, USDC], [500]), True])
    data = sel("execute(bytes,bytes[])") + encode(["bytes", "bytes[]"], [commands, [swap]])
    [s] = decode_calldata(data)
    assert s.function == "universal:V3_SWAP_EXACT_IN" and s.eth_notional_wei == 6 * ETH


def test_unknown_router_or_garbage_is_ignored():
    data = v2_swap_exact_eth_for_tokens(1, [WETH, USDC])
    assert decode_swap_tx({"to": DAI, "input": data, "value": 1}) == []
    assert decode_swap_tx({"to": V2_ROUTER, "input": "0xdeadbeef", "value": 0}) == []
    assert decode_swap_tx({"to": V3_ROUTER, "input": data[:40], "value": 0}) == []
    assert decode_swap_tx({"to": None, "input": data}) == []
