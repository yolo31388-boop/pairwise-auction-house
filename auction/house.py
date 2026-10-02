"""拍卖行托管"""
from dataclasses import dataclass, field
import time

@dataclass
class Listing:
    lid: str
    seller: str
    item: str
    price: int
    deposit: int
    status: str = "active"  # active/sold/expired/removed
    expire_time: float = 0

class AuctionHouse:
    MIN_DEPOSIT = 1  # 上架最低托管费

    def __init__(self):
        self.listings: dict[str, Listing] = {}
        self.transactions: list = []
        self.refunds: list = []  # 托管到期返还记录
        self._tx_seq = 0  # 交易序号，保证同毫秒内多笔交易的顺序

    def list_item(self, seller: str, item: str, price: int, deposit: int) -> str:
        if deposit < self.MIN_DEPOSIT:
            return None  # 托管费不足，拒绝上架
        lid = f"list_{len(self.listings)}"
        self.listings[lid] = Listing(lid, seller, item, price, deposit)
        return lid

    def expire_listing(self, lid: str) -> bool:
        listing = self.listings.get(lid)
        if not listing or listing.status != "active":
            return False
        listing.status = "expired"
        # 托管到期：返还物品和托管费给卖家
        self.refunds.append({
            "seller": listing.seller,
            "item": listing.item,
            "deposit": listing.deposit,
        })
        return True

    def place_bid(self, lid: str, bidder: str, amount: int) -> bool:
        listing = self.listings.get(lid)
        if not listing or listing.status != "active":
            return False
        if amount >= listing.price:
            listing.status = "sold"
            self._record_transaction(listing, bidder, amount)
            return True
        return False

    def _record_transaction(self, listing: Listing, buyer: str, amount: int):
        self._tx_seq += 1
        self.transactions.append({
            "seller": listing.seller,
            "buyer": buyer,
            "item": listing.item,
            "amount": amount,
            "time": int(time.time() * 1000),  # 毫秒级时间戳
            "seq": self._tx_seq,
        })

    def get_transaction_history(self, seller: str) -> list:
        txs = [t for t in self.transactions if t["seller"] == seller]
        return sorted(txs, key=lambda t: (t["time"], t.get("seq", 0)))

    def sync_cross_server(self, listing: Listing) -> bool:
        # 唯一性锁：同 lid 或同卖家同物品的活跃挂单不可重复同步
        if listing.lid in self.listings:
            return False
        for existing in self.listings.values():
            if (existing.seller == listing.seller
                    and existing.item == listing.item
                    and existing.status == "active"):
                return False
        self.listings[listing.lid] = listing
        return True
