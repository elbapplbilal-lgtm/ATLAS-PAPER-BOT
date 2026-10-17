# ATLAS V2 — BTCUSDT historical simulation (2026-10-17)

> Exploratory **independent reimplementation** of the rules in `strategy_v2.py`, tested on Binance USD-M Futures public historical OHLCV received through the connected Binance market-data tool. This is **not a run of the Python strategy file**, nor an exchange order test, nor a guarantee of live execution. DO NOT use it as proof of profitability.

## Input / assumptions

- Symbol: BTCUSDT, Binance USD-M Futures (public OHLCV, not the Demo account).
- 15-minute candles: 1,499 completed candles, starting 2026-10-02 05:30 UTC and ending 2026-10-17 20:14:59.999 UTC.
- 1-hour candles: 599 completed candles, 2026-09-22 21:00 UTC through 2026-10-17 19:59:59.999 UTC.
- Last returned candle of each timeframe discarded to exclude potentially forming candles.
- Signal filters reconstructed from ATLAS V2: 1-hour EMA50/200 trend plus EMA50 slope, 15m EMA20/50/200, RSI14, ADX14, relative volume vs 20 prior bars, candle breakout/bounce confirmation, volatility and oversized-candle filter. Requires 6/6 confirmations.
- **No look-ahead** in hourly selection: only 1-hour bars closed at the 15m signal decision timestamp. Entry simulated at **next 15m candle open**, then 0.03% adverse entry slippage.
- 1x nominal exposure at **most 10% of current simulated balance** per position, risk-budget sizing target 0.5% account balance / stop distance, one position at a time, at most five entries per UTC day, daily stop at -2% of balance measured at day opening.
- Protective levels: max(1.8× ATR14, 0.4% entry price) with a 1.8R target. If both stop and target touch within the same candle, count **stop first**. Time exit after 32 15m candles.
- 0.04% commission both entry and exit; adverse exit slippage 0.03%. Funding, position-lot step limits, minimum order constraints, API timing, liquidity gaps beyond modeled slippage and demo-specific execution mechanics **not modeled**.

## Results (illustrative; not reliable financial forecasts)

| Metric | Result |
|---|---:|
| Initial balance | 5,000.00 USDT |
| End balance (realized fees included) | 4,994.32 USDT |
| Net outcome | -5.68 USDT (-0.11%) |
| Strict-rule entry signals | 19 |
| Simulated completed trades | 15 |
| Winning trades | 6 |
| Losing trades | 9 |
| Win rate (completed trades) | 40% |
| Signals skipped while in positions / due to daily caps | 4 |
| Open simulated positions at end | 0 |

The result is **negative** on this short period. It does not establish the future win rate. The strategy was **not** validated for deployment to real-money Binance Futures. In particular, no actual Demo entries, stops, or take-profit orders have been verified, and the GitHub/Railway runners previously received HTTP 451 when accessing the public Futures Demo API.

## Next steps before any live-account consideration

1. Build a repeatable Python backtest that runs the actual `strategy_v2.py` on longer, separated in-sample and out-of-sample OHLCV data, with funding, fees, lot sizes, latency, and realistic gaps.
2. Verify the signed read-only Demo API from an access-permitted, user-controlled execution environment.
3. Manually observe small **Demo-only** orders with protective stop handling verified and reliable state storage.
4. Do not transfer funds or use real-money API credentials with the existing bot.

The six confirmations are a **filter count**, not a probability of profitable trading. The cap of five positions/day is not a target for five winning trades.
