#!/usr/bin/env python3
"""Read-only authentication health check for Binance Futures Demo.
Never submits, modifies, or cancels an order. Do not log credentials.
"""
import sys
from demo_trader import DemoClient, DemoError, DEMO_HOST

def main():
    if DEMO_HOST != "https://demo-fapi.binance.com":
        print("FAIL: Unexpected exchange host; refused to connect.")
        return 2
    try:
        client = DemoClient()
        # Only a single signed GET; no state-changing API calls.
        account = client.call("GET", "/fapi/v2/account")
        if not isinstance(account, dict) or not ("assets" in account or "totalWalletBalance" in account):
            print("FAIL: Unexpected authenticated account response (not printing private data).")
            return 2
        print("SUCCESS: Binance USD-M Futures DEMO API signed read-only request succeeded.")
        print("No orders were opened, modified, or cancelled.")
        return 0
    except (DemoError, Exception) as exc:
        # Do not print exception details, because transports may include signed URLs.
        print("FAIL: Binance DEMO signed read-only request could not be verified.")
        print("Check that BOTH GitHub secrets match the current DEMO key pair, and demo API permissions.")
        print("Error category:", type(exc).__name__)
        print("No orders were sent.")
        return 2

if __name__ == "__main__":
    sys.exit(main())
