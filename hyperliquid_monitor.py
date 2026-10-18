#!/usr/bin/env python3
"""Hyperliquid BTC 15m market analysis for ATLAS. PUBLIC READ-ONLY; NO TRADING."""
from __future__ import annotations

import json
import logging
import math
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bot import ema, rsi, atr, signal

INFO_URL = "https://api.hyperliquid.xyz/info"
INTERVAL_MS = 15 * 60 * 1000
MAX_AGE_MS = 25 * 60 * 1000


def iso_utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def fetch_closed_candles(now_ms=None, opener=None):
    """Only market candles. No wallets, API keys, signatures, or trade endpoints."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    if opener is None:
        opener = urllib.request.urlopen
    body = {
        "type": "candleSnapshot",
        "req": {
            "coin": "BTC",
            "interval": "15m",
            "startTime": now_ms - 180 * INTERVAL_MS,
            "endTime": now_ms,
        },
    }
    req = urllib.request.Request(
        INFO_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "ATLAS-PAPER-READONLY/1.0"},
        method="POST",
    )
    with opener(req, timeout=15) as response:
        raw = json.load(response)
    if not isinstance(raw, list):
        raise ValueError("Invalid Hyperliquid response")

    bars = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Unexpected candle format")
        if item.get("s") != "BTC" or item.get("i") != "15m":
            raise ValueError("Unexpected market or interval")
        start, end = int(item["t"]), int(item["T"])
        if end >= now_ms:
            continue  # Never use an unfinished 15m candle.
        b = {
            "start": start,
            "end": end,
            "o": float(item["o"]),
            "h": float(item["h"]),
            "l": float(item["l"]),
            "c": float(item["c"]),
            "volume": float(item["v"]),
        }
        if (
            end < start
            or not all(math.isfinite(b[k]) for k in ("o", "h", "l", "c", "volume"))
            or min(b["o"], b["h"], b["l"], b["c"]) <= 0
            or b["volume"] < 0
            or b["l"] > min(b["o"], b["c"])
            or b["h"] < max(b["o"], b["c"])
        ):
            raise ValueError("Invalid Hyperliquid OHLCV data")
        bars.append(b)
    if len(bars) < 65:
        raise ValueError("Insufficient closed 15m candles")
    if any(a["start"] >= b["start"] for a, b in zip(bars, bars[1:])):
        raise ValueError("Candles are not in strictly increasing order")
    if now_ms - bars[-1]["end"] > MAX_AGE_MS:
        raise ValueError("Stale Hyperliquid candles; refusing to report a fresh market")
    return bars


def build_report(bars, now_ms=None):
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    closes = [b["c"] for b in bars]
    current = closes[-1]
    fast, medium, slow = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    momentum, volatility = rsi(closes, 14), atr(bars, 14)
    raw_signal, _ = signal(bars)
    if fast is None or medium is None or slow is None or momentum is None or volatility is None:
        raise ValueError("Insufficient data for market indicators")
    if current > fast > medium > slow:
        bias = "BULLISH"
    elif current < fast < medium < slow:
        bias = "BEARISH"
    else:
        bias = "MIXED / WAIT"
    prior_20 = bars[-21:-1]
    return {
        "project": "ATLAS-PAPER-BOT",
        "exchange": "Hyperliquid",
        "source": INFO_URL,
        "market": "BTC perpetual",
        "interval": "15m",
        "mode": "READ_ONLY_ANALYSIS",
        "last_closed_candle_utc": iso_utc(bars[-1]["end"]),
        "generated_at_utc": iso_utc(now_ms),
        "close_usd": round(current, 2),
        "ema9": round(fast, 2),
        "ema21": round(medium, 2),
        "ema50": round(slow, 2),
        "rsi14": round(momentum, 2),
        "atr14_usd": round(volatility, 2),
        "support_20_prior_candles": round(min(b["l"] for b in prior_20), 2),
        "resistance_20_prior_candles": round(max(b["h"] for b in prior_20), 2),
        "trend": bias,
        "existing_atlas_strategy_signal": raw_signal or "NO_SIGNAL",
        "disclaimer": "Analysis only. No trades, orders, wallet access, or guaranteed profits.",
    }


def write_report(report, json_path=Path("data/hyperliquid_btc_15m.json"),
                 markdown_path=Path("data/hyperliquid_btc_15m.md")):
    json_path = Path(json_path)
    markdown_path = Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    temp_json = json_path.with_suffix(".json.tmp")
    temp_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp_json, json_path)
    md = (
        "# ATLAS | Hyperliquid BTC (15m)\n\n"
        f"- Closed candle: **{report['last_closed_candle_utc']}**\n"
        f"- Price: **${report['close_usd']:,.2f}**\n"
        f"- Market trend: **{report['trend']}**\n"
        f"- EMA9 / EMA21 / EMA50: {report['ema9']} / {report['ema21']} / {report['ema50']}\n"
        f"- RSI14: {report['rsi14']} | ATR14: ${report['atr14_usd']}\n"
        f"- Prior 20-candle support / resistance: ${report['support_20_prior_candles']} / ${report['resistance_20_prior_candles']}\n"
        f"- ATLAS strategy signal (informational): **{report['existing_atlas_strategy_signal']}**\n\n"
        "**READ ONLY. No orders, no API wallet, no real trading.**\n"
    )
    temp_md = markdown_path.with_suffix(".md.tmp")
    temp_md.write_text(md, encoding="utf-8")
    os.replace(temp_md, markdown_path)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    now_ms = int(time.time() * 1000)
    bars = fetch_closed_candles(now_ms)
    report = build_report(bars, now_ms)
    write_report(report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
