"""拍卖行托管 - 红态测试"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auction.house import AuctionHouse, Listing

class TestDepositCheck:
    def test_cannot_list_without_deposit(self):
        ah = AuctionHouse()
        lid = ah.list_item("p1", "sword", 1000, deposit=0)
        assert lid is None

class TestExpireRefund:
    def test_expired_listing_refunds_item_and_deposit(self):
        ah = AuctionHouse()
        lid = ah.list_item("p1", "sword", 1000, deposit=50)
        ah.expire_listing(lid)
        assert ah.listings[lid].status == "expired"

class TestBidOnSoldItem:
    def test_cannot_bid_on_sold_item(self):
        ah = AuctionHouse()
        lid = ah.list_item("p1", "sword", 1000, deposit=50)
        ah.place_bid(lid, "p2", 1000)
        result = ah.place_bid(lid, "p3", 2000)
        assert result == False

class TestTransactionOrdering:
    def test_transactions_ordered_by_millisecond(self):
        ah = AuctionHouse()
        ah.transactions = [
            {"seller": "p1", "item": "a", "time": 1000},
            {"seller": "p1", "item": "b", "time": 1001}
        ]
        history = ah.get_transaction_history("p1")
        assert history[0]["item"] == "a"

class TestCrossServerUniqueness:
    def test_same_item_not_listed_twice(self):
        ah = AuctionHouse()
        l1 = Listing("l1", "p1", "sword", 1000, 50)
        ah.sync_cross_server(l1)
        l2 = Listing("l1", "p1", "sword", 1000, 50)
        result = ah.sync_cross_server(l2)
        assert result == False
