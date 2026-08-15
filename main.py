from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import logging
import server as ta_server
import os
import json
import time
import asyncio
import traceback
from dotenv import load_dotenv
import pandas as pd

load_dotenv()
app = FastAPI()

IST = timezone(timedelta(hours=5, minutes=30))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Query(BaseModel):
    user_input: str
    show_logs: bool = False

YELLOW_STYLE = "background-color: #2d2d2d; padding: 2px 6px; border-radius: 4px; color: #ffbd2e; font-size: 19px;"
GREEN_COLOR = "rgb(159, 222, 161)"

def y(text):
    return f'<span style="{YELLOW_STYLE}">{text}</span>'

def g(text):
    return f'<span style="color: {GREEN_COLOR};">{text}</span>'

def view_link(url):
    if url:
        return f' <a href="{url}" target="_blank" style="{YELLOW_STYLE} text-decoration: none;">[View]</a>'
    return ""

def fmt_in(num):
    if num is None or not isinstance(num, (int, float)) or pd.isna(num):
        return "N/A"
    try:
        s = f"{abs(float(num)):,.2f}"
        parts = s.split(".")
        int_part = parts[0].replace(",", "")
        dec_part = parts[1]
        if len(int_part) > 3:
            last3 = int_part[-3:]
            rest = int_part[:-3]
            rest = rest[::-1]
            chunks = [rest[i:i+2] for i in range(0, len(rest), 2)]
            rest = ",".join(chunks)[::-1]
            int_part = f"{rest},{last3}"
        res = f"{int_part}.{dec_part}"
        return f"-{res}" if float(num) < 0 else res
    except:
        return str(num)

def determine_action(tech_score, net_rr_ratio, lt_trend, adx_val, volatility_state, direction, nifty_trend, atr_percentile, earnings_risk, data_age, daily_hist_days, oos_expectancy):
    if data_age > 300:
        return "NO TRADE (Data Stale)"
    if daily_hist_days < 200:
        return "NO TRADE (Daily History Unavailable)"
    if earnings_risk:
        return "WAIT (Event Risk - Earnings Soon)"
    if atr_percentile > 95:
        return "NO TRADE (Extreme Relative Volatility)"
    if oos_expectancy is not None and oos_expectancy <= 0:
        return "NO TRADE (Negative OOS Expectancy)"
        
    req_rr = 2.5 if volatility_state == "High volatility" else 1.5
    

    fail_reasons = []
    if net_rr_ratio <= 0:
        fail_reasons.append("Negative Net Reward")
    elif net_rr_ratio < req_rr:
        fail_reasons.append(f"R:R < {req_rr}")
        
    if adx_val < 25:
        fail_reasons.append("ADX < 25")
        
    if fail_reasons:
        if direction == "SHORT" and lt_trend == "BEARISH":
            return f"🔴 AVOID / NO TRADE (Failed: {', '.join(fail_reasons)})"
        return f"🟡 WAIT (Failed: {', '.join(fail_reasons)})"
    

    if lt_trend == "BEARISH":
        if direction == "SHORT" and tech_score <= -2:
            if nifty_trend >= 2:
                return "WAIT (Nifty is strongly up)"
            return "SHORT"
        return "AVOID"
    else:
        if direction == "LONG" and tech_score >= 2:
            if nifty_trend <= -2:
                return "WAIT (Nifty is down)"
            return "BUY"
        return "WAIT"

def generate_beginner_guide(name, action, cp, entry, stop, target_price, lt_trend, lt_buy, lt_sell, tech_score, net_rr_ratio, direction, st_trend):
    if action == "BUY":
        action_emoji = "🟢 CONSIDER BUYING"
        st_advice = f"**Short term:**\nMomentum is bullish. Don't chase the stock at the current price of ₹{fmt_in(cp)}. Wait for it to hit the buy zone.\n\n* **Buy:** {y(f'₹{fmt_in(entry)}')}\n* **Target:** {y(f'₹{fmt_in(target_price)}')}\n* **Stop:** {y(f'₹{fmt_in(stop)}')}"
    elif action == "SHORT":
        action_emoji = "🔴 CONSIDER SHORTING"
        st_advice = f"**Short term:**\nThe trend is down. Consider shorting on a rise to the entry zone.\n\n* **Short Entry:** {y(f'₹{fmt_in(entry)}')}\n* **Target (Buy Back):** {y(f'₹{fmt_in(target_price)}')}\n* **Stop Loss:** {y(f'₹{fmt_in(stop)}')}"
    elif "AVOID" in action:
        action_emoji = "🔴 AVOID / NO TRADE"
        st_advice = f"**Short term:**\nMomentum is {st_trend.lower()}, but the broader trend remains bearish. A short-on-rise setup exists, but it fails the minimum R:R requirement after costs. Do not trade."
    elif "NO TRADE" in action:
        action_emoji = "⛔ NO TRADE"
        st_advice = f"**Short term:**\nConditions are unsafe for trading (Extreme Volatility, Stale Data, or Negative Net Reward). Capital preservation is priority."
    else:
        action_emoji = "🟡 WAIT"
        reason = "Market is sideways, signals are mixed, or R:R is insufficient after costs." if "sideways" in action or "Failed" in action or "costs" in action else "Event Risk is pending."
        st_advice = f"**Short term:**\nDon't buy at {y(f'₹{fmt_in(cp)}')}. Better entry: **{y(f'₹{fmt_in(entry)}')}**\n\nIf it reaches that area:\n* **Buy:** {y(f'₹{fmt_in(entry)}')}\n* **Target:** {y(f'₹{fmt_in(target_price)}')}\n* **Stop:** {y(f'₹{fmt_in(stop)}')}\n\n**Why?**\n{reason}"

    if lt_trend == "BEARISH":
        lt_advice = f"**Long term:**\nCurrent trend bias is bearish. Monitor the ₹{fmt_in(lt_buy)} area for potential support, but require price stabilization and confirmation before considering a long-term entry."
    elif lt_trend == "UNKNOWN":
        lt_advice = f"**Long term:**\nData unavailable to determine long-term trend."
    else:
        lt_advice = f"**Long term:**\nThe larger trend bias is bullish. You can hold, with a potential longer-term target around **₹{fmt_in(lt_sell)}**."

    return f"""### {name} — {g('WHAT SHOULD I DO RIGHT NOW?')} | Current Price :  **{y(f'₹{fmt_in(cp)}')}**

**Current decision: {action_emoji}**


{st_advice}

{lt_advice}
"""

def generate_markdown(ticker, profile, short_term, long_term, stock_news, global_news, tech_score, action, net_rr_ratio, req_rr, backtest_data, nifty_trend, fundamentals, earnings_risk, data_source, data_age, daily_hist_days):
    name = profile.get("name", ticker)
    company_desc = profile.get("description", "N/A")
    cp = short_term.get("current_price", "N/A")
    
    reasons = short_term.get("quant_reasons", [])
    
    sma_50 = long_term.get("moving_averages", {}).get("sma_50", 0)
    sma_200 = long_term.get("moving_averages", {}).get("sma_200", 0)
    
    if sma_50 > 0 and sma_200 > 0:
        lt_trend = "BEARISH" if sma_50 < sma_200 else "BULLISH"
    else:
        lt_trend = "UNKNOWN"
    
    if tech_score >= 2: st_trend = "BULLISH"
    elif tech_score <= -2: st_trend = "BEARISH"
    else: st_trend = "NEUTRAL / SIDEWAYS"
        
    if st_trend == "BULLISH" and lt_trend == "BEARISH": 
        regime = "RECOVERY / MIXED — price has recovered above the 50-DMA, but the 50-DMA remains below the 200-DMA."
    elif st_trend == "BEARISH" and lt_trend == "BULLISH": 
        regime = "PULLBACK / WARNING — price has fallen below the 50-DMA, but the 50-DMA remains above the 200-DMA."
    else: 
        regime = lt_trend

    p6 = short_term.get('performance_windows', {}).get('6h', {})
    p12 = short_term.get('performance_windows', {}).get('12h', {})
    p24 = short_term.get('performance_windows', {}).get('24h', {})
    bc = short_term.get('background_calculations', {})
    rsi = bc.get('RSI_14', {})
    stoch_rsi = bc.get('Stoch_RSI', {})
    macd = bc.get('MACD', {})
    bb = bc.get('Bollinger_Bands', {})
    atr = bc.get('ATR', {})
    adx = bc.get('ADX', {})
    vwap = bc.get('VWAP', {})
    projections = short_term.get('time_projections', [])
    atr_percentile = bc.get('ATR', {}).get('percentile', 0)
    

    if atr_percentile > 95:
        vol_status = "Extreme volatility (NO TRADE)"
    elif atr_percentile > 80:
        vol_status = "Elevated volatility"
    elif atr_percentile < 20:
        vol_status = "Very low volatility"
    else:
        vol_status = "Normal volatility"
    
    proj_str = ""
    seen_times = set()
    for p in projections:
        t = p.get('time', 'N/A')
        if t in seen_times: continue
        seen_times.add(t)
        p_min = p.get('min', 0)
        p_max = p.get('max', 0)
        proj_str += f"* **{y(t)}**: Expected volatility range (ATR-based) is **{y(f'₹{fmt_in(p_min)} - ₹{fmt_in(p_max)}')}**.\n"
        
    
    if not proj_str:
        proj_str = "* Market is currently closed. Intraday projections are available during live market hours (09:15 - 15:30 IST)."
            
    targets = short_term.get('actionable_targets', {})
    entry = targets.get('entry', 0)
    stop = targets.get('stop_loss', 0)
    target_price = targets.get('target', 0)
    direction = targets.get('direction', 'LONG')
    
    risk_per_share = round(abs(entry - stop), 2) if entry and stop else 0
    reward_per_share = round(abs(target_price - entry), 2) if entry and target_price else 0
    

    entry_label = f"{y(f'₹{fmt_in(entry)}')}"
    if direction == "SHORT" and entry > cp:
        entry_label += " *(short only if price rallies to this level)*"
        
    def calc_costs(entry_p, exit_p):
        turnover = entry_p + exit_p
        brokerage = 0 
        stt = (entry_p * 0.001) + (exit_p * 0.001) 
        exchange_txn = turnover * 0.0000335
        gst = (brokerage + exchange_txn) * 0.18
        sebi = turnover * 0.000001
        stamp_duty = entry_p * 0.00015 
        slippage = turnover * 0.0005 
        return brokerage + stt + exchange_txn + gst + sebi + stamp_duty + slippage

    costs = calc_costs(entry, target_price) if entry and target_price else 0
    net_reward_per_share = round(reward_per_share - costs, 2)
    
    high_52w = long_term.get('52_week_high', 'N/A')
    low_52w = long_term.get('52_week_low', 'N/A')
    ma = long_term.get('moving_averages', {})
    sma_50_str = ma.get('sma_50', 'N/A')
    sma_200_str = ma.get('sma_200', 'N/A')
    if isinstance(sma_50_str, (int, float)) and sma_50_str > 0 and isinstance(sma_200_str, (int, float)) and sma_200_str > 0:
        dma_status = "the 50-day is above the 200-day, meaning the long-term trend bias is bullish" if sma_50_str > sma_200_str else "the 50-day is below the 200-day, meaning the long-term trend bias is bearish"
    else:
        dma_status = "data unavailable"
    fib = long_term.get('fibonacci_retracement', {})
    lt_targets = long_term.get('long_term_targets', {})
    lt_buy = lt_targets.get('buy_target', 'N/A')
    lt_sell = lt_targets.get('sell_target', 'N/A')
    
    beginner_guide = generate_beginner_guide(name, action, cp, entry, stop, target_price, lt_trend, lt_buy, lt_sell, tech_score, net_rr_ratio, direction, st_trend)
    
    stock_news_str = "\n".join([f"- {n['text']}{view_link(n.get('url', ''))}" if isinstance(n, dict) else f"- {n}" for n in stock_news.get('latest_news_headlines', [])])
    global_news_str = "\n".join([f"- {n['text']}{view_link(n.get('url', ''))}" if isinstance(n, dict) else f"- {n}" for n in global_news.get('global_headlines', [])])

    reasons_str = "\n".join([f"  - {r}" for r in reasons])

   
    wf_bt = backtest_data.get('rolling_oos', {})
    wf_trades = wf_bt.get('total_trades', 0)
    
    if wf_trades < 10:
        wf_str = f"* **OOS Trades:** {wf_trades} (INSUFFICIENT DATA FOR VALIDATION)"
    else:
        wf_str = f"""
* **OOS Win Rate:** {y(f"{wf_bt.get('win_rate', 0)}%")} (95% CI: {wf_bt.get('win_rate_ci_low', 0)}-{wf_bt.get('win_rate_ci_high', 0)}%)
* **OOS Expectancy (Mean R/Trade):** {y(f"{wf_bt.get('expectancy', 0)}R")} (95% CI: {wf_bt.get('exp_ci_low', 0)}R to {wf_bt.get('exp_ci_high', 0)}R)
* **OOS Profit Factor:** {y(f"{wf_bt.get('profit_factor', 0)}")}
* **OOS Max Drawdown:** {y(f"{wf_bt.get('max_dd', 0)}R")} (Bootstrap 95% Worst: {wf_bt.get('mc_dd_95', 0)}R)
* **Portfolio CAGR:** {y(f"{wf_bt.get('cagr', 0)}%")} vs **Buy & Hold:** {y(f"{wf_bt.get('benchmark_return', 0)}%")}
* **Daily Sharpe:** {y(f"{wf_bt.get('sharpe', 0)}")} | **Daily Sortino:** {y(f"{wf_bt.get('sortino', 0)}")}
* **Robustness Test (OOS ATR 1.0/1.5/2.0):** {y(wf_bt.get('robustness', 'N/A'))}
* **Long Stats:** {wf_bt.get('long_trades', 0)} trades, {wf_bt.get('long_win_rate', 0)}% Win
* **Short Stats:** {wf_bt.get('short_trades', 0)} trades, {wf_bt.get('short_win_rate', 0)}% Win
"""

    return f"""**⏱️ Current Date & Time:** <span id="live-clock">Loading...</span>

**{y(ticker)}** | {company_desc}
[CHART:PRICE]

---

{beginner_guide}

=================================================

### {g('⏱ ATR Volatility Envelope')}
*Disclaimer: This is a volatility envelope based on Daily ATR, not a directional price prediction.*

{proj_str}

=================================================

###  {g('Trade Setup & Risk Management')}
*Levels derived from Daily ATR (14), Daily Bollinger Bands (20, 2), and Intraday ADX Trend Strength.*
* **Action:** {action}
* **Entry:** {entry_label}
* **Stop Loss:** {y(f'₹{fmt_in(stop)}')} (Risk: {y(f'₹{fmt_in(risk_per_share)}/share')})
* **Target:** {y(f'₹{fmt_in(target_price)}')} (Gross Reward: {y(f'₹{fmt_in(reward_per_share)}/share')})
* **Net Reward (after estimated trading costs/slippage):** {y(f'₹{fmt_in(net_reward_per_share)}/share')}
* **Net Risk/Reward Ratio:** {y(f'{net_rr_ratio} : 1')} (Required: {req_rr})
* *Note: Do not trade if R:R is below required threshold or ADX < 25.*

=================================================

### 📶 {g('Signal & Market Trend')}
* **Short-Term Momentum:** {y(st_trend)}
* **Long-Term Trend:** {y(lt_trend)}
* **Current Regime:** {y(regime)}
* **Nifty Trend Filter:** {y('Bullish' if nifty_trend > 0 else 'Bearish')} (Score: {nifty_trend})
* **Heuristic Technical Score:** {tech_score} (Pure Price Action)
* **Data Source:** {y(data_source)} (Age: {y(f"{data_age}s")})
* **Daily History Fetched:** {y(f"{daily_hist_days} days")}
* **90-day ATR percentile rank:** {y(f"{atr_percentile}%")} — {vol_status}; hard no-trade threshold: ≥95%.
* **Event Risk (Earnings < 3 days):** {y('YES' if earnings_risk else 'NO')}

**Technical Reasons:**
{reasons_str}

---
---

### 🧩 {g('The Math Explained Simply')}
* **Session VWAP:** ₹{fmt_in(vwap.get('value', 'N/A'))} - The average price weighted by volume for today's trading session. If current price > Session VWAP, intraday buyers currently have an advantage.
* **Intraday ADX (5m):** {adx.get('value', 'N/A')} - Measures intraday trend strength. If ADX > 25, the trend is strong. If < 25, the market is sideways and choppy.
* **RSI (Relative Strength Index):** {rsi.get('value', 'N/A')} - Compares the magnitude of recent gains to recent losses. RSI >70 indicates strong/possibly overextended momentum; RSI <30 indicates weak/possibly oversold momentum.
[CHART:RSI]
* **Stoch RSI (Stochastic RSI):** {stoch_rsi.get('value', 'N/A')} - Shows if RSI is at the extreme end of its range.
[CHART:STOCH_RSI]
* **MACD (Moving Average Convergence Divergence):** {macd.get('macd_line', 'N/A')} vs {macd.get('signal_line', 'N/A')} - Shows momentum by comparing 12-day and 26-day averages.
[CHART:MACD]
* **Daily Bollinger Bands:** Upper ₹{fmt_in(bb.get('upper_band', 'N/A'))}, Lower ₹{fmt_in(bb.get('lower_band', 'N/A'))} - Bollinger Bands measure price volatility relative to its moving average. Touching an outer band indicates an unusually large move relative to recent volatility, not necessarily that price is overvalued or undervalued.
* **Daily ATR (Average True Range):** {atr.get('value', 'N/A')} - Measures how much the stock price moves up and down in a day.

**Recent Trading Hours Performance:**
* **{y('~6 Hours')}:** Changed by {y(f"{p6.get('change_pct', 'N/A')}%")} (High {y(f"₹{fmt_in(p6.get('high', 'N/A'))}")}, Low {y(f"₹{fmt_in(p6.get('low', 'N/A'))}")})
* **{y('~12 Hours')}:** Changed by {y(f"{p12.get('change_pct', 'N/A')}%")} (High {y(f"₹{fmt_in(p12.get('high', 'N/A'))}")}, Low {y(f"₹{fmt_in(p12.get('low', 'N/A'))}")})
* **{y('~24 Hours')}:** Changed by {y(f"{p24.get('change_pct', 'N/A')}%")} (High {y(f"₹{fmt_in(p24.get('high', 'N/A'))}")}, Low {y(f"₹{fmt_in(p24.get('low', 'N/A'))}")})

=================================================

###  {g('Long-Term Technical Levels')}
* **52-Week High:** ₹{fmt_in(high_52w)} | **52-Week Low:** ₹{fmt_in(low_52w)}
* **50-DMA & 200-DMA (Daily Moving Averages):** ₹{fmt_in(sma_50_str)} & ₹{fmt_in(sma_200_str)} - Average price over 50 and 200 days. Here {dma_status}.
* **Potential Support Zone (52W Low / Fib 100%):** ₹{fmt_in(lt_buy)}
* **Potential Resistance Zone (52W High / Fib 0%):** ₹{fmt_in(lt_sell)}
[CHART:LONG_TERM]


---
---

### 📰 News & Events

**{g('Stock Specific News:')}**
{stock_news_str}


=================================================

**{g('Global & Macro News (Events affecting all stocks):')}**
{global_news_str}

*⚠️ Disclaimer: Based on textbook technical math analysis, which historically wins only about 50-55% of the time.*
"""

async def process_data(ticker, stock_name, log_func=None):
    if log_func: await log_func(f"[SYSTEM] Initializing gAIn backend for {ticker}...")
    
    if log_func: await log_func("[DATA] Step 1/8: Fetching Company Profile...")
    profile = await asyncio.to_thread(ta_server.get_company_profile, ticker)
    
    if log_func: await log_func("[DATA] Step 2/8: Fetching 10 Year Daily Data (SMAs, ATR Percentile & Backtest)...")
    long_term = await asyncio.to_thread(ta_server.get_long_term_analysis, ticker)
    daily_sma_50 = long_term.get("moving_averages", {}).get("sma_50", 0)
    daily_sma_200 = long_term.get("moving_averages", {}).get("sma_200", 0)
    daily_atr_percentile = long_term.get("atr_percentile", 0)
    daily_hist_days = long_term.get("history_days", 0)
    
    if log_func: await log_func("[DATA] Step 3/8: Fetching Live Price & Intraday Data (5m)...")
    short_term = await asyncio.to_thread(ta_server.get_bid_ask_targets, ticker, daily_sma_50, daily_sma_200, daily_atr_percentile)
    
    if log_func: await log_func("[MACRO] Step 4/8: Fetching Nifty 50 Trend...")
    nifty_daily = await asyncio.to_thread(ta_server.get_long_term_analysis, "^NSEI")
    nifty_sma_50 = nifty_daily.get("moving_averages", {}).get("sma_50", 0)
    nifty_sma_200 = nifty_daily.get("moving_averages", {}).get("sma_200", 0)
    nifty_atr_pct = nifty_daily.get("atr_percentile", 0)
    nifty_data = await asyncio.to_thread(ta_server.get_bid_ask_targets, "^NSEI", nifty_sma_50, nifty_sma_200, nifty_atr_pct)
    nifty_trend = nifty_data.get("quant_score", 0)
    
    if log_func: await log_func("[FUND] Step 5/8: Fetching Fundamentals & Event Risk...")
    fundamentals, earnings_risk = await asyncio.to_thread(ta_server.get_fundamentals_and_events, ticker)
    
    if log_func: await log_func("[NEWS] Step 6/8: Fetching Stock Specific News...")
    stock_news = await asyncio.to_thread(ta_server.get_indian_stock_news, ticker, stock_name)
        
    if log_func: await log_func("[NEWS] Step 7/8: Fetching Global Macro News...")
    global_news = await asyncio.to_thread(ta_server.get_global_market_news)
    
    if log_func: await log_func("[QUANT] Step 8/8: Running Risk Engine & Statistical Validation...")
    tech_score = short_term.get("quant_score", 0)
    sma_50 = daily_sma_50
    sma_200 = daily_sma_200
    
    if sma_50 > 0 and sma_200 > 0:
        lt_trend = "BEARISH" if sma_50 < sma_200 else "BULLISH"
    else:
        lt_trend = "UNKNOWN"
    
    targets = short_term.get('actionable_targets', {})
    entry = targets.get('entry', 0)
    stop = targets.get('stop_loss', 0)
    target_price = targets.get('target', 0)
    direction = targets.get('direction', 'LONG')
    
    risk_per_share = abs(entry - stop) if entry and stop else 0
    reward_per_share = abs(target_price - entry) if entry and target_price else 0
    
    def calc_costs(entry_p, exit_p):
        turnover = entry_p + exit_p
        brokerage = 0
        stt = (entry_p * 0.001) + (exit_p * 0.001) 
        exchange_txn = turnover * 0.0000335
        gst = (brokerage + exchange_txn) * 0.18
        sebi = turnover * 0.000001
        stamp_duty = entry_p * 0.00015 
        slippage = turnover * 0.0005 
        return brokerage + stt + exchange_txn + gst + sebi + stamp_duty + slippage

    costs = calc_costs(entry, target_price) if entry and target_price else 0
    net_reward_per_share = reward_per_share - costs
    net_rr_ratio = round(net_reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0
    
    volatility_state = short_term.get('background_calculations', {}).get('ATR', {}).get('interpretation', 'Low volatility')
    adx_val = short_term.get('background_calculations', {}).get('ADX', {}).get('value', 0)
    atr_percentile = daily_atr_percentile
    req_rr = 2.5 if volatility_state == "High volatility" else 1.5
    
    data_source = short_term.get('data_source', 'Unknown')
    data_age = short_term.get('data_age_seconds', 999)
    
    oos_expectancy = long_term.get('backtest', {}).get('rolling_oos', {}).get('expectancy', None)
    
    action = determine_action(tech_score, net_rr_ratio, lt_trend, adx_val, volatility_state, direction, nifty_trend, atr_percentile, earnings_risk, data_age, daily_hist_days, oos_expectancy)
    
    backtest_data = long_term.get('backtest', {})
    
    reply = generate_markdown(ticker, profile, short_term, long_term, stock_news, global_news, tech_score, action, net_rr_ratio, req_rr, backtest_data, nifty_trend, fundamentals, earnings_risk, data_source, data_age, daily_hist_days)
    
    return {
        "reply": reply, 
        "short_chart_data": short_term.get("chart_data", []), 
        "long_chart_data": long_term.get("long_term_chart_data", []), 
        "targets": short_term.get("actionable_targets", {})
    }

@app.post("/get_live_data")
async def get_live_data(query: Query):
    ticker = query.user_input.strip().upper()

    if ticker in ["NIFTY", "NIFTY50", "NIFTY 50"]: ticker = "^NSEI"
    elif ticker in ["SENSEX", "BSE"]: ticker = "^BSESN"
    elif ticker in ["BANKNIFTY", "BANK NIFTY"]: ticker = "^NSEBANK"
    elif not (ticker.endswith(".NS") or ticker.endswith(".BO") or ticker.startswith("^")): ticker = f"{ticker}.NS"
    
    stock_name = ticker.replace(".NS", "").replace(".BO", "").replace("^", "")
    
    if query.show_logs:
        async def event_stream():
            queue = asyncio.Queue()

            async def log_msg(msg):
                await queue.put(f"LOG: {msg}\n")

            async def run_task():
                try:
                    payload = await process_data(ticker, stock_name, log_msg)
                    await queue.put(f"FINAL: {json.dumps(payload)}\n")
                except Exception as e:
                    await queue.put(f"LOG: [ERROR] Backend Exception: {str(e)}\n")
                    await queue.put(f"LOG: {traceback.format_exc()}\n")
                    payload = {"reply": f"Backend Error: {str(e)}", "short_chart_data": [], "long_chart_data": [], "targets": {}}
                    await queue.put(f"FINAL: {json.dumps(payload)}\n")
                finally:
                    await queue.put(None)

            task = asyncio.create_task(run_task())
            
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
                
            await task

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    
    else:
        try:
            payload = await process_data(ticker, stock_name)
            return payload
        except Exception as e:
            return {"reply": f"Backend Error: {str(e)}", "short_chart_data": [], "long_chart_data": [], "targets": {}}