import pandas as pd
import numpy as np
import logging
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - MCP_SERVER - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


price_cache = {}  
realtime_cache = {}  

def fetch_rss_feed(url, source_name, search_term=None):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    items = []
    try:
        response = requests.get(url, headers=headers, timeout=5)
        root = ET.fromstring(response.content)
        for item in root.findall('.//item'):
            title = item.find('title').text if item.find('title') is not None else "No Title"
            link = item.find('link').text if item.find('link') is not None else ""
            pub_date_str = item.find('pubDate').text if item.find('pubDate') is not None else ""
            
 
            if not pub_date_str:
                dc_date = item.find('{http://purl.org/dc/elements/1.1/}date')
                if dc_date is not None: pub_date_str = dc_date.text

            if pub_date_str:
                try:
        
                    dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z").astimezone(IST)
                except:
                    try:
                   
                        dt = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00')).astimezone(IST)
                    except:
                        continue
            else:
                continue

          
            if search_term:
                if search_term.lower() not in title.lower():
                    continue

            items.append({
                "title": f"{title} ({source_name})",
                "link": link,
                "date": dt.strftime("%d %b %Y, %H:%M"),
                "timestamp": dt.timestamp()
            })
    except Exception as e:
        pass
    return items

def fetch_yahoo_direct(ticker, interval="5m", range="5d"):
    cache_key = f"{ticker}_{interval}_{range}"
    if cache_key in price_cache and time.time() - price_cache[cache_key]["time"] < 15:
        return price_cache[cache_key]["data"], "Success (Cached)"
        
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200: return pd.DataFrame(), f"Yahoo API returned {res.status_code}"
        data = res.json()
        if "chart" not in data or "result" not in data["chart"] or not data["chart"]["result"]:
            return pd.DataFrame(), "Invalid data format"
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        indicators = result.get("indicators", {}).get("quote", [{}])[0]
        df = pd.DataFrame({
            'datetime': [datetime.fromtimestamp(ts, tz=IST) for ts in timestamps],
            'Open': indicators.get("open", []),
            'High': indicators.get("high", []),
            'Low': indicators.get("low", []),
            'Close': indicators.get("close", []),
            'Volume': indicators.get("volume", [])
        })
        df.dropna(inplace=True)
        df.set_index('datetime', inplace=True)
        price_cache[cache_key] = {"data": df, "time": time.time()}
        return df, "Success"
    except Exception as e:
        return pd.DataFrame(), f"Yahoo fetch exception: {str(e)}"

def fetch_realtime_price(ticker: str) -> float:
    cache_key = f"{ticker}_rt"
    if cache_key in realtime_cache and time.time() - realtime_cache[cache_key]["time"] < 5:
        return realtime_cache[cache_key]["data"]
        
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    live_price = None

    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        res = requests.get(url, headers=headers, timeout=5).json()
        if res.get("chart", {}).get("result"):
            live_price = res["chart"]["result"][0]["meta"].get("regularMarketPrice")
    except: pass

    try:
        stooq_symbol = ticker.replace(".NS", ".in").replace(".BO", ".bo").lower()
        if ticker == "^NSEI": stooq_symbol = "^nsi"
        elif ticker == "^BSESN": stooq_symbol = "^sen"
        elif ticker == "^NSEBANK": stooq_symbol = "^bnse"
        
        url = f"https://stooq.com/q/l/?s={stooq_symbol}&f=sd2t2ohlcv&h&e=csv"
        res = requests.get(url, headers=headers, timeout=5)
        lines = res.text.strip().split('\n')
        if len(lines) > 1:
            parts = lines[1].split(',')
            if len(parts) > 6:
                try:
                    stooq_price = float(parts[6])
                    if stooq_price != 0: live_price = stooq_price
                except ValueError: pass
    except: pass

    if live_price:
        realtime_cache[cache_key] = {"data": live_price, "time": time.time()}
    return live_price

def get_company_profile(ticker: str) -> dict:
    symbol = ticker.replace(".NS", "").replace(".BO", "").upper()
    if ticker.startswith("^"):
        name = "Nifty 50" if ticker == "^NSEI" else "Sensex" if ticker == "^BSESN" else "Bank Nifty" if ticker == "^NSEBANK" else "Market Index"
        return {"name": name, "sector": "Market Index", "industry": "Market Index", "description": f"{name} is a benchmark index of the Indian stock market."}

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        res = session.get(url, headers=headers, timeout=5).json()
        if "metadata" in res:
            meta = res.get("metadata", {}); info = res.get("info", {})
            return {"name": meta.get("companyName", "N/A"), "sector": meta.get("industry", "N/A"), "industry": meta.get("industry", "N/A"), "description": f"{info.get('corpName', symbol)} is listed on the National Stock Exchange of India."}
    except: pass
        
    try:
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=assetProfile"
        res = requests.get(url, headers=headers, timeout=5).json()
        profile = res.get("quoteSummary", {}).get("result", [{}])[0].get("assetProfile", {})
        return {"name": symbol, "sector": profile.get("sector", "N/A"), "industry": profile.get("industry", "N/A"), "description": profile.get("longBusinessSummary", "Company listed on the National Stock Exchange of India.")[:150] + "..."}
    except Exception as e:
        return {"error": f"Profile fetch failed: {str(e)}"}

def calculate_quant_score(hist, current_price, latest, vwap_val, sma_50, sma_200):
    score = 0
    reasons = []
    
    if current_price > vwap_val: score += 1; reasons.append("Price > VWAP (Buyers in control)")
    else: score -= 1; reasons.append("Price < VWAP (Sellers in control)")
        
    if latest['MACD'] > latest['Signal']: score += 1; reasons.append("MACD Bullish Cross")
    else: score -= 1; reasons.append("MACD Bearish Cross")
        
    if 40 <= latest['RSI'] <= 70: score += 1; reasons.append("RSI in Bull Zone (40-70)")
    elif latest['RSI'] < 30: score += 2; reasons.append("RSI Oversold (<30 - Bounce Expected)")
    elif latest['RSI'] > 80: score -= 2; reasons.append("RSI Overbought (>80 - Dump Expected)")
    else: score -= 1; reasons.append("RSI in Bear Zone (30-40)")
        
    if current_price > sma_50: score += 1; reasons.append("Price > 50-DMA (Uptrend)")
    else: score -= 1; reasons.append("Price < 50-DMA (Downtrend)")
        
    if sma_50 > sma_200: score += 1; reasons.append("Golden Cross (50-DMA > 200-DMA)")
    else: score -= 1; reasons.append("Death Cross (50-DMA < 200-DMA)")
        
    avg_vol = hist['Volume'].rolling(window=20).mean().iloc[-1]
    if latest['Volume'] > avg_vol * 1.5: score += 1; reasons.append("Volume Breakout (>1.5x Avg Volume)")
    elif latest['Volume'] < avg_vol * 0.5: score -= 1; reasons.append("Volume Dry Up (<0.5x Avg Volume)")
        
    if current_price > latest['BBU']: score -= 1; reasons.append("Price broke Upper Bollinger Band (Overextended)")
    elif current_price < latest['BBL']: score += 1; reasons.append("Price broke Lower Bollinger Band (Reversal Due)")

    if score >= 5: signal = "STRONG BUY"
    elif score >= 2: signal = "BUY"
    elif score >= -1: signal = "HOLD / NEUTRAL"
    elif score >= -4: signal = "SELL"
    else: signal = "STRONG SELL"
        
    return score, signal, reasons

def get_bid_ask_targets(ticker: str) -> dict:
    try:
        hist, err_msg = fetch_yahoo_direct(ticker, interval="5m", range="5d")
        if hist.empty: return {"error": f"Data fetch failed: {err_msg}"}
        
        live_price = fetch_realtime_price(ticker)
        current_price = live_price if live_price else float(hist['Close'].iloc[-1])
        
        def get_stats(df, hours):
            rows = hours * 12
            if len(df) < rows: rows = len(df)
            window = df.tail(rows)
            start_price = float(window['Close'].iloc[0])
            change_pct = ((current_price - start_price) / start_price) * 100
            return {"start_price": round(start_price, 2), "high": round(float(window['High'].max()), 2), "low": round(float(window['Low'].min()), 2), "change_pct": round(change_pct, 2)}
            
        stats_6h = get_stats(hist, 6); stats_12h = get_stats(hist, 12); stats_24h = get_stats(hist, 24)
        
        hist['SMA_20'] = hist['Close'].rolling(window=20).mean()
        hist['STD_20'] = hist['Close'].rolling(window=20).std()
        hist['BBL'] = hist['SMA_20'] - (hist['STD_20'] * 2)
        hist['BBU'] = hist['SMA_20'] + (hist['STD_20'] * 2)
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        hist['RSI'] = 100 - (100 / (1 + rs))
        rsi_min = hist['RSI'].rolling(window=14).min()
        rsi_max = hist['RSI'].rolling(window=14).max()
        hist['Stoch_RSI'] = (hist['RSI'] - rsi_min) / (rsi_max - rsi_min)
        hist['EMA_12'] = hist['Close'].ewm(span=12, adjust=False).mean()
        hist['EMA_26'] = hist['Close'].ewm(span=26, adjust=False).mean()
        hist['MACD'] = hist['EMA_12'] - hist['EMA_26']
        hist['Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
        tr = pd.concat([hist['High'] - hist['Low'], abs(hist['High'] - hist['Close'].shift()), abs(hist['Low'] - hist['Close'].shift())], axis=1).max(axis=1)
        hist['ATR'] = tr.rolling(window=14).mean()
        
        hist['Typical_Price'] = (hist['High'] + hist['Low'] + hist['Close']) / 3
        hist['TP_Vol'] = hist['Typical_Price'] * hist['Volume']
        hist['Date'] = hist.index.date
        hist['Cum_TP_Vol'] = hist.groupby('Date')['TP_Vol'].cumsum()
        hist['Cum_Vol'] = hist.groupby('Date')['Volume'].cumsum()
        hist['VWAP'] = hist['Cum_TP_Vol'] / hist['Cum_Vol'].replace(0, np.nan)
        
        latest = hist.iloc[-1]
        atr_val = float(latest['ATR']) if not np.isnan(latest['ATR']) else current_price * 0.02
        vwap_val = float(latest['VWAP']) if not np.isnan(latest['VWAP']) else current_price
        
        sma_50 = float(hist['Close'].rolling(50).mean().iloc[-1]) if len(hist) >= 50 else current_price
        sma_200 = float(hist['Close'].rolling(200).mean().iloc[-1]) if len(hist) >= 200 else current_price
        
        quant_score, signal, reasons = calculate_quant_score(hist, current_price, latest, vwap_val, sma_50, sma_200)
        
        low_24h = stats_24h.get('low', current_price * 0.98)
        high_24h = stats_24h.get('high', current_price * 1.02)
        
        entry_price = max(float(hist['BBL'].iloc[-1]), low_24h)
        target_price = min(float(hist['BBU'].iloc[-1]), high_24h)
        
        if entry_price >= target_price:
            entry_price = current_price * 0.98
            target_price = current_price * 1.02
            
        stop_loss = entry_price - (atr_val * 1.5)
        
        now_ist = datetime.now(IST)
        close_time = now_ist.replace(hour=15, minute=15, second=0, microsecond=0)
        macd_momentum = float(latest['MACD']) - float(latest['Signal'])
        
        bias_multiplier = (quant_score / 8.0)
        projections = []
        for h in [1, 2, 3]:
            proj_time = now_ist + timedelta(hours=h)
            if proj_time > close_time: proj_time = close_time
            vol_factor = 0.5 if h == 1 else 1.0 if h == 2 else 1.5
            p_max = current_price + (atr_val * vol_factor * max(0.2, 1 + bias_multiplier))
            p_min = current_price - (atr_val * vol_factor * max(0.2, 1 - bias_multiplier))
            projections.append({"time": proj_time.strftime("%I:%M %p"), "max": round(p_max, 2), "min": round(p_min, 2)})
            
        hours_to_close = (close_time - now_ist).total_seconds() / 3600.0
        if hours_to_close > 0:
            close_max = current_price + (atr_val * hours_to_close * max(0.2, 1 + bias_multiplier))
            close_min = current_price - (atr_val * hours_to_close * max(0.2, 1 - bias_multiplier))
            projections.append({"time": "MARKET CLOSE", "max": round(close_max, 2), "min": round(close_min, 2)})
            
        unique_projections = []
        seen_times = set()
        for p in projections:
            if p['time'] not in seen_times:
                unique_projections.append(p)
                seen_times.add(p['time'])
        
        chart_data = [{"time": idx.strftime('%Y-%m-%d %H:%M'), "price": round(float(row['Close']), 2), "upper_band": round(float(row['BBU']), 2) if not np.isnan(row['BBU']) else None, "lower_band": round(float(row['BBL']), 2) if not np.isnan(row['BBL']) else None, "vwap": round(float(row['VWAP']), 2) if not np.isnan(row['VWAP']) else None, "rsi": round(float(row['RSI']), 2) if not np.isnan(row['RSI']) else None, "stoch_rsi": round(float(row['Stoch_RSI']), 2) if not np.isnan(row['Stoch_RSI']) else None, "macd": round(float(row['MACD']), 4) if not np.isnan(row['MACD']) else None, "signal": round(float(row['Signal']), 4) if not np.isnan(row['Signal']) else None} for idx, row in hist.tail(24*12).iterrows()]
        
        return {
            "current_price": round(current_price, 2),
            "trend": signal,
            "quant_score": quant_score,
            "quant_reasons": reasons,
            "sma_50": round(sma_50, 2),
            "sma_200": round(sma_200, 2),
            "performance_windows": {"6h": stats_6h, "12h": stats_12h, "24h": stats_24h},
            "background_calculations": {
                "RSI_14": {"value": round(float(latest['RSI']), 2), "status": "Overbought (>70)" if latest['RSI'] > 70 else "Oversold (<30)" if latest['RSI'] < 30 else "Neutral"},
                "Stoch_RSI": {"value": round(float(latest['Stoch_RSI']), 2), "status": "Overbought (>0.8)" if latest['Stoch_RSI'] > 0.8 else "Oversold (<0.2)" if latest['Stoch_RSI'] < 0.2 else "Neutral"},
                "MACD": {"macd_line": round(float(latest['MACD']), 4), "signal_line": round(float(latest['Signal']), 4), "momentum": "Bullish" if latest['MACD'] > latest['Signal'] else "Bearish"},
                "Bollinger_Bands": {"upper_band": round(float(latest['BBU']), 2), "lower_band": round(float(latest['BBL']), 2)},
                "ATR": {"value": round(atr_val, 2), "interpretation": "High volatility" if atr_val > (current_price * 0.02) else "Low volatility"},
                "VWAP": {"value": round(vwap_val, 2), "status": "Buyers in control" if current_price > vwap_val else "Sellers in control"}
            },
            "time_projections": unique_projections,
            "actionable_targets": {"entry": round(entry_price, 2), "target": round(target_price, 2), "stop_loss": round(stop_loss, 2)},
            "chart_data": chart_data
        }
    except Exception as e:
        return {"error": str(e)}

def get_long_term_analysis(ticker: str) -> dict:
    try:
        hist, err_msg = fetch_yahoo_direct(ticker, interval="1d", range="1y")
        if hist.empty: return {"error": f"Data fetch failed: {err_msg}"}
        current_price = float(hist['Close'].iloc[-1])
        hist['SMA_50'] = hist['Close'].rolling(window=50).mean()
        hist['SMA_200'] = hist['Close'].rolling(window=200).mean()
        high_52w = float(hist['High'].max()); low_52w = float(hist['Low'].min())
        diff = high_52w - low_52w
        fib_levels = {"0%": round(high_52w, 2), "23.6%": round(high_52w - diff * 0.236, 2), "38.2%": round(high_52w - diff * 0.382, 2), "50%": round(high_52w - diff * 0.5, 2), "61.8%": round(high_52w - diff * 0.618, 2), "100%": round(low_52w, 2)}
        latest = hist.iloc[-1]
        sma_50 = float(latest['SMA_50']) if not np.isnan(latest['SMA_50']) else current_price
        sma_200 = float(latest['SMA_200']) if not np.isnan(latest['SMA_200']) else current_price
        
        fib_vals = list(fib_levels.values())
        lt_buy = low_52w
        for val in sorted(fib_vals, reverse=True):
            if val < current_price: lt_buy = val; break
        lt_sell = high_52w
        for val in sorted(fib_vals):
            if val > current_price: lt_sell = val; break
                
        chart_data = [{"time": idx.strftime('%Y-%m-%d'), "price": round(float(row['Close']), 2), "sma_50": round(float(row['SMA_50']), 2) if not np.isnan(row['SMA_50']) else None, "sma_200": round(float(row['SMA_200']), 2) if not np.isnan(row['SMA_200']) else None} for idx, row in hist.iterrows()]
        return {"current_price": round(current_price, 2), "52_week_high": round(high_52w, 2), "52_week_low": round(low_52w, 2), "moving_averages": {"sma_50": round(sma_50, 2), "sma_200": round(sma_200, 2)}, "fibonacci_retracement": fib_levels, "long_term_targets": {"buy_target": lt_buy, "sell_target": lt_sell}, "long_term_chart_data": chart_data}
    except Exception as e:
        return {"error": str(e)}

def get_indian_stock_news(ticker: str, stock_name: str) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    news_items = []

    try:
        clean_name = stock_name.replace("Limited", "").replace("Ltd", "").strip()
        query = quote(f"{clean_name} stock news India")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        news_items.extend(fetch_rss_feed(url, "Google News"))
    except: pass

    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={ticker}&newsCount=15&lang=en-IN&region=IN"
        res = requests.get(url, headers=headers, timeout=10).json()
        for article in res.get("news", []):
            title = article.get("title", "No Title")
            link = article.get("link", "")
            pub_date_str = article.get("providerPublishTime", "")
            if pub_date_str:
                dt = datetime.fromtimestamp(pub_date_str, tz=IST)
                news_items.append({"title": f"{title} (Yahoo Finance)", "link": link, "date": dt.strftime("%d %b %Y, %H:%M"), "timestamp": dt.timestamp()})
    except: pass

    
    clean_name = stock_name.replace("Limited", "").replace("Ltd", "").strip()
    rss_feeds_stock = [
        ("https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "Economic Times"),
        ("https://www.moneycontrol.com/rss/markets.xml", "Moneycontrol"),
        ("https://www.livemint.com/rss/markets", "Livemint"),
        ("https://www.business-standard.com/rss/markets-106.rss", "Business Standard")
    ]
    for feed_url, source in rss_feeds_stock:
        news_items.extend(fetch_rss_feed(feed_url, source, search_term=clean_name))

    news_items.sort(key=lambda x: x['timestamp'], reverse=True)
    headlines = [{"text": f"[{item['date']}] {item['title']}", "url": item['link']} for item in news_items[:25]]
    result = {"latest_news_headlines": headlines} if headlines else {"news": "No recent news found."}
    return result

def get_global_market_news() -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    news_items = []

    try:
        query = quote("war OR economy OR inflation OR oil prices OR RBI OR \"Federal Reserve\" stock market")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        news_items.extend(fetch_rss_feed(url, "Google News"))
    except: pass

    rss_feeds_global = [
        ("https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "Economic Times"),
        ("https://www.moneycontrol.com/rss/markets.xml", "Moneycontrol"),
        ("https://www.livemint.com/rss/markets", "Livemint"),
        ("https://www.business-standard.com/rss/markets-106.rss", "Business Standard")
    ]
    for feed_url, source in rss_feeds_global:
        news_items.extend(fetch_rss_feed(feed_url, source))

    news_items.sort(key=lambda x: x['timestamp'], reverse=True)
    headlines = [{"text": f"[{item['date']}] {item['title']}", "url": item['link']} for item in news_items[:25]]
    result = {"global_headlines": headlines} if headlines else {"news": "No recent news found."}
    return result