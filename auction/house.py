"""拍卖行托管 - 含5个bug"""
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
        self.transactions: list = []  # bug4: 秒级时间戳

    def list_item(self, seller: str, item: str, price: int, deposit: int) -> str:
        # bug1: 不检查托管费
        lid = f"list_{len(self.listings)}"
        self.listings[lid] = Listing(lid, seller, item, price, deposit)
        return lid

    def expire_listing(self, lid: str) -> bool:
        # bug2: 不返还物品和费用
        listing = self.listings.get(lid)
        if listing:
            listing.status = "expired"
        return True

    def place_bid(self, lid: str, bidder: str, amount: int) -> bool:
        # bug3: 不检查物品是否已售出
        listing = self.listings.get(lid)
        if not listing:
            return False
        if amount >= listing.price:
            listing.status = "sold"
            return True
        return False

    def get_transaction_history(self, seller: str) -> list:
        # bug4: 秒级时间戳排序
        return [t for t in self.transactions if t["seller"] == seller]

    def sync_cross_server(self, listing: Listing) -> bool:
        # bug5: 无唯一性检查
        self.listings[listing.lid] = listing
        return True
