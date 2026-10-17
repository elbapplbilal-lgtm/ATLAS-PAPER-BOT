#!/usr/bin/env python3
"""ATLAS: Binance LIVE USD-M Futures account information, READ ONLY.

NO trade methods. NO order placement or cancellation. API calls are strictly
whitelisted signed GETs, and no redirects are followed. This module is not
imported by the demo trading workflows. Never use trade-enabled LIVE keys.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

LIVE_HOST = "https://fapi.binance.com"
READONLY_PATHS = frozenset({
    "/fapi/v1/time",
    "/fapi/v3/account",
    "/fapi/v3/positionRisk",
})
KEY_ENV = "ATLAS_LIVE_RO_KEY"
SECRET_ENV = "ATLAS_LIVE_RO_SECRET"


class LiveReadOnlyError(RuntimeError):
    """Only sanitized errors: never expose signed URLs, keys or response bodies."""


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get_json(path: str, headers: dict[str, str] | None = None,
              params: str = "", opener=None):
    if path not in READONLY_PATHS:
        raise LiveReadOnlyError("Path blocked by read-only API whitelist")
    if headers is None:
        headers = {}
    url = LIVE_HOST + path + ("?" + params if params else "")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATLAS-LIVE-READONLY/1.0", **headers},
        method="GET",
    )
    open_fn = opener or urllib.request.build_opener(_RejectRedirect()).open
    try:
        with open_fn(request, timeout=12) as resp:
            if resp.status != 200:
                raise LiveReadOnlyError("Non-success status from exchange")
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        # Do not include exc, exc.url, or exchange response body in logs.
        raise LiveReadOnlyError(f"Binance read-only HTTP status: {exc.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        raise LiveReadOnlyError("Read-only exchange request could not be completed") from None
    if not isinstance(data, dict) and path != "/fapi/v3/positionRisk":
        raise LiveReadOnlyError("Invalid JSON payload shape")
    return data


class LiveReadOnlyClient:
    def __init__(self, key: str | None = None, secret: str | None = None, opener=None):
        self._key = (key if key is not None else os.environ.get(KEY_ENV, "")).strip()
        self._secret = (secret if secret is not None else os.environ.get(SECRET_ENV, "")).strip()
        if not self._key or not self._secret:
            raise LiveReadOnlyError("Missing read-only environment credentials")
        self._opener = opener

    def signed_get(self, path: str):
        if path not in ("/fapi/v3/account", "/fapi/v3/positionRisk"):
            raise LiveReadOnlyError("Only whitelisted signed account GETs are permitted")
        clock = _get_json("/fapi/v1/time", opener=self._opener)
        ms = clock.get("serverTime")
        if isinstance(ms, bool) or not isinstance(ms, int) or ms <= 0:
            raise LiveReadOnlyError("Invalid exchange server timestamp")
        params = urllib.parse.urlencode({"timestamp": ms, "recvWindow": 5000})
        signature = hmac.new(self._secret.encode("utf-8"), params.encode("utf-8"),
                             hashlib.sha256).hexdigest()
        return _get_json(
            path,
            headers={"X-MBX-APIKEY": self._key},
            params=params + "&signature=" + signature,
            opener=self._opener,
        )

    def account_check(self):
        account = self.signed_get("/fapi/v3/account")
        if not isinstance(account, dict) or not isinstance(account.get("assets"), list):
            raise LiveReadOnlyError("Account endpoint returned unexpected fields")
        return {"authenticated": True, "mode": (
            "multi-assets" if account.get("multiAssetsMargin") is True else "single-assets"
        )}

    def local_summary(self):
        """Optional LOCAL display; NEVER use in GitHub Actions public job logs."""
        account = self.signed_get("/fapi/v3/account")
        if not isinstance(account, dict) or not isinstance(account.get("assets"), list):
            raise LiveReadOnlyError("Account endpoint returned unexpected fields")
        positions = self.signed_get("/fapi/v3/positionRisk")
        if not isinstance(positions, list):
            raise LiveReadOnlyError("Invalid position response")
        try:
            open_count = sum(1 for p in positions
                             if Decimal(str(p.get("positionAmt", "0"))) != 0)
        except (ValueError, InvalidOperation, TypeError):
            raise LiveReadOnlyError("Invalid position amount") from None
        return {"connected": True, "nonzero_asset_count": sum(
            1 for a in account["assets"]
            if Decimal(str(a.get("walletBalance", "0"))) != 0
        ), "open_position_count": open_count}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Binance LIVE account, READ ONLY")
    parser.add_argument("--mode", choices=["check", "local-summary"], default="check")
    args = parser.parse_args(argv)
    try:
        client = LiveReadOnlyClient()
        result = client.account_check() if args.mode == "check" else client.local_summary()
        print(json.dumps(result, ensure_ascii=False))
        print("READ ONLY. No order or cancellation endpoints were called.")
        return 0
    except LiveReadOnlyError as exc:
        print("Read-only check stopped:", str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
