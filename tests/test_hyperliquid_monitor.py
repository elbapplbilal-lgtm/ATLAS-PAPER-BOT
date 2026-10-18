"""Offline tests: no network, keys or order permissions required."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from hyperliquid_monitor import INFO_URL, fetch_closed_candles, build_report, write_report

NOW_MS = 1_800_000_000_000
CANDLE_MS = 900_000


def sample(n=80):
    items = []
    for i in range(n):
        start = NOW_MS - n * CANDLE_MS + i * CANDLE_MS
        price = 100000 + i * 10
        items.append({
            "s": "BTC", "i": "15m", "t": start, "T": start + CANDLE_MS - 1,
            "o": str(price - 4), "h": str(price + 12),
            "l": str(price - 15), "c": str(price),
            "v": "42.0"
        })
    return items


class FakeResponse(io.BytesIO):
    pass


def as_opener(items):
    def open_fake(request, timeout):
        assert request.full_url == INFO_URL
        assert request.get_method() == "POST"
        body = json.loads(request.data)
        assert body["type"] == "candleSnapshot"
        assert body["req"]["coin"] == "BTC"
        assert body["req"]["interval"] == "15m"
        assert timeout == 15
        return FakeResponse(json.dumps(items).encode())
    return open_fake


class HyperliquidMonitorTests(unittest.TestCase):
    def test_reads_only_public_closed_btc_candles(self):
        items = sample()
        extra = dict(items[-1], t=NOW_MS, T=NOW_MS + CANDLE_MS - 1)
        bars = fetch_closed_candles(now_ms=NOW_MS, opener=as_opener(items + [extra]))
        self.assertEqual(len(bars), 80)
        self.assertLess(bars[-1]["end"], NOW_MS)
        report = build_report(bars, now_ms=NOW_MS)
        self.assertEqual(report["mode"], "READ_ONLY_ANALYSIS")
        self.assertEqual(report["market"], "BTC perpetual")
        self.assertIn(report["trend"], ("BULLISH", "BEARISH", "MIXED / WAIT"))

    def test_rejects_stale_market_data(self):
        with self.assertRaisesRegex(ValueError, "Stale"):
            fetch_closed_candles(now_ms=NOW_MS + 30 * 60_000, opener=as_opener(sample()))

    def test_rejects_invalid_candles(self):
        items = sample()
        items[-1]["c"] = "0"
        with self.assertRaisesRegex(ValueError, "Invalid"):
            fetch_closed_candles(now_ms=NOW_MS, opener=as_opener(items))

    def test_report_is_saved_locally_without_orders(self):
        report = build_report(fetch_closed_candles(NOW_MS, as_opener(sample())), NOW_MS)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            jp, mp = folder / "report.json", folder / "report.md"
            write_report(report, jp, mp)
            self.assertEqual(json.loads(jp.read_text())["mode"], "READ_ONLY_ANALYSIS")
            self.assertIn("No orders", mp.read_text())


if __name__ == "__main__":
    unittest.main()
