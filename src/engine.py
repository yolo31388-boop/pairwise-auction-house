"""拍卖行竞价引擎：原子出价、超时结算、金币冻结返还、交易记录。

核心不变量：
- 出价必须原子检查当前最高价
- 超时自动成交或流拍
- 出价金币冻结，被超价返还
- 成交后卖家收款、买家得物品
- 幂等结算
- 金币守恒
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Bid:
    bidder: str
    amount: int
    timestamp: int


@dataclass
class Auction:
    aid: str
    seller: str
    item: str
    start_price: int
    end_time: int
    current_price: int = 0
    current_bidder: Optional[str] = None
    settled: bool = False
    bids: List[Bid] = field(default_factory=list)
    frozen_gold: Dict[str, int] = field(default_factory=dict)  # bidder -> frozen amount
    # 每个拍卖一把锁：同一拍卖的出价/结算串行化，不同拍卖之间仍可并发。
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)


class AuctionEngine:
    def __init__(self):
        self.auctions: Dict[str, Auction] = {}
        self.gold: Dict[str, int] = {}
        self.inventory: Dict[str, List[str]] = {}
        self.trade_log: List[str] = []

    def add_player(self, pid: str, gold: int = 1000) -> None:
        self.gold[pid] = gold
        self.inventory[pid] = []

    def create_auction(self, aid: str, seller: str, item: str,
                       start_price: int, duration: int, now: int) -> bool:
        if aid in self.auctions:
            return False
        if item not in self.inventory.get(seller, []):
            return False
        self.inventory[seller].remove(item)
        self.auctions[aid] = Auction(
            aid=aid, seller=seller, item=item,
            start_price=start_price, current_price=start_price,
            end_time=now + duration,
        )
        return True

    def place_bid(self, aid: str, bidder: str, amount: int, now: int) -> bool:
        """出价：在拍卖锁内原子地检查最高价、扣金、记录出价、更新最高价。

        所有前置校验通过后才变更任何状态；任一校验失败直接拒绝，
        不发生扣金，无需回滚。新出价必须严格大于当前最高价。
        """
        auc = self.auctions.get(aid)
        if auc is None:
            return False
        with auc.lock:
            if now >= auc.end_time:
                # 拍卖已超时：自动结算（成交或流拍），拒绝新的出价。
                self._settle_locked(auc)
                return False
            if auc.settled:
                return False
            if bidder == auc.seller:
                return False
            if amount <= auc.current_price:
                # 必须严格大于当前最高价，否则拒绝（未扣金，无需返还）。
                return False
            already_frozen = auc.frozen_gold.get(bidder, 0)
            needed = amount - already_frozen  # 自己加价时只需补差额
            if self.gold.get(bidder, 0) < needed:
                return False
            # 前置校验全部通过，开始原子变更：扣金 -> 解冻旧最高出价 -> 记录 -> 更新最高价。
            self.gold[bidder] -= needed
            if auc.current_bidder and auc.current_bidder != bidder:
                old = auc.current_bidder
                self.gold[old] = self.gold.get(old, 0) + auc.frozen_gold.pop(old, 0)
            auc.current_price = amount
            auc.current_bidder = bidder
            auc.frozen_gold[bidder] = amount
            auc.bids.append(Bid(bidder, amount, now))
            self.trade_log.append(f"{aid} bid {amount} by {bidder}")
            return True

    def settle(self, aid: str, now: int) -> bool:
        """结算拍卖：超时后成交（最高价者得）或流拍（物品返还卖家）。

        幂等：已结算的拍卖重复结算直接返回 False，不会重复成交/发奖。
        """
        auc = self.auctions.get(aid)
        if auc is None:
            return False
        with auc.lock:
            if auc.settled:
                return False
            if now < auc.end_time:
                return False
            self._settle_locked(auc)
            return True

    def settle_expired(self, now: int) -> List[str]:
        """自动结算所有已到期的拍卖，返回本次结算的拍卖 id 列表。"""
        settled = []
        for aid in list(self.auctions):
            auc = self.auctions[aid]
            if not auc.settled and now >= auc.end_time:
                if self.settle(aid, now):
                    settled.append(aid)
        return settled

    def _settle_locked(self, auc: Auction) -> None:
        """在持有 auc.lock 的前提下执行结算。调用前需检查未 settled。"""
        if auc.settled:
            return
        if auc.current_bidder:
            # 成交：卖家收到冻结的金币，买家获得物品。
            buyer = auc.current_bidder
            self.gold[auc.seller] = self.gold.get(auc.seller, 0) \
                + auc.frozen_gold.pop(buyer, auc.current_price)
            self.inventory.setdefault(buyer, []).append(auc.item)
            self.trade_log.append(f"{auc.aid} sold to {buyer} for {auc.current_price}")
        else:
            # 流拍：物品返还卖家。
            self.inventory.setdefault(auc.seller, []).append(auc.item)
            self.trade_log.append(f"{auc.aid} unsold, returned to {auc.seller}")
        auc.settled = True

    def get_gold(self, pid: str) -> int:
        return self.gold.get(pid, 0)

    def snapshot(self) -> dict:
        return {
            "gold": dict(self.gold),
            "inventory": {k: list(v) for k, v in self.inventory.items()},
            "auctions": {aid: {"price": a.current_price, "bidder": a.current_bidder,
                               "settled": a.settled} for aid, a in self.auctions.items()},
        }
