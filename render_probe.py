#!/usr/bin/env python3
"""ATLAS public Binance connectivity probe, both LIVE and DEMO endpoints.
PUBLIC GET /fapi/v1/time ONLY. No account access, credentials, or order methods.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
import os, json

PUBLIC_ENDPOINTS = {
    "/probe": ("demo", "https://demo-fapi.binance.com/fapi/v1/time"),
    "/probe-live": ("live", "https://fapi.binance.com/fapi/v1/time"),
}

def public_probe(label, url, fetch=urlopen):
    try:
        req = Request(url, method="GET", headers={"User-Agent": "ATLAS-public-connectivity-check"})
        with fetch(req, timeout=9) as res:
            raw = json.load(res)
            return {
                "service": "ATLAS public connectivity probe", "endpoint": label,
                "reachable": res.status == 200 and isinstance(raw,dict) and isinstance(raw.get("serverTime"),int),
                "http_status": res.status, "orders_enabled": False, "credentials_used": False,
            }
    except HTTPError as e:
        return {"service":"ATLAS public connectivity probe","endpoint":label,
                "reachable":False,"http_status":int(e.code),"orders_enabled":False,"credentials_used":False}
    except (URLError, OSError, ValueError, TimeoutError) as e:
        return {"service":"ATLAS public connectivity probe","endpoint":label,
                "reachable":False,"error_type":type(e).__name__,"orders_enabled":False,"credentials_used":False}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        pathname = urlsplit(self.path).path
        if pathname == "/health":
            out={"service":"ATLAS public connectivity probe","status":"up",
                 "orders_enabled":False,"credentials_used":False}
        elif pathname == "/":
            out={"service":"ATLAS public connectivity probe",
                 "routes":["/probe","/probe-live","/health"],
                 "orders_enabled":False,"credentials_used":False}
        elif pathname in PUBLIC_ENDPOINTS:
            label,url = PUBLIC_ENDPOINTS[pathname]
            out=public_probe(label,url)
        else:
            self.send_response(404)
            self.end_headers()
            return
        body=json.dumps(out,ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self,*args):
        pass

if __name__=="__main__":
    port=int(os.environ.get("PORT","10000"))
    print("ATLAS public read-only hosting probes starting",flush=True)
    for label,url in PUBLIC_ENDPOINTS.values():
        result=public_probe(label,url)
        print("STARTUP PUBLIC REACHABILITY:",label,"HTTP",result.get("http_status","error"),"reachable",result["reachable"],flush=True)
    ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()
