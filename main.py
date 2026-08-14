from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime
import logging
import server as ta_server
import os
import json
import time
import asyncio
import traceback
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

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

def analyze_news_sentiment(headlines):
    bull_words = ["rally", "profit", "upgrade", "deal", "surge", "record", "approve", "win", "beat", "growth", "boost", "rise"]
    bear_words = ["crash", "ban", "fraud", "loss", "downgrade", "fall", "probe", "warning", "tax", "sell", "drag", "drop", "slide"]
    sentiment_score = 0
    matched_words = []
    for h in headlines:
        h_lower = h.lower()
        for w in bull_words:
            if w in h_lower and w not in matched_words:
                sentiment_score += 1
                matched_words.append(w)
        for w in bear_words:
            if w in h_lower and w not in matched_words:
                sentiment_score -= 1
                matched_words.append(w)
    return max(-2, min(2, sentiment_score)), matched_words

def determine_action(final_score, rr_ratio):
    if final_score >= 2 and rr_ratio >= 1.5:
        return "BUY"
    elif final_score <= -2 and rr_ratio >= 1.5:
        return "SELL / AVOID"
    else:
        return "WAIT"

def generate_beginner_guide(name, action, cp, entry, stop, target_price, lt_trend, lt_buy, lt_sell, final_score, rr_ratio):
    if action == "BUY":
        action_emoji = "🟢 CONSIDER BUYING"
        st_advice = f"**Short term:**\nDon't chase the stock at the current price of ₹{cp}. Wait for it to hit the buy zone.\n\n* **Buy:** ₹{entry}\n* **Target:** ₹{target_price}\n* **Stop:** ₹{stop}"
    elif action == "SELL / AVOID":
        action_emoji = "🔴 AVOID / SELL ON RISE"
        st_advice = f"**Short term:**\nThe math says **SELL**. It is risky to buy at the current price of ₹{cp}. If you already own it, consider selling.\n\n* **Buy (High Risk):** ₹{entry}\n* **Target:** ₹{target_price}\n* **Stop:** ₹{stop}"
    else:
        action_emoji = "🟡 WAIT"
        reason = "The stock is moving sideways and several signals disagree." if -1 <= final_score <= 1 else "The Risk/Reward ratio is not attractive enough."
        st_advice = f"**Short term:**\nDon't buy at ₹{cp}. Better entry: **₹{entry}**\n\nIf it reaches that area:\n* **Buy:** ₹{entry}\n* **Target:** ₹{target_price}\n* **Stop:** ₹{stop}\n\n**Why?**\n{reason} There's not enough evidence for a strong trade."

    if lt_trend == "BEARISH":
        lt_advice = f"**Long term:**\nCurrent trend is weak. **Wait for a stronger entry around ₹{lt_buy}** rather than buying heavily now."
    else:
        lt_advice = f"**Long term:**\nThe larger trend is bullish. You can hold, with a potential longer-term target around **₹{lt_sell}**."

    return f"""### {name} — WHAT SHOULD I DO RIGHT NOW? - **₹{cp}**

**Current decision: {action_emoji}**


{st_advice}

{lt_advice}
"""

def generate_why_not_trade(action, reasons, rr_ratio):
    if action != "WAIT": 
        return ""
    
    neg_reasons = []
    for r in reasons:
        if any(word in r for word in ["Bearish", "Sellers", "Downtrend", "Death", "Dry Up", "Overextended", "Dump"]):
            neg_reasons.append(r)
            
    text = "### 🚫 Why I'm NOT recommending a trade\n\n"
    if rr_ratio < 1.5:
        text += f"* Risk/Reward ratio is only {rr_ratio}:1 (minimum 1.5 required).\n"
    if neg_reasons:
        for r in neg_reasons:
            text += f"* {r}\n"
    text += "\n**Therefore: WAIT.**"
    return text

def generate_markdown(ticker, profile, short_term, long_term, stock_news, global_news, final_score, action, rr_ratio):
    name = profile.get("name", ticker)
    sector = profile.get("sector", "N/A")
    company_desc = profile.get("description", "N/A")
    cp = short_term.get("current_price", "N/A")
    
    tech_score = short_term.get("quant_score", 0)
    reasons = short_term.get("quant_reasons", [])
    stock_news_list = stock_news.get('latest_news_headlines', [])
    news_sentiment, matched_words = analyze_news_sentiment(stock_news_list)
    
    sma_50 = short_term.get("sma_50", 0)
    sma_200 = long_term.get("moving_averages", {}).get("sma_200", 0)
    lt_trend = "BEARISH" if sma_50 < sma_200 else "BULLISH"
    
    if final_score >= 2: st_trend = "BULLISH"
    elif final_score <= -2: st_trend = "BEARISH"
    else: st_trend = "NEUTRAL / SIDEWAYS"
        
    if st_trend == "BULLISH" and lt_trend == "BEARISH": regime = "RECOVERY / MIXED"
    elif st_trend == "BEARISH" and lt_trend == "BULLISH": regime = "PULLBACK / WARNING"
    else: regime = lt_trend

    p6 = short_term.get('performance_windows', {}).get('6h', {})
    p12 = short_term.get('performance_windows', {}).get('12h', {})
    p24 = short_term.get('performance_windows', {}).get('24h', {})
    bc = short_term.get('background_calculations', {})
    rsi = bc.get('RSI_14', {})
    stoch_rsi = bc.get('Stoch_RSI', {})
    macd = bc.get('MACD', {})
    bb = bc.get('Bollinger_Bands', {})
    atr = bc.get('ATR', {})
    vwap = bc.get('VWAP', {})
    projections = short_term.get('time_projections', [])
    
    proj_str = ""
    seen_times = set()
    for p in projections:
        t = p.get('time', 'N/A')
        if t in seen_times: continue
        seen_times.add(t)
        p_min = p.get('min', 0)
        p_max = p.get('max', 0)
        central = round((p_min + p_max) / 2, 2) if p_min and p_max else "N/A"
        proj_str += f"* At **{t}**, the expected range is **₹{p_min} - ₹{p_max}** (Central estimate: ₹{central}).\n"
            
    targets = short_term.get('actionable_targets', {})
    entry = targets.get('entry', 0)
    stop = targets.get('stop_loss', 0)
    target_price = targets.get('target', 0)
    
    risk_per_share = round(entry - stop, 2) if entry and stop else 0
    reward_per_share = round(target_price - entry, 2) if entry and target_price else 0
    
    high_52w = long_term.get('52_week_high', 'N/A')
    low_52w = long_term.get('52_week_low', 'N/A')
    ma = long_term.get('moving_averages', {})
    sma_50_str = ma.get('sma_50', 'N/A')
    sma_200_str = ma.get('sma_200', 'N/A')
    if isinstance(sma_50_str, (int, float)) and isinstance(sma_200_str, (int, float)):
        dma_status = "the 50-day is above the 200-day, meaning the long-term trend is up" if sma_50_str > sma_200_str else "the 50-day is below the 200-day, meaning the long-term trend is down"
    else:
        dma_status = "data unavailable"
    fib = long_term.get('fibonacci_retracement', {})
    lt_targets = long_term.get('long_term_targets', {})
    lt_buy = lt_targets.get('buy_target', 'N/A')
    lt_sell = lt_targets.get('sell_target', 'N/A')
    
    beginner_guide = generate_beginner_guide(name, action, cp, entry, stop, target_price, lt_trend, lt_buy, lt_sell, final_score, rr_ratio)
    why_not_trade = generate_why_not_trade(action, reasons, rr_ratio)
    
    stock_news_str = "\n".join([f"- {n}" for n in stock_news_list])
    global_news_list = global_news.get('global_headlines', [])
    global_news_str = "\n".join([f"- {n}" for n in global_news_list])

    reasons_str = "\n".join([f"  - {r}" for r in reasons])
    sentiment_str = f"+{news_sentiment}" if news_sentiment > 0 else str(news_sentiment)

    return f"""**⏱️ Current Date & Time:** <span id="live-clock">Loading...</span>

**{name} ({ticker})**
*Sector:* {sector} | *Current Price:* ₹{cp} | *Action:* {action} |
*Company:* {company_desc}
[CHART:PRICE]

---

{beginner_guide}

---

### ⏱️ Where could the price be?
*Disclaimer: These are model-implied volatility ranges based on ATR, not exact predictions.*

{proj_str}

---

### 🎯 Trade Setup & Risk Management
*Levels derived from 14-day ATR volatility and Bollinger Band support/resistance.*
* **Action:** {action}
* **Entry (Buy):** ₹{entry}
* **Stop Loss:** ₹{stop} (Risk: ₹{risk_per_share}/share)
* **Target (Sell):** ₹{target_price} (Reward: ₹{reward_per_share}/share)
* **Risk/Reward Ratio:** {rr_ratio} : 1
* *Note: Do not trade if R:R is below 1.5.*

---

{why_not_trade}

---

### 📊 Signal & Market Regime
* **Short-Term Trend:** {st_trend}
* **Long-Term Regime:** {lt_trend}
* **Current Regime:** {regime}
* **Signal Score:** {final_score} (Tech: {tech_score} | News: {sentiment_str})

**Quantitative Reasons:**
{reasons_str}

---

### 🧮 Quantitative Evidence (Math Explained Simply)
* **VWAP (Volume Weighted Average Price):** ₹{vwap.get('value', 'N/A')} - (Formula: Sum of (Typical Price * Volume) / Sum of Volume). This is the average price weighted by volume today. If current price > VWAP, buyers are in control.
* **RSI (Relative Strength Index):** {rsi.get('value', 'N/A')} - (Formula: 100 - [100 / (1 + Avg Gain / Avg Loss)]). This compares how much the stock goes up vs down. If RSI > 70, it's too expensive. If < 30, it's too cheap.
[CHART:RSI]
* **Stoch RSI (Stochastic RSI):** {stoch_rsi.get('value', 'N/A')} - (Formula: (Current RSI - Lowest RSI) / (Highest RSI - Lowest RSI)). This shows if RSI is at the extreme end of its range.
[CHART:STOCH_RSI]
* **MACD (Moving Average Convergence Divergence):** {macd.get('macd_line', 'N/A')} vs {macd.get('signal_line', 'N/A')} - (Formula: 12-day EMA - 26-day EMA). This shows the difference between the 12-day and 26-day averages. If positive, the short-term average is higher.
[CHART:MACD]
* **Bollinger Bands:** Upper ₹{bb.get('upper_band', 'N/A')}, Lower ₹{bb.get('lower_band', 'N/A')} - (Formula: 20-day SMA +/- 2 Standard Deviations). These are lines that show where prices usually go. When price hits the top, it's high; when it hits the bottom, it's low.
* **ATR (Average True Range):** {atr.get('value', 'N/A')} - (Formula: Average of True Range over 14 days). This measures how much the stock price moves up and down in a day. Higher ATR means more movement.

**🕒 Last 24 Hours Performance:**
* **6H:** Changed by {p6.get('change_pct', 'N/A')}% (High ₹{p6.get('high', 'N/A')}, Low ₹{p6.get('low', 'N/A')})
* **12H:** Changed by {p12.get('change_pct', 'N/A')}% (High ₹{p12.get('high', 'N/A')}, Low ₹{p12.get('low', 'N/A')})
* **24H:** Changed by {p24.get('change_pct', 'N/A')}% (High ₹{p24.get('high', 'N/A')}, Low ₹{p24.get('low', 'N/A')})

---

### 🧮 Long Term Math (1 Year Data)
* **52-Week High:** ₹{high_52w} | **52-Week Low:** ₹{low_52w}
* **50-DMA & 200-DMA (Daily Moving Averages):** ₹{sma_50_str} & ₹{sma_200_str} - (Formula: Average price over 50 and 200 days). These are like 50-day and 200-day averages. If the 50-day is above the 200-day, the trend is up. If below, the trend is down. Here {dma_status}.
* **Fibonacci Levels:** 0% at ₹{fib.get('0%', 'N/A')}, 23.6% at ₹{fib.get('23.6%', 'N/A')}, 38.2% at ₹{fib.get('38.2%', 'N/A')}, 50% at ₹{fib.get('50%', 'N/A')}, 61.8% at ₹{fib.get('61.8%', 'N/A')}, 100% at ₹{fib.get('100%', 'N/A')}.
[CHART:LONG_TERM]

**Long Term Targets:**
* **Buy/Bid at:** ₹{lt_buy} (Based on nearest 1-year Fibonacci support level).
* **Sell at:** ₹{lt_sell} (Based on nearest 1-year Fibonacci resistance level for max profit).

---

### 📰 News & Events
**Global & Macro News (Events affecting all stocks):**
{global_news_str}

**Stock Specific News:**
{stock_news_str}

*⚠️ Disclaimer: Based on textbook technical math analysis, which historically wins only about 50-55% of the time.*
"""

async def process_data(ticker, stock_name, log_func=None):
    if log_func: await log_func("[SYSTEM] Initializing gAIn quant backend...")
    if log_func: await log_func(f"[INPUT] Ticker requested: {ticker}")
    
    if log_func: await log_func("[DATA] Step 1/6: Fetching Company Profile (NSE/Yahoo)...")
    profile = await asyncio.to_thread(ta_server.get_company_profile, ticker)
    if log_func: await log_func(f"  └─ Profile: {profile.get('name', 'N/A')} | Sector: {profile.get('sector', 'N/A')}")
    
    if log_func: await log_func("[DATA] Step 2/6: Fetching Live Price & 24h OHLCV data (5m interval)...")
    short_term = await asyncio.to_thread(ta_server.get_bid_ask_targets, ticker)
    if log_func:
        await log_func("[MATH] Step 2.1: Calculating Short Term Math...")
        bc = short_term.get('background_calculations', {})
        await log_func(f"  ├─ RSI (14): {bc.get('RSI_14', {}).get('value', 'N/A')} ({bc.get('RSI_14', {}).get('status', 'N/A')})")
        await log_func(f"  ├─ Stoch RSI: {bc.get('Stoch_RSI', {}).get('value', 'N/A')} ({bc.get('Stoch_RSI', {}).get('status', 'N/A')})")
        await log_func(f"  ├─ MACD: {bc.get('MACD', {}).get('macd_line', 'N/A')} vs Signal {bc.get('MACD', {}).get('signal_line', 'N/A')} ({bc.get('MACD', {}).get('momentum', 'N/A')})")
        await log_func(f"  ├─ VWAP: ₹{bc.get('VWAP', {}).get('value', 'N/A')} ({bc.get('VWAP', {}).get('status', 'N/A')})")
        await log_func(f"  ├─ Bollinger Bands: Upper ₹{bc.get('Bollinger_Bands', {}).get('upper_band', 'N/A')}, Lower ₹{bc.get('Bollinger_Bands', {}).get('lower_band', 'N/A')}")
        await log_func(f"  └─ ATR (14): {bc.get('ATR', {}).get('value', 'N/A')} ({bc.get('ATR', {}).get('interpretation', 'N/A')})")
        await log_func("[CHART] Step 2.2: Generating 24h Price, RSI, Stoch RSI, MACD Plotly graphs...")
    
    if log_func: await log_func("[DATA] Step 3/6: Fetching Long Term Data (1Y Daily candles)...")
    long_term = await asyncio.to_thread(ta_server.get_long_term_analysis, ticker)
    if log_func:
        await log_func("[MATH] Step 3.1: Calculating Long Term Math...")
        ma = long_term.get('moving_averages', {})
        await log_func(f"  ├─ 50-DMA: ₹{ma.get('sma_50', 'N/A')} | 200-DMA: ₹{ma.get('sma_200', 'N/A')} ({ma.get('cross_status', 'N/A')})")
        await log_func(f"  ├─ 52-Week High: ₹{long_term.get('52_week_high', 'N/A')} | Low: ₹{long_term.get('52_week_low', 'N/A')}")
        await log_func(f"  └─ Fibonacci Levels mapped.")
        await log_func("[CHART] Step 3.2: Generating 1-Year Price & DMA Plotly graph...")
    
    if log_func: await log_func("[NEWS] Step 4/6: Fetching Stock Specific News (Google + Yahoo)...")
    stock_news = await asyncio.to_thread(ta_server.get_indian_stock_news, ticker, stock_name)
    if log_func: await log_func(f"  └─ Found {len(stock_news.get('latest_news_headlines', []))} articles.")
        
    if log_func: await log_func("[NEWS] Step 5/6: Fetching Global Macro News (ET + Google)...")
    global_news = await asyncio.to_thread(ta_server.get_global_market_news)
    if log_func: await log_func(f"  └─ Found {len(global_news.get('global_headlines', []))} articles.")
    
    if log_func: await log_func("[QUANT] Step 6/6: Running Quant Engine & Risk Management...")
    tech_score = short_term.get("quant_score", 0)
    reasons = short_term.get("quant_reasons", [])
    stock_news_list = stock_news.get('latest_news_headlines', [])
    
    if log_func: await log_func("  ├─ Analyzing News Sentiment...")
    news_sentiment, matched_words = analyze_news_sentiment(stock_news_list)
    final_score = tech_score + news_sentiment
    if log_func: await log_func(f"  │  └─ Sentiment Score: {news_sentiment} (Matched: {', '.join(matched_words) if matched_words else 'None'})")
    
    targets = short_term.get('actionable_targets', {})
    entry = targets.get('entry', 0)
    stop = targets.get('stop_loss', 0)
    target_price = targets.get('target', 0)
    
    risk_per_share = entry - stop if entry and stop else 0
    reward_per_share = target_price - entry if entry and target_price else 0
    rr_ratio = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0
    
    action = determine_action(final_score, rr_ratio)
    if log_func: await log_func(f"  ├─ Technical Score: {tech_score}")
    if log_func: await log_func(f"  ├─ Final Signal Score: {final_score}")
    if log_func: await log_func(f"  ├─ Risk/Reward Ratio: {rr_ratio} : 1 (Entry: ₹{entry}, Stop: ₹{stop}, Target: ₹{target_price})")
    if log_func: await log_func(f"  └─ Final Action Determined: {action}")
    
    if log_func: await log_func("[SYSTEM] Generating plain-English guide & Markdown...")
    reply = generate_markdown(ticker, profile, short_term, long_term, stock_news, global_news, final_score, action, rr_ratio)
    
    if log_func: await log_func("[SYSTEM] Processing complete. Dispatching UI payload...")
    
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
            payload = await process_data(ticker, stock_name, log_func=None)
            return payload
        except Exception as e:
            return {"reply": f"Backend Error: {str(e)}", "short_chart_data": [], "long_chart_data": [], "targets": {}}