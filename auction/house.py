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
    def __init__(self):
        self.listings: dict[str, Listing] = {}
        self.transactions: list = []
        self.returns: list = []  # 托管到期返还记录
        self._seq = 0  # 交易序号，同一毫秒内保证有序
        self._item_locks: set[str] = set()  # 跨服物品唯一性锁

    def list_item(self, seller: str, item: str, price: int, deposit: int) -> str:
        if deposit <= 0:  # 托管费不足，拒绝上架
            return None
        lid = f"list_{len(self.listings)}"
        self.listings[lid] = Listing(lid, seller, item, price, deposit)
        self._item_locks.add(item)
        return lid

    def expire_listing(self, lid: str) -> bool:
        listing = self.listings.get(lid)
        if not listing or listing.status != "active":
            return False
        listing.status = "expired"
        # 返还托管物品和托管费
        self.returns.append({
            "seller": listing.seller,
            "item": listing.item,
            "deposit": listing.deposit,
        })
        self._item_locks.discard(listing.item)
        return True

    def place_bid(self, lid: str, bidder: str, amount: int) -> bool:
        listing = self.listings.get(lid)
        if not listing or listing.status != "active":
            return False
        if amount >= listing.price:
            listing.status = "sold"
            self._seq += 1
            self.transactions.append({
                "seller": listing.seller,
                "buyer": bidder,
                "item": listing.item,
                "price": amount,
                "time": int(time.time() * 1000),  # 毫秒级时间戳
                "seq": self._seq,
            })
            self._item_locks.discard(listing.item)
            return True
        return False

    def get_transaction_history(self, seller: str) -> list:
        # 毫秒级时间戳 + 序号排序，同一毫秒内的交易顺序确定
        return sorted(
            (t for t in self.transactions if t["seller"] == seller),
            key=lambda t: (t["time"], t.get("seq", 0)),
        )

    def sync_cross_server(self, listing: Listing) -> bool:
        # 唯一性锁：同一 lid 或同一物品已在交易行，拒绝同步
        if listing.lid in self.listings or listing.item in self._item_locks:
            return False
        self.listings[listing.lid] = listing
        self._item_locks.add(listing.item)
        return True
