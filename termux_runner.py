#!/usr/bin/env python3
"""ATLAS — manual-start DEMO trading from Android Termux.

BINANCE FUTURES DEMO ONLY. Keeps credentials in process memory, not files.
It never uses GitHub secrets or any live Binance host.
Do not assume uninterrupted operation when Android sleeps or loses network.
"""
from __future__ import annotations
import fcntl
import getpass
import os
import sys
import time
from pathlib import Path
import demo_trader
import check_demo_connection

def ask(prompt: str) -> str:
    value = getpass.getpass(prompt).strip()
    if not value:
        raise ValueError("Empty input; stopped.")
    return value

def main() -> int:
    if demo_trader.DEMO_HOST != "https://demo-fapi.binance.com":
        print("STOP: Unexpected Binance API hostname.")
        return 2
    print("=" * 54)
    print("ATLAS — BINANCE FUTURES DEMO ONLY / NO REAL MONEY")
    print("BTC/USDT | 15m | 1x isolated | max 5 demo entries/day")
    print("The bot only runs while this Termux process remains alive.")
    print("=" * 54)
    print("Paste DEMO keys. Input will not be shown or saved to disk.")
    try:
        os.environ["BINANCE_DEMO_KEY"] = ask("DEMO API Key (hidden): ")
        os.environ["BINANCE_DEMO_SECRET"] = ask("DEMO Secret Key (hidden): ")
    except (EOFError, KeyboardInterrupt, ValueError) as exc:
        print("\nStopped before connecting.", type(exc).__name__)
        return 2

    print("\nChecking DEMO account with READ-ONLY request...")
    if check_demo_connection.main() != 0:
        print("Connection not verified; ALL order execution remains disabled.")
        return 2

    print("\nThe connection worked. No trades have been placed.")
    print("Before enabling demo orders, ensure you have no other active")
    print("demo positions/orders. No trade profit is guaranteed.")
    answer = input("Start AUTOMATIC DEMO ORDER execution? Type YES: ").strip()
    if answer != "YES":
        print("Execution not enabled. Goodbye.")
        return 0

    os.environ["ENABLE_BINANCE_DEMO_ORDERS"] = "YES"
    try:
        client = demo_trader.DemoClient()
        state_lock = Path("data/termux_runner.lock")
        state_lock.parent.mkdir(parents=True, exist_ok=True)
        with state_lock.open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("A second ATLAS instance is already running; refusing.")
                return 2
            print("DEMO trading enabled. Ctrl+C stops the process.")
            while True:
                try:
                    result = demo_trader.run_once(client=client, enable_orders=True)
                    print(time.strftime("%Y-%m-%d %H:%M:%S"), str(result), flush=True)
                except demo_trader.DemoError as exc:
                    print("STOP: DEMO API / order error. Manual account review required.")
                    print("Issue:", str(exc))
                    print("No further orders will be attempted.")
                    return 2
                # No new signal until new closed candles; avoid excessive requests.
                time.sleep(120)
    except KeyboardInterrupt:
        print("\nATLAS stopped. Check DEMO positions and stop orders in Binance.")
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
