import json, os, unittest
from unittest.mock import patch
import demo_trader as d

class DemoTests(unittest.TestCase):
    def test_api_host_is_demo_only(self):
        self.assertEqual(d.DEMO_HOST,'https://demo-fapi.binance.com')
    def test_keys_required(self):
        with patch.dict(os.environ,{'BINANCE_DEMO_KEY':'','BINANCE_DEMO_SECRET':''}):
            with self.assertRaises(d.DemoError):d.DemoClient()
    def test_order_is_disabled_by_default(self):
        candles=[dict(start=i*900000,end=i*900000+899999,o=100,h=101,l=99,c=100,volume=1000) for i in range(80)]
        with patch.object(d,'api_candles',return_value=candles),patch.object(d,'signal',return_value=('LONG',1)),patch.dict(os.environ,{'ENABLE_BINANCE_DEMO_ORDERS':'NO'}):
            self.assertIn('DISABLED',d.run_once(enable_orders=True))
    def test_signed_request_targets_demo_only(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return b'{}'
        def fake_urlopen(req,timeout=12):
            self.assertTrue(req.full_url.startswith(d.DEMO_HOST+'/fapi/'))
            signed=req.full_url if req.method=='GET' else req.data.decode()
            self.assertIn('signature=',signed)
            self.assertTrue(any(k.lower()=='x-mbx-apikey' for k,_ in req.header_items()))
            return Response()
        with patch.object(d.urllib.request,'urlopen',side_effect=fake_urlopen):
            c=d.DemoClient('demo','secret')
            self.assertEqual(c.call('GET','/fapi/v2/account'),{})
            self.assertEqual(c.call('POST','/fapi/v1/order/test',{'symbol':'BTCUSDT'}),{})
    def test_unknown_post_not_retried(self):
        counter=[]
        def fails(*a,**k):
            counter.append(1);raise TimeoutError()
        with patch.object(d.urllib.request,'urlopen',side_effect=fails):
            with self.assertRaises(d.DemoError):
                d.DemoClient('demo','secret').call('POST','/fapi/v1/order')
        self.assertEqual(len(counter),1)
    def test_rejects_live_api_path(self):
        c=d.DemoClient('demo','secret')
        with self.assertRaises(d.DemoError):c.call('GET','/api/v3/account')
        with self.assertRaises(d.DemoError):c.call('DELETE','/fapi/v1/order')
    def test_precise_step_rounding(self):
        from decimal import Decimal
        self.assertEqual(d.quant_down(Decimal('0.12356'),Decimal('0.001')),Decimal('0.123'))
