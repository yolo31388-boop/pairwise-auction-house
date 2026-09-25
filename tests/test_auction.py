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
    # bob 被超价返还，charlie 冻结300（已扣减，不计入可用金币），alice 还没收款
    frozen = sum(sum(a.frozen_gold.values()) for a in eng.auctions.values())
    assert frozen == 300
    assert total_after + frozen == total_before, "金币应守恒(含冻结): before=%d after=%d frozen=%d" % (total_before, total_after, frozen)


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


def test_bid_must_strictly_exceed_current_price():
    """等于当前最高价的出价也必须拒绝，且不动金币。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    assert eng.place_bid("a1", "bob", 100, now=10) is False
    assert eng.get_gold("bob") == 1000
    assert eng.place_bid("a1", "bob", 200, now=10) is True
    eng.add_player("charlie", 1000)
    assert eng.place_bid("a1", "charlie", 200, now=20) is False
    assert eng.get_gold("charlie") == 1000


def test_lower_bid_does_not_change_price_or_bidder():
    """低价出价被拒绝后，当前最高价和最高出价者不变（价格不回退）。"""
    eng = _eng()
    eng.add_player("charlie", 1000)
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    assert eng.place_bid("a1", "charlie", 90, now=20) is False
    auc = eng.auctions["a1"]
    assert auc.current_price == 200
    assert auc.current_bidder == "bob"
    assert eng.get_gold("charlie") == 1000


def test_bid_deducts_and_freezes_gold():
    """出价立即扣金并冻结。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    assert eng.place_bid("a1", "bob", 250, now=10) is True
    assert eng.get_gold("bob") == 750
    assert eng.auctions["a1"].frozen_gold["bob"] == 250


def test_seller_paid_only_after_settle():
    """卖家只有在成交结算后才能收到金币。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    assert eng.get_gold("alice") == 1000
    assert eng.settle("a1", now=60) is True
    assert eng.get_gold("alice") == 1200


def test_item_delivered_to_highest_bidder():
    """成交后物品交付给最高出价者，卖家不再持有。"""
    eng = _eng()
    eng.add_player("charlie", 1000)
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    eng.place_bid("a1", "charlie", 300, now=20)
    eng.settle("a1", now=60)
    assert eng.inventory["charlie"] == ["sword"]
    assert "sword" not in eng.inventory["alice"]
    assert "sword" not in eng.inventory["bob"]


def test_trade_log_records_bids_and_sale():
    """交易记录完整记录每一次出价和最终成交。"""
    eng = _eng()
    eng.add_player("charlie", 1000)
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    eng.place_bid("a1", "charlie", 300, now=20)
    eng.settle("a1", now=60)
    assert "a1 bid 200 by bob" in eng.trade_log
    assert "a1 bid 300 by charlie" in eng.trade_log
    assert "a1 sold to charlie for 300" in eng.trade_log


def test_trade_log_records_unsold():
    """流拍也写入交易记录。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.settle("a1", now=60)
    assert "a1 unsold, returned to alice" in eng.trade_log


def test_settle_idempotent_no_duplicate_effects():
    """重复结算幂等：返回 False，交易记录不重复，金币物品不重复发放。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    assert eng.settle("a1", now=60) is True
    assert eng.settle("a1", now=70) is False
    assert eng.settle("a1", now=80) is False
    assert eng.trade_log.count("a1 sold to bob for 200") == 1
    assert eng.get_gold("alice") == 1200
    assert eng.inventory["bob"].count("sword") == 1


def test_settle_expired_auto_settles_all_due():
    """超时后自动结算：有出价的成交，无出价的流拍返还。"""
    eng = _eng()
    eng.inventory["alice"].append("shield")
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.create_auction("a2", "alice", "shield", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    settled = eng.settle_expired(now=60)
    assert sorted(settled) == ["a1", "a2"]
    assert "sword" in eng.inventory["bob"]
    assert "shield" in eng.inventory["alice"]
    assert eng.get_gold("alice") == 1200


def test_bid_after_timeout_triggers_auto_settle():
    """超时后的出价被拒绝，并触发该拍卖自动结算，不会卡在中间状态。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    assert eng.place_bid("a1", "bob", 300, now=60) is False
    auc = eng.auctions["a1"]
    assert auc.settled is True
    assert "sword" in eng.inventory["bob"]
    assert eng.get_gold("alice") == 1200


def test_raise_own_bid_pays_only_delta():
    """同一竞拍者加价只需补差额，冻结金额同步更新。"""
    eng = _eng()
    eng.create_auction("a1", "alice", "sword", 100, 100, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    assert eng.place_bid("a1", "bob", 250, now=20) is True
    assert eng.get_gold("bob") == 750
    assert eng.auctions["a1"].frozen_gold["bob"] == 250


def test_concurrent_bids_no_price_regression():
    """并发出价：价格严格递增不回退，金币守恒（含冻结）。"""
    import threading

    eng = _eng()
    bidders = ["p%d" % i for i in range(8)]
    for pid in bidders:
        eng.add_player(pid, 100000)
    eng.create_auction("a1", "alice", "sword", 100, 1000, now=0)
    amounts = [150, 90, 300, 250, 500, 120, 800, 400]
    barrier = threading.Barrier(len(bidders))
    results = {}

    def worker(pid, amt):
        barrier.wait()
        results[pid] = eng.place_bid("a1", pid, amt, now=10)

    threads = [threading.Thread(target=worker, args=(p, a))
               for p, a in zip(bidders, amounts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    auc = eng.auctions["a1"]
    accepted = [b.amount for b in auc.bids]
    assert all(x < y for x, y in zip(accepted, accepted[1:])), "被接受的出价必须严格递增"
    assert auc.current_price == max(amounts)
    assert auc.current_bidder == "p6"
    assert sum(1 for v in results.values() if v) == len(accepted)
    total = sum(eng.get_gold(p) for p in bidders)
    frozen = sum(auc.frozen_gold.values())
    assert total + frozen == 100000 * len(bidders), "并发下金币必须守恒"


def test_gold_conservation_full_cycle():
    """完整周期金币守恒：出价冻结 + 结算转账前后总额不变。"""
    eng = _eng()
    eng.add_player("charlie", 1000)
    players = ["alice", "bob", "charlie"]
    total_before = sum(eng.get_gold(p) for p in players)
    eng.create_auction("a1", "alice", "sword", 100, 50, now=0)
    eng.place_bid("a1", "bob", 200, now=10)
    eng.place_bid("a1", "charlie", 300, now=20)
    eng.settle("a1", now=60)
    total_after = sum(eng.get_gold(p) for p in players)
    frozen = sum(sum(a.frozen_gold.values()) for a in eng.auctions.values())
    assert frozen == 0
    assert total_after == total_before
