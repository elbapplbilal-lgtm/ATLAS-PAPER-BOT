#!/usr/bin/env python3
"""ATLAS hosting probe: READ-ONLY public Binance Futures DEMO API.
No API keys, no trading, no logged secrets. Only use for reachability testing.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import os, json, time

HOST="https://demo-fapi.binance.com/fapi/v1/time"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/","/probe","/health"):
            self.send_response(404);self.end_headers();return
        if self.path == "/health":
            out={"service":"ATLAS connectivity probe","status":"up","orders_enabled":False}
        else:
            try:
                req=Request(HOST,headers={"User-Agent":"ATLAS-demo-connectivity-check"})
                with urlopen(req,timeout=9) as res:
                    raw=json.load(res)
                    out={"service":"ATLAS connectivity probe","reachable":isinstance(raw,dict) and isinstance(raw.get("serverTime"),int),"http_status":res.status,"orders_enabled":False}
            except HTTPError as e:
                out={"service":"ATLAS connectivity probe","reachable":False,"http_status":int(e.code),"orders_enabled":False}
            except (URLError, OSError, ValueError, TimeoutError) as e:
                out={"service":"ATLAS connectivity probe","reachable":False,"error_type":type(e).__name__,"orders_enabled":False}
        body=json.dumps(out,ensure_ascii=False).encode()
        self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)))
        self.end_headers();self.wfile.write(body)
    def log_message(self,*args): pass

if __name__ == "__main__":
    port=int(os.environ.get("PORT","10000"))
    print("ATLAS demo read-only hosting probe starting",flush=True)
    ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()
