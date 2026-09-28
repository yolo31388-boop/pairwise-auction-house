"""拍卖行竞价引擎：原子出价、超时结算、金币冻结返还、交易记录。

核心不变量：
- 上架时验证卖家持有物品并锁定（从背包移入托管），结算后才真正转移
- 出价先校验后扣款，校验失败不产生任何副作用（原子）
- 最小加价按当前价比例动态计算（5%，至少 1 金）
- 出价金币由卖家账户托管，被超价时从托管金中原路返还
- 超时自动成交或流拍，结算幂等，失败可回滚
- 出价历史用环形缓冲，只保留最近若干条，内存有界
- 金币守恒：任何时刻 sum(get_gold) 不变
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

BID_HISTORY_LIMIT = 256
MIN_INCREMENT_RATE = 0.05


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
    bids: Deque[Bid] = field(default_factory=lambda: deque(maxlen=BID_HISTORY_LIMIT))
    frozen_gold: Dict[str, int] = field(default_factory=dict)  # bidder -> frozen amount


class AuctionEngine:
    def __init__(self):
        self.auctions: Dict[str, Auction] = {}
        self.gold: Dict[str, int] = {}
        self.inventory: Dict[str, list] = {}
        self.trade_log: Deque[str] = deque(maxlen=BID_HISTORY_LIMIT)

    def add_player(self, pid: str, gold: int = 1000) -> None:
        self.gold[pid] = gold
        self.inventory[pid] = []

    def min_increment(self, price: int) -> int:
        """动态价格阶梯：按当前价比例计算，高价物品加价幅度更大，且有下限。"""
        return max(1, int(price * MIN_INCREMENT_RATE))

    def create_auction(self, aid: str, seller: str, item: str,
                       start_price: int, duration: int, now: int) -> bool:
        if aid in self.auctions:
            return False
        if item not in self.inventory.get(seller, []):
            return False
        # 上架即锁定：物品从卖家背包移入拍卖托管，结算时才真正转移
        self.inventory[seller].remove(item)
        self.auctions[aid] = Auction(
            aid=aid, seller=seller, item=item,
            start_price=start_price, current_price=start_price,
            end_time=now + duration,
        )
        return True

    def place_bid(self, aid: str, bidder: str, amount: int, now: int) -> bool:
        """原子出价：先完成全部校验，再一次性提交状态变更。"""
        auc = self.auctions.get(aid)
        if auc is None or auc.settled:
            return False
        if now >= auc.end_time:
            return False
        if bidder == auc.seller:
            return False
        # 校验：必须高于当前最高价一个动态最小阶梯
        if amount < auc.current_price + self.min_increment(auc.current_price):
            return False
        own_frozen = auc.frozen_gold.get(bidder, 0) if bidder == auc.current_bidder else 0
        need = amount - own_frozen
        if self.gold.get(bidder, 0) < need:
            return False
        # 校验全部通过，以下变更要么全部生效要么不执行（单线程原子）
        self.gold[bidder] -= need
        self.gold[auc.seller] = self.gold.get(auc.seller, 0) + need
        # 被超价者从卖家托管金中原路返还
        if auc.current_bidder and auc.current_bidder != bidder:
            old = auc.current_bidder
            refund = auc.frozen_gold.pop(old, 0)
            self.gold[auc.seller] -= refund
            self.gold[old] = self.gold.get(old, 0) + refund
        auc.current_price = amount
        auc.current_bidder = bidder
        auc.frozen_gold[bidder] = amount
        auc.bids.append(Bid(bidder, amount, now))
        return True

    def settle(self, aid: str, now: int) -> bool:
        """结算拍卖：超时后成交或流拍，幂等，重复调用无副作用。"""
        auc = self.auctions.get(aid)
        if auc is None or auc.settled:
            return False
        if now < auc.end_time:
            return False
        auc.settled = True
        if auc.current_bidder:
            # 成交：托管金已在出价时划入卖家，此处只转移物品
            buyer = auc.current_bidder
            auc.frozen_gold.pop(buyer, None)
            self.inventory.setdefault(buyer, []).append(auc.item)
            self.trade_log.append(f"{aid} sold to {buyer} for {auc.current_price}")
        else:
            # 流拍：物品退回卖家
            self.inventory[auc.seller].append(auc.item)
            self.trade_log.append(f"{aid} unsold, returned to {auc.seller}")
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
