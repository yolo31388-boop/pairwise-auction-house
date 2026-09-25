"""拍卖行表驱动测试：原子出价、超时结算、金币冻结返还、幂等、守恒。"""

from __future__ import annotations

import random
import threading

import pytest

from src import AuctionEngine


def _eng():
    eng = AuctionEngine()
    eng.add_player("alice", 1000)
    eng.add_player("bob", 1000)
    eng.inventory["alice"].append("sword")
    return eng


def _total_gold(eng) -> int:
    """流通金币 + 冻结金币（守恒口径）。"""
    circulating = sum(eng.gold.values())
    frozen = sum(sum(a.frozen_gold.values()) for a in eng.auctions.values())
    return circulating + frozen


def test_basic_bid():
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    assert eng.place_bid("a1", "bob", 150, now=10) is True
    assert eng.get_gold("bob") == 850


def test_bid_below_current_price_rejected():
    """低于当前最高价的出价必须被拒绝并返还金币。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    gold_before = eng.get_gold("bob")
    # 用另一个玩家出低价
    eng.add_player("charlie", 1000)
    result = eng.place_bid("a1", "charlie", 150, now=20)
    assert result is False, "低于当前最高价应被拒绝"
    assert eng.get_gold("charlie") == 1000, "拒绝后金币应返还"


def test_outbid_returns_gold():
    eng = _eng()
    eng.add_player("charlie", 1000)
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    assert eng.get_gold("bob") == 800
    eng.place_bid("a1", "charlie", 300, now=20)
    assert eng.get_gold("bob") == 1000, "被超价后金币应返还"


def test_timeout_settles_to_bidder():
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    eng.settle("a1", now=60)
    assert "sword" in eng.inventory["bob"]
    assert eng.get_gold("alice") == 1200  # 1000 + 200


def test_timeout_unsold_returns_item():
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.settle("a1", now=60)
    assert "sword" in eng.inventory["alice"]


def test_settle_before_timeout_rejected():
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    assert eng.settle("a1", now=50) is False


def test_settle_idempotent():
    """重复结算不能重复发奖。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    eng.settle("a1", now=60)
    alice_gold = eng.get_gold("alice")
    eng.settle("a1", now=70)  # 重复结算
    assert eng.get_gold("alice") == alice_gold, "重复结算不应重复发奖"
    assert eng.inventory["bob"].count("sword") == 1


def test_gold_conservation():
    """整个过程金币守恒：流通金币 + 拍卖行冻结金币为常量。"""
    eng = _eng()
    eng.add_player("charlie", 1000)
    total_before = _total_gold(eng)
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    eng.place_bid("a1", "charlie", 300, now=20)
    # bob 被超价返还，charlie 的 300 冻结在拍卖行，alice 还没收款
    assert _total_gold(eng) == total_before
    eng.settle("a1", now=150)
    # 成交后冻结金币转给卖家，总量仍守恒
    assert _total_gold(eng) == total_before
    assert eng.get_gold("alice") == 1300


def test_seller_cannot_bid():
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    assert eng.place_bid("a1", "alice", 200, now=10) is False


def test_insufficient_gold():
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    assert eng.place_bid("a1", "bob", 2000, now=10) is False
    assert eng.get_gold("bob") == 1000


def test_bid_after_timeout_rejected():
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    assert eng.place_bid("a1", "bob", 200, now=60) is False


def test_deterministic():
    def run():
        eng = _eng()
        eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
        eng.place_bid("a1", "bob", 200, now=10)
        eng.settle("a1", now=150)
        return eng.snapshot()
    assert run() == run()


def test_trade_log_records_bids_and_settlement():
    """交易记录必须完整记录每一次出价和最终成交。"""
    eng = _eng()
    eng.add_player("charlie", 1000)
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    eng.place_bid("a1", "charlie", 300, now=20)
    eng.settle("a1", now=150)
    assert "a1 bid 200 by bob" in eng.trade_log
    assert "a1 bid 300 by charlie" in eng.trade_log
    assert "a1 sold to charlie for 300" in eng.trade_log
    assert len(eng.auctions["a1"].bids) == 2


def test_trade_log_records_unsold():
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.settle("a1", now=60)
    assert "a1 unsold, returned to alice" in eng.trade_log


def test_seller_paid_only_after_settle():
    """成交前卖家不得收到金币；成交后恰好收到成交价。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    assert eng.get_gold("alice") == 1000, "结算前卖家不应收到金币"
    eng.settle("a1", now=150)
    assert eng.get_gold("alice") == 1200, "成交后卖家应收到成交价"


def test_item_delivered_exactly_once():
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    eng.settle("a1", now=60)
    eng.settle("a1", now=70)
    assert eng.inventory["bob"].count("sword") == 1
    assert "sword" not in eng.inventory["alice"]


def test_settle_returns_false_when_already_settled():
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    assert eng.settle("a1", now=60) is True
    assert eng.settle("a1", now=70) is False, "重复结算应返回 False"


def test_auto_settle_on_expired_auction_access():
    """超时后任何出价尝试都会触发自动结算，拍卖不能卡在中间状态。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    assert eng.place_bid("a1", "bob", 300, now=60) is False
    auc = eng.auctions["a1"]
    assert auc.settled is True, "超时后应自动结算"
    assert "sword" in eng.inventory["bob"]
    assert eng.get_gold("alice") == 1200


def test_same_bidder_raise_own_bid():
    """同一出价者加价：只补差价，金币不丢失。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    assert eng.place_bid("a1", "bob", 350, now=20) is True
    assert eng.get_gold("bob") == 650
    assert eng.auctions["a1"].frozen_gold["bob"] == 350
    assert eng.auctions["a1"].current_price == 350


def test_equal_price_rejected():
    """等于当前最高价的出价必须被拒绝。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    eng.add_player("charlie", 1000)
    assert eng.place_bid("a1", "charlie", 200, now=20) is False
    assert eng.get_gold("charlie") == 1000


def test_concurrent_bids_price_never_regresses():
    """并发出价：价格单调严格递增，最终价等于最高接受出价，金币守恒。"""
    eng = _eng()
    bidders = [f"p{i}" for i in range(16)]
    for pid in bidders:
        eng.add_player(pid, 100000)
    eng.create_auction("a1", "alice", "sword", 100, 10_000, now=0)
    total_before = _total_gold(eng)

    def worker(pid, seed):
        rng = random.Random(seed)
        for _ in range(50):
            eng.place_bid("a1", pid, rng.randint(1, 50000), now=1)

    threads = [threading.Thread(target=worker, args=(pid, i))
               for i, pid in enumerate(bidders)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    auc = eng.auctions["a1"]
    amounts = [b.amount for b in auc.bids]
    assert all(x < y for x, y in zip(amounts, amounts[1:])), "接受的出价必须严格递增"
    assert auc.current_price == amounts[-1], "当前价必须等于最后一次接受的出价"
    assert auc.current_bidder == auc.bids[-1].bidder
    assert _total_gold(eng) == total_before, "并发出价下金币必须守恒"
    # 结算后仍然守恒且幂等
    eng.settle("a1", now=20_000)
    eng.settle("a1", now=20_000)
    assert _total_gold(eng) == total_before
    assert eng.inventory[auc.current_bidder].count("sword") == 1
