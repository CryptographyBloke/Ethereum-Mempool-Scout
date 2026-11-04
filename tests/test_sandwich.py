from mempool_scout.sandwich import detect_sandwiches, extract_pool_swaps, parse_swap_log

from .fixtures import ATTACKER, BOT, ETH, OTHER, VICTIM, h, sandwich_block, v2_log, v3_log


def test_detects_classic_v2_sandwich():
    receipts = sandwich_block()["receipts"]
    swaps = extract_pool_swaps(receipts)
    [sw] = detect_sandwiches(swaps)
    assert sw.victim.tx_hash == h(2)
    assert (sw.front.tx_hash, sw.back.tx_hash) == (h(1), h(3))
    assert sw.attacker == BOT
    assert sw.profit_in_token0  # profit in token0 (WETH in the fixture)
    assert sw.gross_profit == 400_000_000_000_000_000  # 10.4 - 10 WETH


def test_no_sandwich_when_attacker_differs():
    swaps = extract_pool_swaps(sandwich_block()["receipts"])
    swaps[2].tx_from, swaps[2].tx_to = OTHER, OTHER
    assert detect_sandwiches(swaps) == []


def test_no_sandwich_when_back_run_volume_does_not_match():
    swaps = extract_pool_swaps(sandwich_block()["receipts"])
    swaps[2].amount1 = swaps[2].amount1 * 3  # sells 3x what the front-run bought
    assert detect_sandwiches(swaps) == []


def test_victim_must_trade_in_front_run_direction():
    swaps = extract_pool_swaps(sandwich_block()["receipts"])
    swaps[1].amount0, swaps[1].amount1 = -swaps[1].amount0, 5 * 10**6
    assert detect_sandwiches(swaps) == []


def test_v3_log_parsing_and_sandwich():
    logs = [
        v3_log(h(1), 0, 0, 5 * ETH, -10_000),
        v3_log(h(2), 1, 1, 20 * ETH, -38_000),
        v3_log(h(3), 2, 2, -int(5.2 * ETH), 10_000),
    ]
    froms = [ATTACKER, VICTIM, ATTACKER]
    swaps = [parse_swap_log(lg, f, BOT if f == ATTACKER else "0xrouter") for lg, f in zip(logs, froms)]
    assert all(s is not None and s.protocol == "uniswap-v3" for s in swaps)
    [sw] = detect_sandwiches(swaps)
    assert sw.gross_profit == int(5.2 * ETH) - 5 * ETH


def test_failed_receipts_and_foreign_logs_ignored():
    r = sandwich_block()["receipts"]
    r[0]["status"] = 0
    r[3]["logs"] = [{**v2_log(h(4), 3, 9, 1, 0, 0, 1), "topics": ["0x" + "ab" * 32]}]
    swaps = extract_pool_swaps(r)
    assert [s.tx_hash for s in swaps] == [h(2), h(3)]
