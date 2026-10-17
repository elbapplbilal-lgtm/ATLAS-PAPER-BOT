#!/usr/bin/env python3
"""ATLAS V2 closed-candle, multi-timeframe setup analysis (DEMO use only).

Score means number of confirmations, NOT probability of winning.
Never calls the network or submits orders.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Optional
from bot import ema, rsi, atr

MIN_BARS = 225

@dataclass(frozen=True)
class Setup:
    side: Optional[str]
    atr: Optional[float]
    score: int
    score_max: int
    stop_distance: Optional[float]
    rr: float
    reason: str

def _validate(bars, name):
    if len(bars) < MIN_BARS:
        raise ValueError(f'{name}: requires at least {MIN_BARS} closed candles')
    before = -1
    for bar in bars:
        if not isinstance(bar, dict) or any(k not in bar for k in ('start','end','o','h','l','c','volume')):
            raise ValueError(f'{name}: invalid candle fields')
        if not isinstance(bar['start'],int) or not isinstance(bar['end'],int) or bar['start']<=before or bar['end']<=bar['start']:
            raise ValueError(f'{name}: out-of-order candle')
        before=bar['start']
        v=[bar[k] for k in ('o','h','l','c','volume')]
        if any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in v) or min(v[:4])<=0 or v[4]<0:
            raise ValueError(f'{name}: invalid OHLCV')
        if bar['h']<max(bar['o'],bar['c']) or bar['l']>min(bar['o'],bar['c']) or bar['h']<bar['l']:
            raise ValueError(f'{name}: impossible OHLC')

def adx(bars, period=14):
    """Wilder-smoothed directional movement strength; closed bars only."""
    if len(bars)<3*period+1:return None
    tr,plus,minus=[],[],[]
    for p,b in zip(bars,bars[1:]):
        up=b['h']-p['h'];down=p['l']-b['l']
        plus.append(up if up>down and up>0 else 0.0)
        minus.append(down if down>up and down>0 else 0.0)
        tr.append(max(b['h']-b['l'],abs(b['h']-p['c']),abs(b['l']-p['c'])))
    def wilder(values):
        v=sum(values[:period]);out=[v]
        for x in values[period:]:
            v=v-v/period+x
            out.append(v)
        return out
    trs=wilder(tr);ps=wilder(plus);ms=wilder(minus)
    dx=[]
    for t,p,m in zip(trs,ps,ms):
        if t<=0:dx.append(0.0);continue
        pd=100*p/t;md=100*m/t
        dx.append(100*abs(pd-md)/(pd+md) if pd+md else 0.0)
    if len(dx)<period:return None
    value=sum(dx[:period])/period
    for x in dx[period:]:value=(value*(period-1)+x)/period
    return value

def analyze(bars15,bars1h):
    """Return a Setup with no side unless all mandatory conditions pass."""
    _validate(bars15,'15m');_validate(bars1h,'1h')
    current=bars15[-1];price=current['c']
    if bars1h[-1]['end'] > current['end']:
        raise ValueError('Higher timeframe includes candle after decision time')
    x=[b['c'] for b in bars15];h=[b['c'] for b in bars1h]
    a=atr(bars15,14)
    if a is None or not math.isfinite(a) or a<=0:
        return Setup(None,a,0,6,None,1.8,'ATR invalid')
    if not .0015 <= a/price <= .035:
        return Setup(None,a,0,6,None,1.8,'Volatility outside safe demo range')
    f=ema(x,20);s=ema(x,50);slow=ema(x,200)
    fast1=ema(h,50);slow1=ema(h,200);fast1_prev=ema(h[:-4],50)
    if any(q is None for q in (f,s,slow,fast1,slow1,fast1_prev)):
        return Setup(None,a,0,6,None,1.8,'Insufficient trend indicators')
    direction=None
    if fast1>slow1 and fast1>fast1_prev and f>s>slow and price>f:
        direction='LONG'
    if fast1<slow1 and fast1<fast1_prev and f<s<slow and price<f:
        direction='SHORT'
    if not direction:return Setup(None,a,0,6,None,1.8,'1h and 15m trend do not agree')
    momentum=rsi(x,14);strength=adx(bars15,14)
    vol_avg=sum(b['volume'] for b in bars15[-21:-1])/20
    vol_ratio=current['volume']/vol_avg if vol_avg>0 else 0
    bdy=abs(current['c']-current['o'])
    prev=bars15[-13:-1];prev_fast=ema(x[:-1],20)
    if current['h']-current['l'] > 2.6*a or bdy>2*a:
        return Setup(None,a,0,6,None,1.8,'Oversized candle; no chase')
    if direction=='LONG':
        rsi_ok=momentum is not None and 51<=momentum<=72
        breakout=price>max(b['h'] for b in prev) and bdy>.3*a
        bounce=(bars15[-2]['l']<=prev_fast and price>bars15[-2]['h'] and current['c']>current['o'] and bdy>.25*a)
        structure=price>current['o'] and (breakout or bounce)
    else:
        rsi_ok=momentum is not None and 28<=momentum<=49
        breakout=price<min(b['l'] for b in prev) and bdy>.3*a
        bounce=(bars15[-2]['h']>=prev_fast and price<bars15[-2]['l'] and current['c']<current['o'] and bdy>.25*a)
        structure=price<current['o'] and (breakout or bounce)
    adx_ok=strength is not None and strength>=19
    vol_ok=vol_ratio>=1.15
    # Score counts two trend confirmations + RSI + ADX + volume + structure.
    score=2+int(rsi_ok)+int(adx_ok)+int(vol_ok)+int(structure)
    if not rsi_ok or not adx_ok or not structure or not vol_ok or score<6:
        return Setup(None,a,score,6,None,1.8,'RSI, ADX, candle trigger or volume filter not confirmed')
    distance=max(a*1.8,price*.004)
    if distance/price>.035:
        return Setup(None,a,score,6,None,1.8,'Stop distance too wide')
    return Setup(direction,a,score,6,distance,1.8,'Confirmed trend setup; no guaranteed result')
