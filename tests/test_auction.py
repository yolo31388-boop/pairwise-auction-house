"""拍卖行表驱动测试：原子出价、超时结算、金币冻结返还、幂等、守恒。"""

from __future__ import annotations

import pytest

from src import AuctionEngine


def _eng():
    eng = AuctionEngine()
    eng.add_player("alice", 1000)
    eng.add_player("bob", 1000)
    eng.inventory["alice"].append("sword")
    return eng


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
    """整个过程金币守恒（不含卖家收款）。"""
    eng = _eng()
    eng.add_player("charlie", 1000)
    total_before = eng.get_gold("alice") + eng.get_gold("bob") + eng.get_gold("charlie")
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    eng.place_bid("a1", "charlie", 300, now=20)
    total_after = eng.get_gold("alice") + eng.get_gold("bob") + eng.get_gold("charlie")
    # bob 被超价返还，charlie 冻结300，alice 还没收款
    assert total_after == total_before, "金币应守恒: before=%d after=%d" % (total_before, total_after)


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
