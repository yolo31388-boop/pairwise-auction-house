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
        """出价。BUG：不原子检查当前最高价，先扣金再检查。"""
        auc = self.auctions.get(aid)
        if auc is None or auc.settled:
            return False
        if now >= auc.end_time:
            return False
        if bidder == auc.seller:
            return False
        # BUG：先扣金币，再检查价格
        if self.gold.get(bidder, 0) < amount:
            return False
        self.gold[bidder] -= amount
        # 冻结之前出价者的金币应该先返还
        if auc.current_bidder and auc.current_bidder != bidder:
            old = auc.current_bidder
            self.gold[old] = self.gold.get(old, 0) + auc.frozen_gold.get(old, 0)
            auc.frozen_gold.pop(old, None)
        # BUG：不检查 amount > current_price，直接接受
        auc.current_price = amount  # BUG：应该 if amount <= auc.current_price: return False 并返还金币
        auc.current_bidder = bidder
        auc.frozen_gold[bidder] = amount
        auc.bids.append(Bid(bidder, amount, now))
        return True

    def settle(self, aid: str, now: int) -> bool:
        """结算拍卖。BUG：超时后不自动结算，需要手动调用且可能重复。"""
        auc = self.auctions.get(aid)
        if auc is None:
            return False
        if now < auc.end_time:
            return False
        # BUG：不检查 settled，可能重复结算
        if auc.current_bidder:
            # 成交
            buyer = auc.current_bidder
            self.gold[auc.seller] += auc.frozen_gold.get(buyer, auc.current_price)
            auc.frozen_gold.pop(buyer, None)
            self.inventory[buyer].append(auc.item)
            self.trade_log.append(f"{aid} sold to {buyer} for {auc.current_price}")
        else:
            # 流拍
            self.inventory[auc.seller].append(auc.item)
            self.trade_log.append(f"{aid} unsold, returned to {auc.seller}")
        auc.settled = True
        return True

    def get_gold(self, pid: str) -> int:
        return self.gold.get(pid, 0)

    def snapshot(self) -> dict:
        return {
            "gold": dict(self.gold),
            "inventory": {k: list(v) for k, v in self.inventory.items()},
            "auctions": {aid: {"price": a.current_price, "bidder": a.current_bidder,
                               "settled": a.settled} for aid, a in self.auctions.items()},
        }
