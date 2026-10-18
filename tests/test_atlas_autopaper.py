"""Offline-only tests for the multi-market autonomous PAPER engine."""
import copy
import unittest
from unittest.mock import patch

import atlas_autopaper as a
from strategy_v2 import Setup

NOW = 1792332000000


def bars(now=NOW, step=900000, count=240, price=100.0):
    # Latest bar closed 5 minutes ago. O,H,L,C all consistent.
    last_end = now - 5 * 60_000
    first_start = last_end - (count - 1) * step - step + 1
    return [dict(start=first_start+i*step, end=first_start+(i+1)*step-1,
                 o=price, h=price+2, l=price-2, c=price, volume=5000)
            for i in range(count)]


class AutoPaperTests(unittest.TestCase):
    def setUp(self):
        self.state = a.fresh_state()
        self.b15 = bars()
        self.b1 = bars(step=3600000)
        # latest 1h finishes 5 minutes before latest 15m, for temporal safety
        self.b1[-1]["end"] = self.b15[-1]["end"] - 1
        self.data = {"BTCUSDT": {"15m": self.b15, "1h": self.b1}}

    def run_mock(self, side="LONG"):
        setup = Setup(side, 1., 6 if side else 0, 6, 1. if side else None, 1.8, "test")
        with patch.object(a, "choose_markets", return_value=["BTCUSDT"]), \
             patch.object(a, "closed_candles", side_effect=lambda sym, interval, now, fetch: self.data[sym][interval]), \
             patch.object(a, "analyze", return_value=setup), \
             patch("strategy_v2.adx", return_value=25):
            return a.run_cycle(self.state, NOW)

    def test_three_x_and_first_entry_paper_only(self):
        result = self.run_mock()
        self.assertEqual(result["entry"]["simulated_leverage"], 3)
        self.assertEqual(self.state["entries_today"], 1)
        self.assertEqual(len(self.state["positions"]), 1)
        p = self.state["positions"]["BTCUSDT"]
        self.assertEqual(p["leverage"], 3)
        self.assertLessEqual(p["margin"], a.START_BALANCE * .10)
        self.assertLessEqual(p["qty"] * p["entry"], a.START_BALANCE * .30)
        self.assertGreater(p["entry_fee"], 0)

    def test_duplicate_candle_no_second_entry(self):
        self.run_mock()
        self.state["positions"].clear()
        result = self.run_mock()
        self.assertIsNone(result["entry"])
        self.assertEqual(self.state["entries_today"], 1)

    def test_max_five_daily_not_forced(self):
        self.state["day"] = __import__("datetime").datetime.fromtimestamp(
            NOW/1000, __import__("datetime").timezone.utc).date().isoformat()
        self.state["entries_today"] = 5
        result = self.run_mock()
        self.assertIsNone(result["entry"])
        self.assertEqual(self.state["entries_today"], 5)

    def test_no_signal_means_zero_entries(self):
        result = self.run_mock(side=None)
        self.assertIsNone(result["entry"])
        self.assertFalse(self.state["positions"])

    def test_daily_loss_halts_entries(self):
        self.state["day"] = __import__("datetime").datetime.fromtimestamp(
            NOW/1000, __import__("datetime").timezone.utc).date().isoformat()
        self.state["day_start"] = 5000
        self.state["balance"] = 4850
        self.assertIsNone(self.run_mock()["entry"])

    def test_market_selection_uses_liquid_live_usdt_perpetual_only(self):
        def get(path, params=None):
            if path.endswith("exchangeInfo"):
                return {"symbols": [
                    {"symbol":"BTCUSDT","quoteAsset":"USDT","contractType":"PERPETUAL","status":"TRADING"},
                    {"symbol":"ETHUSDT","quoteAsset":"USDT","contractType":"PERPETUAL","status":"TRADING"},
                    {"symbol":"BADUSDT","quoteAsset":"USDT","contractType":"PERPETUAL","status":"BREAK"},
                    {"symbol":"BTCUSD","quoteAsset":"USD","contractType":"PERPETUAL","status":"TRADING"}]}
            return [{"symbol":"ETHUSDT","quoteVolume":"90000000"},
                    {"symbol":"BTCUSDT","quoteVolume":"100000000"},
                    {"symbol":"BADUSDT","quoteVolume":"1000000000"},
                    {"symbol":"BTCUSD","quoteVolume":"1000000000"}]
        self.assertEqual(a.choose_markets(fetch=get),["BTCUSDT","ETHUSDT"])

    def test_block_any_private_or_order_endpoint(self):
        for p in ("/fapi/v1/order","/fapi/v3/account","/fapi/v1/algoOrder"):
            with self.assertRaises(a.PaperError):
                a.public_get(p)

    def test_exchange_feed_missing_fails_closed(self):
        with patch.object(a,"choose_markets",return_value=["BTCUSDT"]), \
             patch.object(a,"closed_candles",side_effect=a.PaperError("offline")):
            with self.assertRaisesRegex(a.PaperError,"All Binance"):
                a.run_cycle(self.state,NOW)
        self.assertEqual(self.state["balance"],5000)
        self.assertFalse(self.state["positions"])

    def test_stop_first_if_stop_and_target_same_bar(self):
        self.run_mock()
        p = self.state["positions"]["BTCUSDT"]
        # Must be a newer bar than entry, crossing both stop and target.
        b = dict(self.b15[-1])
        b["start"] += 900000
        b["end"] += 900000
        b["o"] = p["entry"]
        b["h"] = p["target"]+1
        b["l"] = p["stop"]-1
        a.mark_positions(self.state,{"BTCUSDT":{"15m":[self.b15[-1],b]}})
        self.assertEqual(self.state["trades"][-1]["reason"],"STOP")
        self.assertFalse(self.state["positions"])


if __name__ == "__main__":
    unittest.main()
