#!/usr/bin/env python3
"""Read-only Binance Futures DEMO connectivity diagnostics.

Public GET /fapi/v1/time and signed GET /fapi/v2/account ONLY.
Never prints key/secret, signed query, account balances, URL, or API error text.
"""
import hashlib
import hmac
import json
import os
import sys
import time
from urllib import parse, request, error

BASE = "https://demo-fapi.binance.com"

def get_json(path, headers=None):
    req = request.Request(BASE + path, headers=headers or {}, method="GET")
    try:
        with request.urlopen(req, timeout=15) as response:
            return json.load(response), None, None
    except error.HTTPError as exc:
        # Only disclose coarse diagnostics, not signed URL or private account data.
        try:
            payload = json.loads(exc.read(2048).decode("utf-8"))
            code = payload.get("code") if isinstance(payload, dict) else None
            code = code if isinstance(code, int) and -999999 < code < 999999 else None
        except (ValueError, UnicodeError, OSError):
            code = None
        return None, exc.code, code
    except (OSError, TimeoutError, ValueError):
        return None, "NETWORK", None

def main():
    if BASE != "https://demo-fapi.binance.com":
        print("FAIL: Wrong exchange host.")
        return 2
    key = os.environ.get("BINANCE_DEMO_KEY", "").strip()
    secret = os.environ.get("BINANCE_DEMO_SECRET", "").strip()
    if not key or not secret:
        print("FAIL: GitHub demo secrets missing or empty.")
        return 2
    clock, http, api_error = get_json("/fapi/v1/time")
    if http is not None:
        print(f"FAIL: DEMO public server time HTTP={http}, Binance code={api_error}.")
        return 2
    if not isinstance(clock, dict) or not isinstance(clock.get("serverTime"), int):
        print("FAIL: Invalid response from DEMO time server.")
        return 2
    print("OK: DEMO public server reachable.")
    payload = parse.urlencode({
        "timestamp": clock["serverTime"],
        "recvWindow": 5000,
    })
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    result, http, api_error = get_json(
        "/fapi/v2/account?" + payload + "&signature=" + sig,
        headers={"X-MBX-APIKEY": key, "User-Agent": "ATLAS-READONLY-DEMO"},
    )
    if http is not None:
        print(f"FAIL: DEMO authenticated request HTTP={http}, Binance code={api_error}.")
        print("No orders placed.")
        return 2
    if not isinstance(result, dict) or not ("assets" in result or "totalWalletBalance" in result):
        print("FAIL: Unrecognized authenticated DEMO response.")
        return 2
    print("SUCCESS: Binance Futures DEMO authenticated READ-ONLY connection works.")
    print("No orders placed; demo order execution stays disabled.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
