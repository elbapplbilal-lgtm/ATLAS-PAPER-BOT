import unittest
from unittest.mock import patch
import strategy_v2 as st

def sample(step=900000, length=240, price=100):
    out=[]
    origin=1_000_000_000_000
    for i in range(length):
        ts=origin+i*step
        out.append({'start':ts,'end':ts+step-1,'o':price,'h':price+1,
                    'l':price-1,'c':price,'volume':1000})
    return out

class MultiTimeframeStrategyTests(unittest.TestCase):
    def test_no_future_higher_timeframe_candles(self):
        low=sample();high=sample(step=3600000)
        with self.assertRaisesRegex(ValueError, 'after decision'):
            st.analyze(low,high)
    def test_requires_225_closed_candles_both_frames(self):
        with self.assertRaises(ValueError):
            st.analyze(sample(length=224),sample(step=3600000))
        with self.assertRaises(ValueError):
            st.analyze(sample(),sample(step=3600000,length=224))
    def test_no_signal_in_flat_market(self):
        low=sample()
        high=sample(step=3600000)
        # Shift higher timeframe to a previous period: no time travel.
        for b in high:
            b['start']-=1_000_000_000
            b['end']-=1_000_000_000
        result=st.analyze(low,high)
        self.assertIsNone(result.side)
    def test_bad_volume_blocks(self):
        low=sample();high=sample(step=3600000)
        for b in high:b['start']-=1_000_000_000;b['end']-=1_000_000_000
        low[-1].update({'o':100,'h':104,'l':99,'c':103,'volume':500})
        low[-2].update({'h':101,'l':99})
        seq=[100,99,98,103,98,101,100]
        with patch.object(st,'ema',side_effect=seq),patch.object(st,'rsi',return_value=61),patch.object(st,'atr',return_value=2),patch.object(st,'adx',return_value=27):
            result=st.analyze(low,high)
        # Without a volume confirmation, score is capped at five.
        self.assertLess(result.score,6)
    def test_strong_long_requires_six_independent_confirmations(self):
        low=sample();high=sample(step=3600000)
        for b in high:b['start']-=1_000_000_000;b['end']-=1_000_000_000
        low[-1].update({'o':100,'h':104,'l':99,'c':103,'volume':2000})
        seq=[100,99,98,103,98,101,100]
        with patch.object(st,'ema',side_effect=seq),patch.object(st,'rsi',return_value=61),patch.object(st,'atr',return_value=2),patch.object(st,'adx',return_value=27):
            result=st.analyze(low,high)
        self.assertEqual(result.side,'LONG')
        self.assertEqual(result.score,6)
        self.assertGreater(result.stop_distance,0)
    def test_adx_for_constant_bars_is_zero(self):
        self.assertAlmostEqual(st.adx(sample()),0)

if __name__=='__main__':
    unittest.main()
