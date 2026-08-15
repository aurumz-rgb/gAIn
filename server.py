import pandas as pd
import numpy as np
import logging
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
import time
from io import StringIO

logging.basicConfig(level=logging.INFO, format='%(asctime)s - MCP_SERVER - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

price_cache = {}  
realtime_cache = {}  

def fetch_rss_feed(url, source_name, search_term=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://news.google.com/'
    }
    items = []
    try:
        response = requests.get(url, headers=headers, timeout=10)
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
    cache_time = 5 if interval == "5m" else 3600
    if cache_key in price_cache and time.time() - price_cache[cache_key]["time"] < cache_time:
        return price_cache[cache_key]["data"], "Success (Cached)"
        
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range}&interval={interval}&includeAdjustedClose=true"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://finance.yahoo.com/',
        'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Upgrade-Insecure-Requests': '1',
        'Connection': 'keep-alive'
    }
    try:
        res = requests.get(url, headers=headers, timeout=15)
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
        if not df.empty:
            price_cache[cache_key] = {"data": df, "time": time.time()}
        return df, "Success"
    except Exception as e:
        return pd.DataFrame(), f"Yahoo fetch exception: {str(e)}"

def fetch_stooq_daily(ticker, years=5):
    stooq_symbol = ticker.replace(".NS", ".in").replace(".BO", ".bo").lower()
    if ticker == "^NSEI": stooq_symbol = "^nsi"
    elif ticker == "^BSESN": stooq_symbol = "^sen"
    elif ticker == "^NSEBANK": stooq_symbol = "^bnse"
    
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=years*365)).strftime("%Y%m%d")
    
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&d1={start_date}&d2={end_date}&i=d"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://stooq.com/'
    }
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200: return pd.DataFrame(), f"Stooq API returned {res.status_code}"
        if "No data" in res.text: return pd.DataFrame(), "Stooq returned no data"
        df = pd.read_csv(StringIO(res.text))
        if df.empty: return pd.DataFrame(), "Stooq returned empty CSV"
        
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        df.index = df.index.tz_localize('UTC').tz_convert(IST)
        
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(inplace=True)
        return df, "Success (Stooq)"
    except Exception as e:
        return pd.DataFrame(), f"Stooq fetch exception: {str(e)}"

def fetch_realtime_price(ticker: str):
    cache_key = f"{ticker}_rt"
    if cache_key in realtime_cache and time.time() - realtime_cache[cache_key]["time"] < 2:
        return realtime_cache[cache_key]["data"], realtime_cache[cache_key]["source"], realtime_cache[cache_key]["fetch_time"]
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://finance.yahoo.com/'
    }
    live_price = None
    source = "Unknown"
    fetch_time = time.time()

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        res = requests.get(url, headers=headers, timeout=5).json()
        if res.get("chart", {}).get("result"):
            live_price = res["chart"]["result"][0]["meta"].get("regularMarketPrice")
            source = "Yahoo"
    except: pass

    if not live_price:
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
                        if stooq_price != 0: 
                            live_price = stooq_price
                            source = "Stooq"
                    except ValueError: pass
        except: pass

    if live_price:
        realtime_cache[cache_key] = {"data": live_price, "time": fetch_time, "source": source, "fetch_time": fetch_time}
        
    return live_price, source, fetch_time

def get_company_profile(ticker: str) -> dict:
    symbol = ticker.replace(".NS", "").replace(".BO", "").upper()
    if ticker.startswith("^"):
        name = "Nifty 50" if ticker == "^NSEI" else "Sensex" if ticker == "^BSESN" else "Bank Nifty" if ticker == "^NSEBANK" else "Market Index"
        return {"name": name, "sector": "Market Index", "industry": "Market Index", "description": f"{name} is a benchmark index of the Indian stock market."}

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.nseindia.com/'
    }
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

def get_fundamentals_and_events(ticker: str):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://finance.yahoo.com/'
    }
    fundamentals = {"pe": "N/A", "pb": "N/A", "roe": "N/A", "de": "N/A"}
    earnings_risk = False
    
    try:
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=summaryDetail,financialData,calendarEvents"
        res = requests.get(url, headers=headers, timeout=5).json()
        result = res.get("quoteSummary", {}).get("result", [{}])[0]
        
        summary = result.get("summaryDetail", {})
        financials = result.get("financialData", {})
        calendar = result.get("calendarEvents", {})
        
        fundamentals['pe'] = summary.get('trailingPE', {}).get('raw', 'N/A')
        fundamentals['pb'] = summary.get('priceToBook', {}).get('raw', 'N/A')
        fundamentals['roe'] = round(financials.get('returnOnEquity', {}).get('raw', 0) * 100, 2) if 'returnOnEquity' in financials else 'N/A'
        fundamentals['de'] = financials.get('debtToEquity', {}).get('raw', 'N/A')
        
        if calendar.get('earnings'):
            earn_date = calendar['earnings'].get('earningsDate', [{}])[0].get('raw')
            if earn_date:
                earn_dt = datetime.fromtimestamp(earn_date, tz=IST)
                days_until = (earn_dt - datetime.now(IST)).total_seconds() / 86400
                if 0 <= days_until <= 3:
                    earnings_risk = True
    except:
        pass
        

    if fundamentals['pe'] == "N/A" and not ticker.startswith("^"):
        try:
            symbol = ticker.replace(".NS", "").replace(".BO", "").upper()
            session = requests.Session()
            nse_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Referer': 'https://www.nseindia.com/'
            }
            session.get("https://www.nseindia.com", headers=nse_headers, timeout=5)
            url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
            res = session.get(url, headers=nse_headers, timeout=5).json()
            if "metadata" in res:
                meta = res.get("metadata", {})
                fundamentals['pe'] = round(meta.get('pdToPeMultiple', 0), 2) if meta.get('pdToPeMultiple') else "N/A"
                fundamentals['pb'] = round(meta.get('pbPerShare', 0), 2) if meta.get('pbPerShare') else "N/A"
                fundamentals['roe'] = round(meta.get('returnOnEquity', 0), 2) if meta.get('returnOnEquity') else "N/A"
                fundamentals['de'] = round(meta.get('debtToEquity', 0), 2) if meta.get('debtToEquity') else "N/A"
        except:
            pass
        
    return fundamentals, earnings_risk

def calculate_quant_score(hist, current_price, latest, vwap_val, daily_sma_50, daily_sma_200):
    score = 0
    reasons = []
    
    if current_price > vwap_val: score += 1; reasons.append("Price > VWAP (Intraday buyers have advantage)")
    else: score -= 1; reasons.append("Price < VWAP (Intraday sellers have advantage)")
        
    if latest['MACD'] > latest['Signal']: score += 1; reasons.append("MACD Bullish Cross")
    else: score -= 1; reasons.append("MACD Bearish Cross")
        
    if 40 <= latest['RSI'] <= 70: score += 1; reasons.append("RSI in Bull Zone (40-70)")
    elif latest['RSI'] < 30: score += 2; reasons.append("RSI Oversold (<30)")
    elif latest['RSI'] > 70: score -= 1; reasons.append("RSI Overbought (>70)")
    else: score -= 1; reasons.append("RSI in Bear Zone (30-40)")
        
    if daily_sma_50 > 0:
        if current_price > daily_sma_50: score += 1; reasons.append("Price > 50-DMA (Uptrend)")
        else: score -= 1; reasons.append("Price < 50-DMA (Downtrend)")
        
    if daily_sma_50 > 0 and daily_sma_200 > 0:
        if daily_sma_50 > daily_sma_200: score += 1; reasons.append("Golden Cross (50-DMA > 200-DMA)")
        else: score -= 1; reasons.append("Death Cross (50-DMA < 200-DMA)")
        
    avg_vol = hist['Volume'].rolling(window=20).mean().iloc[-1]
    if latest['Volume'] > avg_vol * 1.5: score += 1; reasons.append("Volume Spike (>1.5x Avg)")
    elif latest['Volume'] < avg_vol * 0.5: score -= 1; reasons.append("Low Volume (<0.5x Avg)")

    if score >= 5: signal = "STRONG BUY"
    elif score >= 2: signal = "BUY"
    elif score >= -1: signal = "HOLD / NEUTRAL"
    elif score >= -4: signal = "SELL"
    else: signal = "STRONG SELL"
        
    return score, signal, reasons

def get_bid_ask_targets(ticker: str, daily_sma_50: float = 0, daily_sma_200: float = 0, daily_atr_percentile: float = 0) -> dict:
    try:

        hist_5m, err_msg = fetch_yahoo_direct(ticker, interval="5m", range="5d")
        if hist_5m.empty: return {"error": f"5m Data fetch failed: {err_msg}"}
        
       
        hist_1d, err_msg_1d = fetch_yahoo_direct(ticker, interval="1d", range="1y")
        if hist_1d.empty:
            hist_1d, err_msg_1d = fetch_stooq_daily(ticker, years=1)
            if hist_1d.empty: return {"error": f"1d Data fetch failed: {err_msg_1d}"}
            
        live_price, src, fetch_ts = fetch_realtime_price(ticker)
        current_price = live_price if live_price else float(hist_5m['Close'].iloc[-1])
        

        def get_stats(df, hours):
            rows = hours * 12
            if len(df) < rows: rows = len(df)
            window = df.tail(rows)
            start_price = float(window['Close'].iloc[0])
            change_pct = ((current_price - start_price) / start_price) * 100
            return {"start_price": round(start_price, 2), "high": round(float(window['High'].max()), 2), "low": round(float(window['Low'].min()), 2), "change_pct": round(change_pct, 2)}
            
        stats_6h = get_stats(hist_5m, 6); stats_12h = get_stats(hist_5m, 12); stats_24h = get_stats(hist_5m, 24)
        

        hist_5m['SMA_20'] = hist_5m['Close'].rolling(window=20).mean()
        hist_5m['STD_20'] = hist_5m['Close'].rolling(window=20).std()
        hist_5m['BBL_5m'] = hist_5m['SMA_20'] - (hist_5m['STD_20'] * 2)
        hist_5m['BBU_5m'] = hist_5m['SMA_20'] + (hist_5m['STD_20'] * 2)
        
        delta = hist_5m['Close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
        rs = avg_gain / avg_loss
        hist_5m['RSI'] = 100 - (100 / (1 + rs))
        
        rsi_min = hist_5m['RSI'].rolling(window=14).min()
        rsi_max = hist_5m['RSI'].rolling(window=14).max()
        hist_5m['Stoch_RSI'] = (hist_5m['RSI'] - rsi_min) / (rsi_max - rsi_min)
        hist_5m['EMA_12'] = hist_5m['Close'].ewm(span=12, adjust=False).mean()
        hist_5m['EMA_26'] = hist_5m['Close'].ewm(span=26, adjust=False).mean()
        hist_5m['MACD'] = hist_5m['EMA_12'] - hist_5m['EMA_26']
        hist_5m['Signal'] = hist_5m['MACD'].ewm(span=9, adjust=False).mean()
        
        tr_5m = pd.concat([hist_5m['High'] - hist_5m['Low'], abs(hist_5m['High'] - hist_5m['Close'].shift()), abs(hist_5m['Low'] - hist_5m['Close'].shift())], axis=1).max(axis=1)
        hist_5m['ATR_5m'] = tr_5m.ewm(alpha=1/14, adjust=False).mean()
        

        hist_5m['UpMove'] = hist_5m['High'].diff()
        hist_5m['DownMove'] = -hist_5m['Low'].diff()
        hist_5m['+DM'] = np.where((hist_5m['UpMove'] > hist_5m['DownMove']) & (hist_5m['UpMove'] > 0), hist_5m['UpMove'], 0.0)
        hist_5m['-DM'] = np.where((hist_5m['DownMove'] > hist_5m['UpMove']) & (hist_5m['DownMove'] > 0), hist_5m['DownMove'], 0.0)
        safe_atr_5m = hist_5m['ATR_5m'].replace(0, np.nan)
        hist_5m['+DI'] = 100 * (hist_5m['+DM'].ewm(alpha=1/14, adjust=False).mean() / safe_atr_5m)
        hist_5m['-DI'] = 100 * (hist_5m['-DM'].ewm(alpha=1/14, adjust=False).mean() / safe_atr_5m)
        di_sum = (hist_5m['+DI'] + hist_5m['-DI']).replace(0, np.nan)
        hist_5m['DX'] = 100 * abs(hist_5m['+DI'] - hist_5m['-DI']) / di_sum
        hist_5m['ADX'] = hist_5m['DX'].ewm(alpha=1/14, adjust=False).mean()
        hist_5m['ADX'].replace([np.inf, -np.inf], 0, inplace=True)
        hist_5m['ADX'].fillna(0, inplace=True)
        
        hist_5m['Typical_Price'] = (hist_5m['High'] + hist_5m['Low'] + hist_5m['Close']) / 3
        hist_5m['TP_Vol'] = hist_5m['Typical_Price'] * hist_5m['Volume']
        hist_5m['Date'] = hist_5m.index.date
        hist_5m['Cum_TP_Vol'] = hist_5m.groupby('Date')['TP_Vol'].cumsum()
        hist_5m['Cum_Vol'] = hist_5m.groupby('Date')['Volume'].cumsum()
        hist_5m['VWAP'] = hist_5m['Cum_TP_Vol'] / hist_5m['Cum_Vol'].replace(0, np.nan)
        
        latest_5m = hist_5m.iloc[-1]
        vwap_val = float(latest_5m['VWAP']) if not np.isnan(latest_5m['VWAP']) else current_price
        adx_val = float(latest_5m['ADX']) if not np.isnan(latest_5m['ADX']) else 0
        
        
        hist_1d['SMA_20'] = hist_1d['Close'].rolling(window=20).mean()
        hist_1d['STD_20'] = hist_1d['Close'].rolling(window=20).std()
        hist_1d['BBL'] = hist_1d['SMA_20'] - (hist_1d['STD_20'] * 2)
        hist_1d['BBU'] = hist_1d['SMA_20'] + (hist_1d['STD_20'] * 2)
        
        tr_1d = pd.concat([hist_1d['High'] - hist_1d['Low'], abs(hist_1d['High'] - hist_1d['Close'].shift()), abs(hist_1d['Low'] - hist_1d['Close'].shift())], axis=1).max(axis=1)
        hist_1d['ATR'] = tr_1d.ewm(alpha=1/14, adjust=False).mean()
        
        latest_1d = hist_1d.iloc[-1]
        daily_bbl = float(latest_1d['BBL']) if not np.isnan(latest_1d['BBL']) else current_price * 0.98
        daily_bbu = float(latest_1d['BBU']) if not np.isnan(latest_1d['BBU']) else current_price * 1.02
        daily_atr = float(latest_1d['ATR']) if not np.isnan(latest_1d['ATR']) else current_price * 0.02
        
 
        sma_50 = daily_sma_50 if daily_sma_50 > 0 else 0
        sma_200 = daily_sma_200 if daily_sma_200 > 0 else 0
        
        quant_score, signal, reasons = calculate_quant_score(hist_5m, current_price, latest_5m, vwap_val, sma_50, sma_200)
        
    
        low_24h = stats_24h.get('low', current_price * 0.98)
        high_24h = stats_24h.get('high', current_price * 1.02)
        
        if sma_50 > 0 and sma_200 > 0:
            trend_is_bullish = sma_50 > sma_200
        else:
            trend_is_bullish = current_price > float(hist_1d['SMA_20'].iloc[-1])
        
        if trend_is_bullish:
            entry_price = max(daily_bbl, low_24h)
            target_price = min(daily_bbu, high_24h)
            if entry_price >= target_price:
                entry_price = current_price * 0.98
                target_price = current_price * 1.02
            stop_loss = entry_price - (daily_atr * 1.5)
            direction = "LONG"
        else:
            entry_price = min(daily_bbu, high_24h)
            target_price = max(daily_bbl, low_24h)
            if entry_price <= target_price:
                entry_price = current_price * 1.02
                target_price = current_price * 0.98
            stop_loss = entry_price + (daily_atr * 1.5)
            direction = "SHORT"
        
        now_ist = datetime.now(IST)
        close_time = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        
        
        projections = []
        if now_ist < close_time:
            total_trading_hours = 6.25 # 9:15 AM to 3:30 PM
            hours_to_close = (close_time - now_ist).total_seconds() / 3600.0
            
            if hours_to_close > 1.0:
                t1 = now_ist + timedelta(hours=1)
                vol_factor_1h = (1.0 / total_trading_hours) 
                bias = (quant_score / 8.0) 
                p_max_1h = current_price + (daily_atr * vol_factor_1h * max(0.5, 1 + bias))
                p_min_1h = current_price - (daily_atr * vol_factor_1h * max(0.5, 1 - bias))
                projections.append({"time": t1.strftime("%I:%M %p"), "max": round(p_max_1h, 2), "min": round(p_min_1h, 2)})
                
            vol_factor_close = hours_to_close / total_trading_hours
            p_max_close = current_price + (daily_atr * vol_factor_close * max(0.5, 1 + bias))
            p_min_close = current_price - (daily_atr * vol_factor_close * max(0.5, 1 - bias))
            projections.append({"time": "MARKET CLOSE", "max": round(p_max_close, 2), "min": round(p_min_close, 2)})
            
        unique_projections = []
        seen_times = set()
        for p in projections:
            if p['time'] not in seen_times:
                unique_projections.append(p)
                seen_times.add(p['time'])
        
        chart_data = [{"time": idx.strftime('%Y-%m-%d %H:%M'), "price": round(float(row['Close']), 2), "upper_band": round(float(row['BBU_5m']), 2) if not np.isnan(row['BBU_5m']) else None, "lower_band": round(float(row['BBL_5m']), 2) if not np.isnan(row['BBL_5m']) else None, "vwap": round(float(row['VWAP']), 2) if not np.isnan(row['VWAP']) else None, "rsi": round(float(row['RSI']), 2) if not np.isnan(row['RSI']) else None, "stoch_rsi": round(float(row['Stoch_RSI']), 2) if not np.isnan(row['Stoch_RSI']) else None, "macd": round(float(row['MACD']), 4) if not np.isnan(row['MACD']) else None, "signal": round(float(row['Signal']), 4) if not np.isnan(row['Signal']) else None} for idx, row in hist_5m.tail(24*12).iterrows()]
        
        data_age = time.time() - fetch_ts
        
        return {
            "current_price": round(current_price, 2),
            "trend": signal,
            "quant_score": quant_score,
            "quant_reasons": reasons,
            "sma_50": round(sma_50, 2),
            "sma_200": round(sma_200, 2),
            "performance_windows": {"6h": stats_6h, "12h": stats_12h, "24h": stats_24h},
            "background_calculations": {
                "RSI_14": {"value": round(float(latest_5m['RSI']), 2), "status": "Overbought (>70)" if latest_5m['RSI'] > 70 else "Oversold (<30)" if latest_5m['RSI'] < 30 else "Neutral"},
                "Stoch_RSI": {"value": round(float(latest_5m['Stoch_RSI']), 2), "status": "Overbought (>0.8)" if latest_5m['Stoch_RSI'] > 0.8 else "Oversold (<0.2)" if latest_5m['Stoch_RSI'] < 0.2 else "Neutral"},
                "MACD": {"macd_line": round(float(latest_5m['MACD']), 4), "signal_line": round(float(latest_5m['Signal']), 4), "momentum": "Bullish" if latest_5m['MACD'] > latest_5m['Signal'] else "Bearish"},
    
                "Bollinger_Bands": {"upper_band": round(daily_bbu, 2), "lower_band": round(daily_bbl, 2)},
                "ATR": {"value": round(daily_atr, 2), "interpretation": "High volatility" if daily_atr > (current_price * 0.02) else "Low volatility", "percentile": round(daily_atr_percentile, 1)},
                "VWAP": {"value": round(vwap_val, 2), "status": "Intraday buyers have advantage" if current_price > vwap_val else "Intraday sellers have advantage"},
                "ADX": {"value": round(adx_val, 2), "status": "Trending" if adx_val > 25 else "Sideways"}
            },
            "time_projections": unique_projections,
            "actionable_targets": {
                "entry": round(entry_price, 2), 
                "target": round(target_price, 2), 
                "stop_loss": round(stop_loss, 2),
                "direction": direction
            },
            "chart_data": chart_data,
            "data_source": src,
            "data_age_seconds": round(data_age, 1)
        }
    except Exception as e:
        return {"error": str(e)}

def run_rolling_oos_backtest(hist):
    def calc_estimated_trading_costs(entry_p, exit_p):
        turnover = entry_p + exit_p
        brokerage = 0 
        stt = (entry_p * 0.001) + (exit_p * 0.001) 
        exchange_txn = turnover * 0.0000335
        gst = (brokerage + exchange_txn) * 0.18
        sebi = turnover * 0.000001
        stamp_duty = entry_p * 0.00015 
        slippage = turnover * 0.0005 
        return brokerage + stt + exchange_txn + gst + sebi + stamp_duty + slippage

    hist['BBL_prev'] = hist['BBL'].shift(1)
    hist['BBU_prev'] = hist['BBU'].shift(1)
    hist['ATR_prev'] = hist['ATR'].shift(1)
    hist['SMA_50_prev'] = hist['SMA_50'].shift(1)
    hist['SMA_200_prev'] = hist['SMA_200'].shift(1)
    
    def process_chunk(df, atr_mult=1.5):
        trades = []
        in_trade = False
        entry_idx = -1
        entry_price = 0.0
        stop_price = 0.0
        target_price = 0.0
        direction = ""
        max_hold = 20 
        
        for i in range(200, len(df)):
            if in_trade:
                row = df.iloc[i]
                hit_stop = False
                hit_target = False
                timeout = (i - entry_idx) >= max_hold
                exit_price = 0.0
                
                if direction == "LONG":
                    if row['Low'] <= stop_price and row['High'] >= target_price:
                        exit_price, hit_stop = stop_price, True
                    elif row['Open'] <= stop_price:
                        exit_price, hit_stop = row['Open'], True
                    elif row['Open'] >= target_price:
                        exit_price, hit_target = row['Open'], True
                    elif row['Low'] <= stop_price:
                        exit_price, hit_stop = stop_price, True
                    elif row['High'] >= target_price:
                        exit_price, hit_target = target_price, True
                elif direction == "SHORT":
                    if row['High'] >= stop_price and row['Low'] <= target_price:
                        exit_price, hit_stop = stop_price, True
                    elif row['Open'] >= stop_price:
                        exit_price, hit_stop = row['Open'], True
                    elif row['Open'] <= target_price:
                        exit_price, hit_target = row['Open'], True
                    elif row['High'] >= stop_price:
                        exit_price, hit_stop = stop_price, True
                    elif row['Low'] <= target_price:
                        exit_price, hit_target = target_price, True
                        
                if timeout and not hit_stop and not hit_target:
                    exit_price = row['Close']
                    
                if hit_stop or hit_target or timeout:
                    costs = calc_estimated_trading_costs(entry_price, exit_price)
                    if direction == "LONG":
                        pnl = (exit_price - entry_price) - costs
                        risk = entry_price - stop_price
                    else: 
                        pnl = (entry_price - exit_price) - costs
                        risk = stop_price - entry_price
                        
                    trades.append({
                        "type": direction,
                        "pnl_r": pnl / risk if risk > 0 else 0,
                        "hit_target": hit_target,
                        "hit_stop": hit_stop,
                        "date": row.name
                    })
                    in_trade = False
                    
            if not in_trade:
                row = df.iloc[i]
                if row['SMA_50_prev'] > row['SMA_200_prev']:
                    if row['Low'] <= row['BBL_prev'] or row['Open'] <= row['BBL_prev']:
                        entry_price = row['Open'] if row['Open'] <= row['BBL_prev'] else row['BBL_prev']
                        stop_price = entry_price - (row['ATR_prev'] * atr_mult)
                        target_price = row['BBU_prev']
                        if stop_price >= entry_price or target_price <= entry_price: continue
                        in_trade, entry_idx, direction = True, i, "LONG"
                        
                elif row['SMA_50_prev'] < row['SMA_200_prev']:
                    if row['High'] >= row['BBU_prev'] or row['Open'] >= row['BBU_prev']:
                        entry_price = row['Open'] if row['Open'] >= row['BBU_prev'] else row['BBU_prev']
                        stop_price = entry_price + (row['ATR_prev'] * atr_mult)
                        target_price = row['BBL_prev']
                        if stop_price <= entry_price or target_price >= entry_price: continue
                        in_trade, entry_idx, direction = True, i, "SHORT"
                        
        return trades


    train_window = min(252 * 5, int(len(hist) * 0.7))
    test_window = min(252, int(len(hist) * 0.3))
    
    oos_trades_15 = []
    oos_trades_10 = []
    oos_trades_20 = []
    
   
    if train_window >= 252 and test_window >= 126:
        start_idx = 0
        while start_idx + train_window + test_window <= len(hist):
            test_df = hist.iloc[start_idx + train_window : start_idx + train_window + test_window]
            oos_trades_15.extend(process_chunk(test_df, atr_mult=1.5))
            oos_trades_10.extend(process_chunk(test_df, atr_mult=1.0))
            oos_trades_20.extend(process_chunk(test_df, atr_mult=2.0))
            start_idx += test_window
    
    elif len(hist) > 200:
        oos_trades_15 = process_chunk(hist, atr_mult=1.5)
        oos_trades_10 = process_chunk(hist, atr_mult=1.0)
        oos_trades_20 = process_chunk(hist, atr_mult=2.0)

    def calc_metrics(trades_list, daily_df):
        if not trades_list: return {}
        wins = [t for t in trades_list if t['pnl_r'] > 0]
        losses = [t for t in trades_list if t['pnl_r'] <= 0]
        gross_profit = sum(t['pnl_r'] for t in wins)
        gross_loss = abs(sum(t['pnl_r'] for t in losses))
        
        win_rate = round((len(wins) / len(trades_list) * 100), 2)
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0
        expectancy = round(np.mean([t['pnl_r'] for t in trades_list]), 2)
        
        peak, max_dd, curr = 0, 0, 0
        for t in trades_list:
            curr += t['pnl_r']
            if curr > peak: peak = curr
            dd = peak - curr
            if dd > max_dd: max_dd = dd
            
        capital = 1000000
        equity_curve = [capital]
        dates = [trades_list[0]['date'] - timedelta(days=1)]
        for t in trades_list:
            risk_amt = capital * 0.01
            pnl_rupees = risk_amt * t['pnl_r']
            capital += pnl_rupees
            equity_curve.append(capital)
            dates.append(t['date'])
            
        eq_df = pd.DataFrame({'Date': dates, 'Equity': equity_curve}).set_index('Date')
        
        first_date = trades_list[0]['date']
        last_date = trades_list[-1]['date']
        years = (last_date - first_date).days / 365.25
        if years > 0 and equity_curve[-1] > 0:
            cagr = round(((equity_curve[-1] / 1000000) ** (1/years) - 1) * 100, 2)
        else:
            cagr = 0
            
        daily_eq = eq_df.resample('D').last().ffill()
        daily_rets = daily_eq.pct_change().dropna()
        if len(daily_rets) > 1 and daily_rets.std() > 0:
            sharpe = round((daily_rets.mean() / daily_rets.std()) * np.sqrt(252), 2)
            downside_rets = daily_rets[daily_rets < 0]
            if downside_rets.std() > 0:
                sortino = round((daily_rets.mean() / downside_rets.std()) * np.sqrt(252), 2)
            else:
                sortino = 0
        else:
            sharpe = 0
            sortino = 0
            
        period_daily = daily_df.loc[first_date:last_date]
        if len(period_daily) > 0:
            bh_return = round((period_daily['Close'].iloc[-1] / period_daily['Close'].iloc[0] - 1) * 100, 2)
        else:
            bh_return = 0
            
        pnls = [t['pnl_r'] for t in trades_list]
        exp_boot = []
        mc_dds = []
        if len(pnls) >= 30:
            for _ in range(5000):
                sim_trades = np.random.choice(pnls, len(pnls), replace=True)
                exp_boot.append(np.mean(sim_trades))
                sim_curr, sim_peak, sim_max_dd = 0, 0, 0
                for r in sim_trades:
                    sim_curr += r
                    if sim_curr > sim_peak: sim_peak = sim_curr
                    sim_dd = sim_peak - sim_curr
                    if sim_dd > sim_max_dd: sim_max_dd = sim_dd
                mc_dds.append(sim_max_dd)
                
            exp_ci_low = round(np.percentile(exp_boot, 2.5), 2)
            exp_ci_high = round(np.percentile(exp_boot, 97.5), 2)
            mc_dd_95 = round(np.percentile(mc_dds, 95), 2)
            
            from math import sqrt
            n = len(pnls)
            p = win_rate / 100
            z = 1.96
            denom = 1 + z**2/n
            center = (p + z**2/(2*n)) / denom
            margin = (z * sqrt((p*(1-p) + z**2/(4*n))/n)) / denom
            wr_ci_low = round(max(0, (center - margin) * 100), 2)
            wr_ci_high = round(min(100, (center + margin) * 100), 2)
        else:
            exp_ci_low, exp_ci_high, mc_dd_95, wr_ci_low, wr_ci_high = 0, 0, 0, 0, 0
            
        long_trades = [t for t in trades_list if t['type'] == "LONG"]
        short_trades = [t for t in trades_list if t['type'] == "SHORT"]
        long_win = round((len([t for t in long_trades if t['pnl_r'] > 0]) / len(long_trades) * 100)) if long_trades else 0
        short_win = round((len([t for t in short_trades if t['pnl_r'] > 0]) / len(short_trades) * 100)) if short_trades else 0
        
        return {
            "total_trades": len(trades_list),
            "win_rate": win_rate,
            "win_rate_ci_low": wr_ci_low,
            "win_rate_ci_high": wr_ci_high,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "exp_ci_low": exp_ci_low,
            "exp_ci_high": exp_ci_high,
            "max_dd": round(max_dd, 2),
            "mc_dd_95": mc_dd_95,
            "cagr": cagr,
            "benchmark_return": bh_return,
            "sharpe": sharpe,
            "sortino": sortino,
            "long_trades": len(long_trades),
            "long_win_rate": long_win,
            "short_trades": len(short_trades),
            "short_win_rate": short_win
        }

    robustness = "FRAGILE"
    if len(oos_trades_15) >= 30:
        pf_15 = calc_metrics(oos_trades_15, hist).get('profit_factor', 0)
        pf_10 = calc_metrics(oos_trades_10, hist).get('profit_factor', 0)
        pf_20 = calc_metrics(oos_trades_20, hist).get('profit_factor', 0)
        if pf_15 > 1.0 and pf_10 > 1.0 and pf_20 > 1.0:
            robustness = "ROBUST"
            
    final_metrics = calc_metrics(oos_trades_15, hist)
    final_metrics['robustness'] = robustness
    
    return {"rolling_oos": final_metrics}

def get_long_term_analysis(ticker: str) -> dict:
    try:
        hist = pd.DataFrame()
        err_msg = "No data source available"
        

        hist, err_msg = fetch_yahoo_direct(ticker, interval="1d", range="2y")
        
     
        if hist.empty:
            hist, err_msg = fetch_stooq_daily(ticker, years=10)
            
        if hist.empty: 
            return {"error": f"Data fetch failed: {err_msg}", "history_days": 0}
        
        current_price = float(hist['Close'].iloc[-1])
        hist['SMA_50'] = hist['Close'].rolling(window=50).mean()
        hist['SMA_200'] = hist['Close'].rolling(window=200).mean()
        hist['SMA_20'] = hist['Close'].rolling(window=20).mean()
        hist['STD_20'] = hist['Close'].rolling(window=20).std()
        hist['BBL'] = hist['SMA_20'] - (hist['STD_20'] * 2)
        hist['BBU'] = hist['SMA_20'] + (hist['STD_20'] * 2)
        
        tr = pd.concat([hist['High'] - hist['Low'], abs(hist['High'] - hist['Close'].shift()), abs(hist['Low'] - hist['Close'].shift())], axis=1).max(axis=1)
        hist['ATR'] = tr.ewm(alpha=1/14, adjust=False).mean()
        
        daily_atr_percentile = 0
        if len(hist) >= 90:
            daily_atr_percentile = float(hist['ATR'].tail(90).rank(pct=True).iloc[-1] * 100)
        
        high_52w = float(hist['High'].tail(252).max()) if len(hist) >= 252 else float(hist['High'].max())
        low_52w = float(hist['Low'].tail(252).min()) if len(hist) >= 252 else float(hist['Low'].min())
        
        diff = high_52w - low_52w
        fib_levels = {"0%": round(high_52w, 2), "23.6%": round(high_52w - diff * 0.236, 2), "38.2%": round(high_52w - diff * 0.382, 2), "50%": round(high_52w - diff * 0.5, 2), "61.8%": round(high_52w - diff * 0.618, 2), "100%": round(low_52w, 2)}
        latest = hist.iloc[-1]
        sma_50 = float(latest['SMA_50']) if not np.isnan(latest['SMA_50']) else 0
        sma_200 = float(latest['SMA_200']) if not np.isnan(latest['SMA_200']) else 0
        
        backtest_data = run_rolling_oos_backtest(hist)
        
        fib_vals = list(fib_levels.values())
        lt_buy = low_52w
        for val in sorted(fib_vals, reverse=True):
            if val < current_price: lt_buy = val; break
        lt_sell = high_52w
        for val in sorted(fib_vals):
            if val > current_price: lt_sell = val; break
                
        chart_data = [{"time": idx.strftime('%Y-%m-%d'), "price": round(float(row['Close']), 2), "sma_50": round(float(row['SMA_50']), 2) if not np.isnan(row['SMA_50']) else None, "sma_200": round(float(row['SMA_200']), 2) if not np.isnan(row['SMA_200']) else None} for idx, row in hist.iterrows()]
        return {
            "current_price": round(current_price, 2), 
            "52_week_high": round(high_52w, 2), 
            "52_week_low": round(low_52w, 2), 
            "moving_averages": {"sma_50": round(sma_50, 2), "sma_200": round(sma_200, 2)}, 
            "fibonacci_retracement": fib_levels, 
            "long_term_targets": {"buy_target": lt_buy, "sell_target": lt_sell}, 
            "long_term_chart_data": chart_data,
            "atr_percentile": daily_atr_percentile,
            "history_days": len(hist),
            "backtest": backtest_data
        }
    except Exception as e:
        return {"error": str(e), "history_days": 0}

def get_indian_stock_news(ticker: str, stock_name: str) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://news.google.com/'
    }
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
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://news.google.com/'
    }
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