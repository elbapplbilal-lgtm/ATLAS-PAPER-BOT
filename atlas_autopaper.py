#!/usr/bin/env python3
"""ATLAS autonomous multi-symbol PAPER runner.

READS PUBLIC Binance Futures OHLCV ONLY. It never reads API secrets, never
creates Binance orders, and cannot access private Binance account endpoints.
3x leverage is simulated for *margin sizing*; fills are estimates.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from strategy_v2 import analyze

HOST = "https://fapi.binance.com"
ALLOWED = frozenset(("/fapi/v1/exchangeInfo", "/fapi/v1/ticker/24hr", "/fapi/v1/klines"))
START_BALANCE = 5000.0
LEVERAGE = 3  # simulated isolated leverage only
MAX_DAILY_ENTRIES = 5  # MAXIMUM, not a daily quota
MAX_OPEN = 1
MAX_MARKETS = 20
MIN_24H_QUOTE_VOLUME = 25_000_000.0
RISK_PER_ENTRY = 0.005
MAX_MARGIN_FRACTION = 0.10
MAX_DAILY_DRAWDOWN = 0.02
FEE = 0.0004  # per-side assumed taker fee
SLIP = 0.0003  # simulated adverse slippage
STATE_PATH = Path("data/autopaper_state.json")
REPORT_PATH = Path("data/autopaper_report.json")


class PaperError(RuntimeError):
    pass


def public_get(path, params=None):
    """Whitelisted public GET only. No authenticated API and NO trades."""
    if path not in ALLOWED:
        raise PaperError("Only public Binance GET endpoints allowed")
    query = urllib.parse.urlencode(params or {})
    url = HOST + path + ("?" + query if query else "")
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "ATLAS-PAPER-SCAN/1"})
    with urllib.request.urlopen(req, timeout=12) as response:
        data = json.load(response)
    return data


def fresh_state():
    return {
        "balance": START_BALANCE, "day": "", "day_start": START_BALANCE,
        "entries_today": 0, "positions": {}, "last_scanned": {},
        "trades": [], "scans": 0,
    }


def load_state(path=STATE_PATH):
    if not path.exists():
        return fresh_state()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(k in value for k in fresh_state()):
        raise PaperError("Corrupted simulation state; refusing reset")
    if not isinstance(value["positions"], dict) or not isinstance(value["last_scanned"], dict):
        raise PaperError("Invalid simulation positions or scan state")
    return value


def save_json_atomic(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def choose_markets(fetch=public_get, limit=MAX_MARKETS):
    info = fetch("/fapi/v1/exchangeInfo")
    ticker = fetch("/fapi/v1/ticker/24hr")
    if not isinstance(info, dict) or not isinstance(info.get("symbols"), list):
        raise PaperError("Invalid symbol universe")
    if not isinstance(ticker, list):
        raise PaperError("Invalid volume ranking")
    eligible = {s["symbol"] for s in info["symbols"]
                if s.get("status") == "TRADING"
                and s.get("contractType") == "PERPETUAL"
                and s.get("quoteAsset") == "USDT"
                and isinstance(s.get("symbol"), str)}
    ranking = []
    for row in ticker:
        symbol = row.get("symbol")
        if symbol not in eligible:
            continue
        try:
            volume = float(row["quoteVolume"])
        except (ValueError, TypeError, KeyError):
            continue
        if math.isfinite(volume) and volume >= MIN_24H_QUOTE_VOLUME:
            ranking.append((volume, symbol))
    ranking.sort(key=lambda x: (-x[0], x[1]))
    if not ranking:
        raise PaperError("No verified liquid USDT perpetual markets; no entries")
    return [sym for _, sym in ranking[:limit]]


def closed_candles(symbol, interval, now_ms, fetch=public_get):
    if interval not in ("15m", "1h") or not symbol.endswith("USDT"):
        raise PaperError("Unsupported market/interval")
    raw = fetch("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": 300})
    if not isinstance(raw, list):
        raise PaperError("Invalid public candles")
    bars = []
    for v in raw:
        if not isinstance(v, list) or len(v) < 7:
            raise PaperError("Bad OHLCV shape")
        b = dict(start=int(v[0]), o=float(v[1]), h=float(v[2]), l=float(v[3]),
                 c=float(v[4]), volume=float(v[5]), end=int(v[6]))
        if not all(math.isfinite(b[k]) for k in ("o", "h", "l", "c", "volume")):
            raise PaperError("Non-finite OHLCV")
        if b["end"] < now_ms:
            bars.append(b)
    if len(bars) < 225:
        raise PaperError("Insufficient completed candles")
    from strategy_v2 import _validate
    _validate(bars, interval)
    max_age = 25 * 60_000 if interval == "15m" else 80 * 60_000
    if now_ms - bars[-1]["end"] > max_age:
        raise PaperError("Stale market feed")
    return bars


def _exit_position(state, symbol, bar, kind, raw_fill):
    p = state["positions"][symbol]
    exit_fill = raw_fill * (1 - SLIP if p["side"] == "LONG" else 1 + SLIP)
    gross = (exit_fill - p["entry"]) * p["qty"] * (1 if p["side"] == "LONG" else -1)
    exit_fee = exit_fill * p["qty"] * FEE
    state["balance"] += gross - exit_fee
    state["trades"].append({
        "symbol": symbol, "side": p["side"], "pnl": round(gross - exit_fee - p["entry_fee"], 5),
        "reason": kind, "closed_ms": bar["end"],
    })
    del state["positions"][symbol]


def mark_positions(state, histories):
    """Process every newly closed 15m candle, stop first if both levels touch."""
    for symbol, p in list(state["positions"].items()):
        bars = histories.get(symbol, {}).get("15m")
        if bars is None:
            raise PaperError("Held position market feed missing; halt simulation")
        last = p["last_bar"]
        if last < bars[0]["start"]:
            raise PaperError("Held market history gap; refuse to invent fills")
        upcoming = [b for b in bars if b["start"] > last]
        for b in upcoming:
            if p["side"] == "LONG":
                stop = b["l"] <= p["stop"]
                target = b["h"] >= p["target"]
                stop_fill = min(p["stop"], b["o"])  # approximate adverse gap
                target_fill = p["target"]
            else:
                stop = b["h"] >= p["stop"]
                target = b["l"] <= p["target"]
                stop_fill = max(p["stop"], b["o"])
                target_fill = p["target"]
            p["bars_held"] += 1
            p["last_bar"] = b["start"]
            if stop:
                _exit_position(state, symbol, b, "STOP", stop_fill)
                break
            if target:
                _exit_position(state, symbol, b, "TARGET", target_fill)
                break
            if p["bars_held"] >= 32:
                _exit_position(state, symbol, b, "TIME", b["c"])
                break


def _daily_rollover(state, now_ms):
    date = datetime.fromtimestamp(now_ms / 1000, timezone.utc).date().isoformat()
    if state["day"] != date:
        state["day"] = date
        state["day_start"] = float(state["balance"])
        state["entries_today"] = 0


def run_cycle(state, now_ms=None, fetch=public_get, limit=MAX_MARKETS):
    """One deterministic scan. Mutates local PAPER state; no private calls."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    markets = choose_markets(fetch, limit)
    for held in state["positions"]:
        if held not in markets:
            markets.append(held)  # continue monitoring a held position
    histories = {}
    errors = 0
    for symbol in markets:
        try:
            b15 = closed_candles(symbol, "15m", now_ms, fetch)
            b1h = closed_candles(symbol, "1h", now_ms, fetch)
            histories[symbol] = {"15m": b15, "1h": b1h}
        except (ValueError, KeyError, TypeError, OSError, PaperError) as exc:
            logging.warning("Unusable public market feed for %s: %s", symbol, type(exc).__name__)
            errors += 1
    if not histories:
        raise PaperError("All Binance price feeds unavailable; simulation halted")
    # Check held position feeds BEFORE any changes.
    if any(held not in histories for held in state["positions"]):
        raise PaperError("Cannot safely monitor a held paper position")
    mark_positions(state, histories)
    _daily_rollover(state, now_ms)
    candidates = []
    for symbol, data in histories.items():
        b15 = data["15m"]
        candle = b15[-1]
        if state["last_scanned"].get(symbol, -1) >= candle["start"]:
            continue
        if now_ms - candle["end"] > 20 * 60_000:
            continue  # too late to enter this closed candle
        higher = [b for b in data["1h"] if b["end"] <= candle["end"]]
        if len(higher) < 225:
            continue
        try:
            setup = analyze(b15, higher)
        except ValueError:
            continue
        state["last_scanned"][symbol] = candle["start"]
        if setup.side and setup.score == setup.score_max and setup.stop_distance:
            # All 6 conditions must pass. A higher ADX or volume is NOT win probability.
            from strategy_v2 import adx
            strength = adx(b15) or 0.0
            vol_base = sum(x["volume"] for x in b15[-21:-1]) / 20
            vol_ratio = candle["volume"] / vol_base if vol_base > 0 else 0.0
            candidates.append((strength, vol_ratio, symbol, setup, candle))
    state["scans"] += 1
    if (state["positions"] or state["entries_today"] >= MAX_DAILY_ENTRIES
            or state["balance"] <= state["day_start"] * (1 - MAX_DAILY_DRAWDOWN)):
        return {"markets_checked": len(histories), "candidates": len(candidates), "entry": None, "errors": errors}
    candidates.sort(key=lambda x: (-x[0], -x[1], x[2]))
    chosen = None
    for _, _, symbol, setup, candle in candidates:
        entry = candle["c"] * (1 + SLIP if setup.side == "LONG" else 1 - SLIP)
        distance = float(setup.stop_distance)
        if not (0 < distance <= entry * 0.035) or not math.isfinite(entry):
            continue
        # 3x isolated *simulated* leverage: 10% margin = <=30% notional of equity.
        notional = min(state["balance"] * MAX_MARGIN_FRACTION * LEVERAGE,
                       state["balance"] * RISK_PER_ENTRY * entry / distance)
        qty = notional / entry
        if notional < 10 or qty <= 0:
            continue
        stop = entry - distance if setup.side == "LONG" else entry + distance
        target = entry + setup.rr * distance if setup.side == "LONG" else entry - setup.rr * distance
        if min(stop, target) <= 0:
            continue
        fee = notional * FEE
        state["balance"] -= fee
        state["positions"][symbol] = {
            "side": setup.side, "entry": entry, "qty": qty, "stop": stop,
            "target": target, "margin": notional / LEVERAGE,
            "entry_fee": fee, "last_bar": candle["start"], "bars_held": 0,
            "leverage": LEVERAGE,
        }
        state["entries_today"] += 1
        chosen = {"symbol": symbol, "side": setup.side,
                  "confirmations": setup.score, "simulated_leverage": LEVERAGE}
        break
    return {"markets_checked": len(histories), "candidates": len(candidates),
            "entry": chosen, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(description="ATLAS autonomous scan, PAPER ONLY")
    ap.add_argument("--mode", choices=("once", "loop"), default="once")
    ap.add_argument("--state", default=str(STATE_PATH))
    ap.add_argument("--report", default=str(REPORT_PATH))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    path = Path(args.state)
    while True:
        try:
            state = load_state(path)
            result = run_cycle(state)
            save_json_atomic(path, state)
            report = {
                "mode": "PAPER ONLY; NO LIVE OR DEMO ORDERS",
                "simulated_leverage": LEVERAGE,
                "max_daily_entries": MAX_DAILY_ENTRIES,
                "entries_today": state["entries_today"],
                "balance_usdt": round(state["balance"], 2),
                "open_positions": len(state["positions"]),
                "closed_trades": len(state["trades"]),
                "last_scan": result,
                "disclaimer": "Hypothetical; funding/liquidation/exchange order constraints NOT modeled",
            }
            save_json_atomic(Path(args.report), report)
            print(json.dumps(report, ensure_ascii=False))
        except (PaperError, ValueError, OSError, KeyError, TypeError) as exc:
            logging.error("ATLAS paused: %s; NO ORDERS EXECUTED", exc)
            if args.mode == "once":
                return 2
        if args.mode == "once":
            return 0
        time.sleep(90)


if __name__ == "__main__":
    raise SystemExit(main())
