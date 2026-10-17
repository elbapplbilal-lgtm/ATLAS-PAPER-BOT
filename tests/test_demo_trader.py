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
        from strategy_v2 import Setup
        candles=[dict(start=i*900000,end=i*900000+899999,o=100,h=101,l=99,c=100,volume=1000) for i in range(230)]
        setup=Setup('LONG',1,6,6,1.8,1.8,'test setup')
        with patch.object(d,'api_candles',return_value=candles),patch.object(d,'analyze',return_value=setup),patch.dict(os.environ,{'ENABLE_BINANCE_DEMO_ORDERS':'NO'}):
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
    def test_no_signal_never_checks_credentials_or_orders(self):
        from strategy_v2 import Setup
        candles=[dict(start=i*900000,end=i*900000+899999,o=100,h=101,l=99,c=100,volume=1000) for i in range(230)]
        setup=Setup(None,1,4,6,None,1.8,'Weak setup')
        with patch.object(d,'api_candles',return_value=candles),patch.object(d,'analyze',return_value=setup),patch.object(d,'DemoClient',side_effect=AssertionError('Should not authenticate')):
            self.assertIn('No confirmed',d.run_once(enable_orders=True))

    def test_max_five_attempted_entries_daily(self):
        from strategy_v2 import Setup
        from unittest.mock import patch
        candles=[dict(start=i*900000,end=i*900000+899999,o=100,h=101,l=99,c=100,volume=1000) for i in range(230)]
        setup=Setup('LONG',1,6,6,1.8,1.8,'Strong setup')
        state={'day': '1970-01-03', 'initial_wallet': '5000', 'entries_today': 5, 'last_attempted_bar': None}
        class Client:
            def __init__(self):self.calls=[]
            def call(self,*args):
                self.calls.append(args)
                raise AssertionError('No exchange orders or authenticated calls expected')
        client=Client()
        with patch.object(d,'api_candles',return_value=candles),patch.object(d,'analyze',return_value=setup),patch.object(d,'read_state',return_value=state),patch.object(d,'account_checks',return_value=(d.Decimal('5000'),d.Decimal('5000'))),patch.dict(os.environ,{'ENABLE_BINANCE_DEMO_ORDERS':'YES'}):
            with self.assertRaisesRegex(d.DemoError,'entry limit'):d.run_once(client=client,enable_orders=True)
        self.assertEqual(client.calls,[])

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
