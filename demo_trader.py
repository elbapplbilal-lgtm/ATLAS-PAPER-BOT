#!/usr/bin/env python3
"""ATLAS: Binance USD-M Futures DEMO ONLY.

Hard-coded DEMO exchange hostname. NO real-money trading functions.
Requires demo API credentials and explicit order opt-in.
Do not treat paper-trading strategy as evidence of profitability.
"""
from __future__ import annotations
import argparse, hashlib, hmac, json, logging, math, os, time
import urllib.request, urllib.parse
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from strategy_v2 import analyze

DEMO_HOST = 'https://demo-fapi.binance.com'
SYMBOL = 'BTCUSDT'
STATE = Path('data/demo_state.json')
MAX_STOP_RISK = Decimal('0.005')
MAX_EXPOSURE = Decimal('0.10')
DAILY_STOP = Decimal('0.02')
MAX_DAILY_ENTRIES = 5

class DemoError(RuntimeError):pass

def api_candles(interval='15m'):
    if interval not in ('15m','1h'):raise DemoError('Unsupported analysis interval')
    q=urllib.parse.urlencode({'symbol':SYMBOL,'interval':interval,'limit':300})
    req=urllib.request.Request(DEMO_HOST+'/fapi/v1/klines?'+q,headers={'User-Agent':'ATLAS-DEMO-ONLY'})
    try:
        with urllib.request.urlopen(req,timeout=12) as r:data=json.load(r)
    except Exception as e:raise DemoError('Binance Demo market feed unavailable') from e
    if not isinstance(data,list):raise DemoError('Unexpected demo response')
    now=int(time.time()*1000);bars=[]
    for x in data:
        try:
            b=dict(start=int(x[0]),o=float(x[1]),h=float(x[2]),l=float(x[3]),
                   c=float(x[4]),volume=float(x[5]),end=int(x[6]))
            if not all(math.isfinite(b[k]) for k in ('o','h','l','c')) or b['l']<=0 or b['l']>min(b['o'],b['c']) or b['h']<max(b['o'],b['c']):
                raise ValueError()
        except Exception as e:raise DemoError('Invalid demo exchange price') from e
        if b['end']<now:bars.append(b)
    if len(bars)<225 or any(a['start']>=b['start'] for a,b in zip(bars,bars[1:])):
        raise DemoError('Not enough closed demo candles')
    if now-bars[-1]['end']>(25 if interval=='15m' else 80)*60*1000:raise DemoError('Demo '+interval+' candles stale')
    return bars

class DemoClient:
    def __init__(self,key=None,secret=None):
        self.key=key or os.environ.get('BINANCE_DEMO_KEY','')
        self.secret=secret or os.environ.get('BINANCE_DEMO_SECRET','')
        if not self.key or not self.secret:
            raise DemoError('DEMO keys missing. Never paste API credentials into chat or public code.')

    def call(self,method,path,params=None,signed=True):
        if method not in ('GET','POST') or not path.startswith('/fapi/'):
            raise DemoError('Unsupported API method/path')
        vals=dict(params or {})
        if signed:vals.update({'timestamp':int(time.time()*1000),'recvWindow':5000})
        encoded=urllib.parse.urlencode(vals)
        if signed:
            signature=hmac.new(self.secret.encode(),encoded.encode(),hashlib.sha256).hexdigest()
            encoded+='&signature='+signature
        url=DEMO_HOST+path+('?' + encoded if method=='GET' and encoded else '')
        req=urllib.request.Request(url,data=(encoded.encode() if method=='POST' else None),
             method=method,headers={'X-MBX-APIKEY':self.key,'User-Agent':'ATLAS-DEMO-ONLY',
                                    'Content-Type':'application/x-www-form-urlencoded'})
        try:
            with urllib.request.urlopen(req,timeout=12) as response:return json.load(response)
        except Exception as e:
            # Do not retry unknown POST outcomes. It may already have filled.
            raise DemoError('Binance DEMO API request failed: '+method+' '+path+' ('+type(e).__name__+')') from e

def quant_down(x,step):
    if step<=0:raise DemoError('Bad exchange quantity/tick step')
    return (x/step).to_integral_value(rounding=ROUND_DOWN)*step

def dec(x):return format(x,'f')

def filters(client):
    info=client.call('GET','/fapi/v1/exchangeInfo',signed=False)
    row=next((s for s in info.get('symbols',[]) if s.get('symbol')==SYMBOL),None)
    if not row or row.get('status')!='TRADING':raise DemoError('BTCUSDT not trading in DEMO')
    fl={f['filterType']:f for f in row.get('filters',[])}
    lot=fl.get('LOT_SIZE');market=fl.get('MARKET_LOT_SIZE') or lot;price=fl.get('PRICE_FILTER')
    if not lot or not market or not price:raise DemoError('Missing exchange filters')
    return dict(step=max(Decimal(lot['stepSize']),Decimal(market['stepSize'])),
                minQty=max(Decimal(lot['minQty']),Decimal(market['minQty'])),
                maxQty=min(Decimal(lot['maxQty']),Decimal(market['maxQty'])),
                tick=Decimal(price['tickSize']))

def read_state():
    if not STATE.exists():return {}
    v=json.loads(STATE.read_text(encoding='utf8'))
    if not isinstance(v,dict):raise DemoError('Invalid state file')
    return v

def save_state(v):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    temp=STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(v,indent=2),encoding='utf8')
    temp.replace(STATE)

def account_checks(client):
    mode=client.call('GET','/fapi/v1/positionSide/dual')
    if str(mode.get('dualSidePosition')).lower()!='false':
        raise DemoError('DEMO account must be in One-way mode')
    positions=client.call('GET','/fapi/v2/positionRisk')
    if not isinstance(positions,list) or any(Decimal(str(p.get('positionAmt','0')))!=0 for p in positions):
        raise DemoError('An existing DEMO position or invalid account response blocks entries')
    orders=client.call('GET','/fapi/v1/openOrders',{'symbol':SYMBOL})
    if not isinstance(orders,list) or orders:raise DemoError('Pending DEMO orders require manual review')
    algos=client.call('GET','/fapi/v1/openAlgoOrders',{'symbol':SYMBOL})
    if not isinstance(algos,list) or algos:raise DemoError('Pending DEMO conditional orders require review')
    acc=client.call('GET','/fapi/v2/account')
    wallet=Decimal(str(acc['totalWalletBalance']))
    available=Decimal(str(acc['availableBalance']))
    if wallet<=0 or available<=0:raise DemoError('No available demo balance')
    return wallet,available

def run_once(client=None,enable_orders=False):
    bars=api_candles();bar=bars[-1]
    higher=[b for b in api_candles('1h') if b['end']<=bar['end']]
    try: setup=analyze(bars,higher)
    except ValueError as e:raise DemoError('Unable to validate multi-timeframe candles: '+str(e)) from e
    direction=setup.side
    if not direction:return 'No confirmed 15m+1h DEMO setup (score='+str(setup.score)+'/6): '+setup.reason
    state=read_state()
    day=time.strftime('%Y-%m-%d',time.gmtime(bar['end']/1000))
    if state.get('day')!=day:state=dict(day=day,initial_wallet=None,entries_today=0,last_attempted_bar=None)
    if state.get('last_attempted_bar')==bar['start']:
        return 'This demo candle already attempted. No duplicate.'
    if not enable_orders or os.environ.get('ENABLE_BINANCE_DEMO_ORDERS','')!='YES':
        return 'Signal '+direction+' for '+SYMBOL+'; demo orders are DISABLED.'
    client=client or DemoClient()
    wallet,available=account_checks(client)
    if state['initial_wallet'] is None:state['initial_wallet']=dec(wallet)
    if wallet<Decimal(state['initial_wallet'])*(1-DAILY_STOP):
        raise DemoError('DEMO daily stop reached')
    if state['entries_today']>=MAX_DAILY_ENTRIES:raise DemoError('DEMO entry limit reached')
    rule=filters(client)
    entry=Decimal(str(bar['c']))
    distance=Decimal(str(setup.stop_distance))
    if distance/entry>Decimal('0.05'):return 'Volatility too high; no order.'
    quantity=quant_down(min(wallet*MAX_STOP_RISK/distance,available*MAX_EXPOSURE/entry),rule['step'])
    if quantity<rule['minQty'] or quantity>rule['maxQty'] or quantity*entry<Decimal('10'):
        return 'Demo order size below exchange minimum; no order.'
    # 1x isolated, one-way, no existing positions/order by account checks.
    client.call('POST','/fapi/v1/leverage',{'symbol':SYMBOL,'leverage':1})
    pos=client.call('GET','/fapi/v2/positionRisk',{'symbol':SYMBOL})
    if not isinstance(pos,list) or len(pos)!=1:raise DemoError('Position mode/account changed')
    if str(pos[0].get('marginType','')).lower()!='isolated':
        client.call('POST','/fapi/v1/marginType',{'symbol':SYMBOL,'marginType':'ISOLATED'})
    # Save attempted bar BEFORE sending to avoid duplicate orders after a network timeout.
    state['last_attempted_bar']=bar['start'];state['entries_today']+=1
    save_state(state)
    side='BUY' if direction=='LONG' else 'SELL'
    exit_side='SELL' if direction=='LONG' else 'BUY'
    placed=client.call('POST','/fapi/v1/order',
        {'symbol':SYMBOL,'side':side,'type':'MARKET','quantity':dec(quantity),
         'newClientOrderId':'atlasd_'+str(bar['start'])+'_btc',
         'newOrderRespType':'RESULT'})
    if placed.get('status')!='FILLED' or Decimal(str(placed.get('executedQty','0')))<=0:
        raise DemoError('Unknown order fill status. Stop and inspect DEMO manually.')
    fill=Decimal(str(placed.get('avgPrice') or '0'))
    if fill<=0:raise DemoError('No valid fill price: DEMO manual review required')
    stop=quant_down(fill-distance if direction=='LONG' else fill+distance,rule['tick'])
    target=quant_down(fill+distance*Decimal(str(setup.rr)) if direction=='LONG' else fill-distance*Decimal(str(setup.rr)),rule['tick'])
    if min(stop,target)<=0:raise DemoError('Invalid protective levels; manual DEMO review')
    def protect(kind,trigger):
        return client.call('POST','/fapi/v1/algoOrder',
            {'algoType':'CONDITIONAL','symbol':SYMBOL,'side':exit_side,
             'type':kind,'triggerPrice':dec(trigger),
             'closePosition':'true','workingType':'CONTRACT_PRICE'})
    try:
        protect('STOP_MARKET',stop)
    except DemoError as err:
        try:
            client.call('POST','/fapi/v1/order',
                {'symbol':SYMBOL,'side':exit_side,'type':'MARKET',
                 'quantity':placed['executedQty'],'reduceOnly':'true'})
        except DemoError as emergency:
            raise DemoError('CRITICAL: DEMO position may be unprotected! Close manually.') from emergency
        raise DemoError('Protective stop failed; emergency DEMO close attempted') from err
    try:protect('TAKE_PROFIT_MARKET',target)
    except DemoError:
        raise DemoError('DEMO stop in place; take-profit failed. Manual review needed.')
    return 'DEMO filled '+direction+' '+SYMBOL+' confidence confirmations='+str(setup.score)+'/6 (not probability) qty='+dec(quantity)+' SL='+dec(stop)+' TP='+dec(target)

def main():
    parser=argparse.ArgumentParser(description='BINANCE FUTURES DEMO ONLY')
    parser.add_argument('--mode',choices=['signal','health','trade-once'],default='signal')
    args=parser.parse_args()
    try:
        if args.mode=='signal':
            bars=api_candles();higher=[b for b in api_candles('1h') if b['end']<=bars[-1]['end']]
            setup=analyze(bars,higher)
            print('Binance DEMO 15m+1h analysis:',setup.side or 'NO TRADE',
                  'confirmations=',str(setup.score)+'/6','reason=',setup.reason)
            return 0
        if args.mode=='health':
            wallet,avail=account_checks(DemoClient())
            print('Demo connection works. Balance:',wallet,'Available:',avail)
            return 0
        print(run_once(enable_orders=True));return 0
    except (DemoError,ValueError) as exc:
        logging.error('%s',exc);return 2

if __name__=='__main__':raise SystemExit(main())
