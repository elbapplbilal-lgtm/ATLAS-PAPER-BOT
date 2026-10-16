#!/usr/bin/env python3
"""ATLAS paper-only bot. Uses public Binance prices; NEVER places orders."""
from __future__ import annotations
import argparse, csv, json, logging, math, os, random, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

PUBLIC_URL = 'https://fapi.binance.com/fapi/v1/klines'
SYMBOLS = ('BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','ADAUSDT',
           'DOGEUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','DOTUSDT','TRXUSDT')
START_BALANCE = 5000.0
RISK = .005
MAX_OPEN = 3
DAILY_STOP = .02
FEE = .0004
SLIPPAGE = .0003

def ema(xs,n):
    if len(xs)<n:return None
    k=2/(n+1); a=sum(xs[:n])/n
    for v in xs[n:]:a=k*v+(1-k)*a
    return a

def rsi(xs,n=14):
    if len(xs)<=n:return None
    changes=[b-a for a,b in zip(xs,xs[1:])]
    gains=[max(0,d) for d in changes];losses=[max(0,-d) for d in changes]
    a=sum(gains[:n])/n;b=sum(losses[:n])/n
    for g,l in zip(gains[n:],losses[n:]):
        a=(a*(n-1)+g)/n;b=(b*(n-1)+l)/n
    return 100-100/(1+a/b) if b>0 else (100 if a>0 else 50)

def atr(bars,n=14):
    if len(bars)<=n:return None
    trs=[max(b['h']-b['l'],abs(b['h']-a['c']),abs(b['l']-a['c']))
         for a,b in zip(bars,bars[1:])]
    a=sum(trs[:n])/n
    for t in trs[n:]:a=(a*(n-1)+t)/n
    return a

def signal(bars):
    if len(bars)<65:return None,None
    xs=[b['c'] for b in bars]
    f,s,t,v,z=ema(xs,9),ema(xs,21),ema(xs,50),rsi(xs),atr(bars)
    if any(x is None for x in (f,s,t,v,z)) or z<=0:return None,None
    if not .0015<=z/xs[-1]<=.035:return None,z
    if f>s>t and xs[-1]>f and 52<=v<=69:return 'LONG',z
    if f<s<t and xs[-1]<f and 31<=v<=48:return 'SHORT',z
    return None,z

def fetch_klines(symbol,limit=180):
    if symbol not in SYMBOLS:raise ValueError('Pair is not allowed')
    q=urllib.parse.urlencode({'symbol':symbol,'interval':'15m','limit':limit})
    req=urllib.request.Request(PUBLIC_URL+'?'+q,headers={'User-Agent':'ATLAS-PAPER/0.2'})
    with urllib.request.urlopen(req,timeout=12) as r:raw=json.load(r)
    if not isinstance(raw,list):raise ValueError('Exchange response is invalid')
    now=int(time.time()*1000);out=[]
    for v in raw:
        if not isinstance(v,list) or len(v)<7:raise ValueError('Bad candle')
        b=dict(start=int(v[0]),o=float(v[1]),h=float(v[2]),l=float(v[3]),
               c=float(v[4]),volume=float(v[5]),end=int(v[6]))
        if not all(math.isfinite(b[k]) for k in ('o','h','l','c','volume')) or min(b['o'],b['h'],b['l'],b['c'])<=0 or b['l']>min(b['o'],b['c']) or b['h']<max(b['o'],b['c']):
            raise ValueError('Invalid OHLC')
        if b['end']<now:out.append(b)  # Closed candles only.
    if len(out)<65 or any(a['start']>=b['start'] for a,b in zip(out,out[1:])):
        raise ValueError('Not enough valid closed candles')
    if now-out[-1]['end']>25*60*1000:raise ValueError('Stale candles: refusing entries')
    return out

def synthetic(symbol='BTCUSDT',count=350):
    rnd=random.Random(2200+SYMBOLS.index(symbol));price=32000+SYMBOLS.index(symbol)*1000;out=[]
    for i in range(count):
        o=price;price=max(.1,o*math.exp((.001 if i//90%2 else -.001)+rnd.gauss(0,.004)))
        h=max(o,price)*(1+abs(rnd.gauss(0,.002)));l=min(o,price)*(1-abs(rnd.gauss(0,.002)))
        t=1710000000000+i*900000
        out.append(dict(start=t,end=t+899999,o=o,h=h,l=l,c=price,volume=1000))
    return out

def fresh_state():
    return dict(balance=START_BALANCE,positions={},trades=[],processed={},day='',day_start=START_BALANCE,checked=0,skipped=0)

def load_state(path):
    if not path.exists():return fresh_state()
    x=json.loads(path.read_text(encoding='utf8'))
    if not isinstance(x,dict) or any(k not in x for k in fresh_state()):
        raise ValueError('Paper state is corrupted; halt rather than reset positions')
    return x

def save_state(path,s):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(s,indent=2,ensure_ascii=False),encoding='utf8')
    os.replace(tmp,path)

def step(s,symbol,bars):
    b=bars[-1]
    if b['start']<=int(s['processed'].get(symbol,-1)):return False
    today=datetime.fromtimestamp(b['end']/1000,timezone.utc).date().isoformat()
    if s['day']!=today:
        s['day']=today;s['day_start']=s['balance']
    p=s['positions'].get(symbol)
    if p:
        p['bars_held']+=1
        if p['side']=='LONG':
            hit_stop=b['l']<=p['stop'];hit_target=b['h']>=p['target']
        else:
            hit_stop=b['h']>=p['stop'];hit_target=b['l']<=p['target']
        reason='STOP' if hit_stop else 'TARGET' if hit_target else 'TIME' if p['bars_held']>=32 else None
        if reason:
            fill=p['stop'] if hit_stop else p['target'] if hit_target else b['c']
            fill*=1-SLIPPAGE if p['side']=='LONG' else 1+SLIPPAGE
            pnl=(fill-p['entry'])*p['qty']*(1 if p['side']=='LONG' else -1)
            s['balance']+=pnl-fill*p['qty']*FEE
            s['trades'].append(dict(symbol=symbol,side=p['side'],entry=p['entry'],exit=fill,
                                    pnl=pnl-fill*p['qty']*FEE-p['entry_fee'],reason=reason,end=b['end']))
            del s['positions'][symbol]
    s['processed'][symbol]=b['start'];s['checked']+=1
    if symbol in s['positions'] or len(s['positions'])>=MAX_OPEN:return True
    if s['balance']<=s['day_start']*(1-DAILY_STOP):
        s['skipped']+=1;return True
    direction,vol=signal(bars)
    if not direction:return True
    entry=b['c']*(1+SLIPPAGE if direction=='LONG' else 1-SLIPPAGE)
    distance=max(vol*1.8,entry*.004)
    if distance/entry>.05:return True
    existing=sum(v['qty']*v['entry'] for v in s['positions'].values())
    free=max(0,.9*s['balance']-existing)
    qty=min(max(0,s['balance'])*RISK/distance,.65*max(0,s['balance'])/entry,free/entry)
    if qty*entry<10:return True
    stop=entry-distance if direction=='LONG' else entry+distance
    target=entry+1.8*distance if direction=='LONG' else entry-1.8*distance
    if min(stop,target)<=0:return True
    fee=qty*entry*FEE;s['balance']-=fee
    s['positions'][symbol]=dict(side=direction,entry=entry,qty=qty,stop=stop,
                                target=target,bars_held=0,entry_fee=fee)
    return True

def write_report(path,s,feed):
    path.parent.mkdir(parents=True,exist_ok=True)
    trades=s['trades'];wins=sum(x['pnl']>0 for x in trades)
    result=dict(mode=feed,starting_usdt=START_BALANCE,balance_usdt=round(s['balance'],2),
                closed_trades=len(trades),wins=wins,win_rate=round(100*wins/len(trades),2) if trades else None,
                open_positions=len(s['positions']),scanned_closed_candles=s['checked'],
                disclaimer='PAPER ONLY; hypothetical fills, no funding/liquidation modeled')
    path.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf8')
    with path.with_suffix('.csv').open('w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=['symbol','side','entry','exit','pnl','reason','end'])
        writer.writeheader();writer.writerows(trades)
    return result

def one_cycle(s,pairs):
    histories={};pending=[];good=0
    for symbol in pairs:
        try:
            bars=fetch_klines(symbol);histories[symbol]=bars
            previous=s['processed'].get(symbol)
            indexes=[len(bars)-1] if previous is None else [i for i,b in enumerate(bars) if i>=65 and b['start']>previous]
            pending.extend((bars[i]['start'],symbol,i) for i in indexes)
            good+=1
        except Exception as exc:
            logging.error('No trusted feed for %s: %s; NO TRADES',symbol,exc)
    for _,symbol,i in sorted(pending):
        step(s,symbol,histories[symbol][:i+1])
    if not good:raise RuntimeError('No Binance market data available; not inventing prices')

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=['once','loop','offline-test','backtest'],default='once')
    p.add_argument('--symbols',default=','.join(SYMBOLS))
    p.add_argument('--state',default='data/paper_state.json')
    p.add_argument('--report',default='data/summary.json')
    args=p.parse_args(argv)
    pairs=[s.strip().upper() for s in args.symbols.split(',')]
    if not pairs or len(set(pairs))!=len(pairs) or any(s not in SYMBOLS for s in pairs):p.error('Invalid pair selection')
    logging.basicConfig(level=logging.INFO,format='%(levelname)s: %(message)s')
    state_path=Path(args.state);report_path=Path(args.report)
    if args.mode in ('backtest','offline-test'):
        data={s:(synthetic(s) if args.mode=='offline-test' else fetch_klines(s,180)) for s in pairs}
        s=fresh_state();indices={x:0 for x in pairs}
        timestamps=sorted(set(b['start'] for candles in data.values() for b in candles))
        for ts in timestamps:
            for sym in pairs:
                bars=data[sym];i=indices[sym]
                if i<len(bars) and bars[i]['start']==ts:
                    if i>=65:step(s,sym,bars[:i+1])
                    indices[sym]+=1
        print(json.dumps(write_report(report_path,s,'SYNTHETIC TEST DATA' if args.mode=='offline-test' else 'BINANCE HISTORICAL PAPER'),indent=2))
        return 0
    s=load_state(state_path)
    while True:
        try:
            one_cycle(s,pairs);save_state(state_path,s)
            print(json.dumps(write_report(report_path,s,'BINANCE PUBLIC DATA: PAPER ONLY'),indent=2))
        except Exception:logging.exception('No real orders exist; paper analysis paused')
        if args.mode!='loop':break
        time.sleep(75)
    return 0

if __name__=='__main__':raise SystemExit(main())
