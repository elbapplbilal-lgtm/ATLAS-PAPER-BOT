import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import bot

class PaperTests(unittest.TestCase):
    def test_paper_price_url_only(self):
        self.assertEqual(bot.PUBLIC_URL,'https://fapi.binance.com/fapi/v1/klines')
    def test_twelve_pairs(self):
        self.assertEqual(len(bot.SYMBOLS),12)
    def test_ema(self):
        self.assertAlmostEqual(bot.ema([10,10,10,10,10],3),10)
    def test_rsi(self):
        self.assertGreater(bot.rsi(list(range(40))),99)
    def test_synthetic_has_chronological_bars(self):
        bars=bot.synthetic(count=100)
        self.assertEqual(len(bars),100)
        self.assertTrue(all(a['start']<b['start'] for a,b in zip(bars,bars[1:])))
    def test_history_no_signal_for_short_sample(self):
        self.assertEqual(bot.signal(bot.synthetic(count=20))[0],None)
    def test_no_double_counting(self):
        bars=bot.synthetic(count=100)
        s=bot.fresh_state()
        self.assertTrue(bot.step(s,'BTCUSDT',bars))
        self.assertFalse(bot.step(s,'BTCUSDT',bars))
        self.assertEqual(s['checked'],1)
    def test_position_budget_restricted(self):
        bars=bot.synthetic(count=100)
        s=bot.fresh_state()
        with patch.object(bot,'signal',return_value=('LONG',100)):
            bot.step(s,'BTCUSDT',bars)
        p=s['positions'].get('BTCUSDT')
        self.assertIsNotNone(p)
        self.assertLessEqual(p['qty']*p['entry'],s['balance']*.66)
    def test_daily_stop_prevents_entry(self):
        bars=bot.synthetic(count=100)
        s=bot.fresh_state()
        today=bot.datetime.fromtimestamp(bars[-1]['end']/1000,bot.timezone.utc).date().isoformat()
        s['day']=today;s['day_start']=5000;s['balance']=4850
        with patch.object(bot,'signal',return_value=('LONG',100)):
            bot.step(s,'BTCUSDT',bars)
        self.assertEqual(len(s['positions']),0)
    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state.json'
            s=bot.fresh_state()
            s['balance']=4900
            bot.save_state(path,s)
            self.assertEqual(bot.load_state(path)['balance'],4900)
    def test_corrupted_state_halts(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state.json'
            path.write_text('{}')
            with self.assertRaises(ValueError):bot.load_state(path)
    def test_offline_mode_no_api(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(bot,'fetch_klines',side_effect=AssertionError('Network should not be called')):
                result=bot.main(['--mode','offline-test','--symbols','BTCUSDT','--report',str(Path(temp)/'summary.json')])
            self.assertEqual(result,0)
            summary=json.loads((Path(temp)/'summary.json').read_text())
            self.assertIn('SYNTHETIC',summary['mode'])
    def test_public_feed_rejects_unlisted_pair(self):
        with self.assertRaises(ValueError):bot.fetch_klines('NOT_A_PAIR')
