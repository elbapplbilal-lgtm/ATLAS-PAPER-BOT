"""Offline safety tests for Binance real-account read-only adapter.

Tests NEVER contact Binance and NEVER use actual credentials.
"""
import io
import json
import os
import re
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import live_readonly as lr


class MockResponse:
    status = 200
    def __init__(self, body):
        self.data = io.BytesIO(json.dumps(body).encode("utf-8"))
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.data.close()
    def read(self, size=-1):
        return self.data.read(size)


class MockOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []
        self.methods = []
        self.headers = []
    def __call__(self, req, timeout):
        self.urls.append(req.full_url)
        self.methods.append(req.get_method())
        self.headers.append(dict(req.header_items()))
        return MockResponse(self.responses.pop(0))


class ReadOnlyTests(unittest.TestCase):
    def test_explicit_live_host_and_strict_whitelist(self):
        self.assertEqual(lr.LIVE_HOST, "https://fapi.binance.com")
        self.assertEqual(lr.READONLY_PATHS, {
            "/fapi/v1/time", "/fapi/v3/account", "/fapi/v3/positionRisk"
        })
        for p in ("/fapi/v1/order", "/fapi/v1/algoOrder",
                  "/fapi/v1/leverage", "/api/v3/order", "https://evil.org"):
            with self.assertRaises(lr.LiveReadOnlyError):
                lr._get_json(p, opener=lambda *a, **k: self.fail("no network"))

    def test_only_get_and_correct_hmac(self):
        mock = MockOpener({"serverTime": 1792000000000}, {"assets": [], "multiAssetsMargin": False})
        cli = lr.LiveReadOnlyClient("readonly_TEST", "secret_TEST", opener=mock)
        self.assertEqual(cli.account_check(), {"authenticated": True, "mode": "single-assets"})
        self.assertEqual(mock.methods, ["GET", "GET"])
        self.assertEqual(mock.urls[0], lr.LIVE_HOST + "/fapi/v1/time")
        self.assertTrue(mock.urls[1].startswith(lr.LIVE_HOST + "/fapi/v3/account?"))
        self.assertNotIn("secret_TEST", mock.urls[1])
        self.assertIn("signature=", mock.urls[1])
        self.assertEqual(mock.headers[-1].get("X-mbx-apikey"), "readonly_TEST")
        import hashlib, hmac, urllib.parse
        q=urllib.parse.urlsplit(mock.urls[1]).query
        data,sig=q.rsplit("&signature=",1)
        self.assertEqual(sig,hmac.new(b"secret_TEST",data.encode(),hashlib.sha256).hexdigest())

    def test_no_redirects_ever(self):
        reject = lr._RejectRedirect()
        self.assertIsNone(reject.redirect_request(
            None, None, 302, "Move", {}, "https://other.example/"))

    def test_no_post_support(self):
        self.assertFalse(hasattr(lr.LiveReadOnlyClient,"place_order"))
        self.assertFalse(hasattr(lr.LiveReadOnlyClient,"post"))
        mock = MockOpener({"serverTime":1792000000000})
        client = lr.LiveReadOnlyClient("x","y",opener=mock)
        with self.assertRaises(lr.LiveReadOnlyError):
            client.signed_get("/fapi/v1/order")
        self.assertEqual(mock.urls, [])

    def test_no_credentials_no_network(self):
        with patch.dict(os.environ, {lr.KEY_ENV:"", lr.SECRET_ENV:""}):
            with self.assertRaises(lr.LiveReadOnlyError):
                lr.LiveReadOnlyClient()

    def test_sanitize_failed_http_url_and_message(self):
        secret_token="should-not-leak"
        url="https://fapi.binance.com/fapi/v3/account?secret="+secret_token
        def fake(req, timeout):
            raise urllib.error.HTTPError(url,451,"private-details",None,None)
        with self.assertRaises(lr.LiveReadOnlyError) as cm:
            lr._get_json("/fapi/v1/time",opener=fake)
        err=str(cm.exception)
        self.assertEqual(err,"Binance read-only HTTP status: 451")
        self.assertNotIn(secret_token,err)
        self.assertNotIn("private-details",err)

    def test_local_summary_counts_only(self):
        mock=MockOpener(
            {"serverTime":1792000000000},
            {"assets":[{"walletBalance":"500"},{"walletBalance":"0"}]},
            {"serverTime":1792000001000},
            [{"positionAmt":"0"},{"positionAmt":"0.01"}],
        )
        result=lr.LiveReadOnlyClient("test","test",opener=mock).local_summary()
        self.assertEqual(result,{"connected":True,"nonzero_asset_count":1,"open_position_count":1})
        self.assertEqual(mock.methods,["GET"]*4)


if __name__=="__main__":
    unittest.main()
