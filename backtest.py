import os
import time
import requests
import urllib.parse
import pandas as pd
import numpy as np
import yfinance as yf

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 18 檔標的完整配置（全面 USD / USDT 計價）
SYMBOL_CONFIG = {
    # 1. 幣安主流與中文幣 (USDT)
    'BTC': {'type': 'binance', 'pair': 'BTCUSDT', 'curr': 'USDT'},
    'ETH': {'type': 'binance', 'pair': 'ETHUSDT', 'curr': 'USDT'},
    'XAU': {'type': 'binance', 'pair': 'PAXGUSDT', 'curr': 'USDT'},
    '币安人生': {'type': 'binance', 'pair': '币安人生USDT', 'curr': 'USDT'},

    # 2. 鏈上迷因幣 (GeckoTerminal 15m DEX, USD)
    'PLAY': {'type': 'dex', 'network': 'base', 'pool': '0x853a7c99227499dba9db8c3a02aa691afdebf841', 'curr': 'USD'},
    'LAB': {'type': 'dex', 'network': 'bsc', 'pool': '0xd9434e63fe78a6e77dafe2abc504121bf8500822f6d3a59eccba577cf0a070f2', 'curr': 'USD'},

    # 3. 美股與商品期貨 (Yahoo Finance 15m, USD)
    'TSM': {'type': 'stock', 'ticker': 'TSM', 'curr': 'USD'},
    'NVDA': {'type': 'stock', 'ticker': 'NVDA', 'curr': 'USD'},
    'TSLA': {'type': 'stock', 'ticker': 'TSLA', 'curr': 'USD'},
    'AAPL': {'type': 'stock', 'ticker': 'AAPL', 'curr': 'USD'},
    'GOOGL': {'type': 'stock', 'ticker': 'GOOGL', 'curr': 'USD'},
    'MU': {'type': 'stock', 'ticker': 'MU', 'curr': 'USD'},
    'AMZN': {'type': 'stock', 'ticker': 'AMZN', 'curr': 'USD'},
    'GLW': {'type': 'stock', 'ticker': 'GLW', 'curr': 'USD'},
    'SPCX': {'type': 'stock', 'ticker': 'SPCX', 'curr': 'USD'},
    'CLU': {'type': 'stock', 'ticker': 'CL=F', 'curr': 'USD'},
    'SNDK': {'type': 'stock', 'ticker': 'SNDK', 'curr': 'USD'}
}

TIMEFRAME = '15m'
FETCH_LIMIT = 500
BINANCE_MIRROR = "https://data-api.binance.vision/api/v3/klines"

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        print(content)
        return
    try:
        if len(content) > 1900:
            chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
            for chunk in chunks:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=10)
                time.sleep(0.5)
        else:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    except Exception as err:
        print("推播失敗:", err)

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))

def get_kline_df(cfg):
    """依照配置抓取 15m K 線並統一輸出 DataFrame"""
    t = cfg['type']
    
    if t == 'binance':
        encoded_pair = urllib.parse.quote(cfg['pair'])
        url = f"{BINANCE_MIRROR}?symbol={encoded_pair}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
        try:
            res = requests.get(url, timeout=8)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) >= 50:
                    df = pd.DataFrame(data, columns=[
                        'timestamp', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
                    ])
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        df[col] = df[col].astype(float)
                    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%m/%d %H:%M')
                    return df
        except Exception:
            pass

    elif t == 'dex':
        headers = {"Accept": "application/json;version=20230302"}
        target_addr = cfg['pool']
        network = cfg['network']
        
        # 1. 嘗試直接調用 pool
        url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{target_addr}/ohlcv/minute?aggregate=15&limit={FETCH_LIMIT}"
        try:
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                ohlcv = res.json().get('data', {}).get('attributes', {}).get('ohlcv_list', [])
                if ohlcv and len(ohlcv) >= 30:
                    ohlcv.reverse()
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        df[col] = df[col].astype(float)
                    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s').dt.strftime('%m/%d %H:%M')
                    return df
        except Exception:
            pass

        # 2. 備援：透過 Token 地址自動搜尋 Top 1 活躍池
        search_url = f"https://api.geckoterminal.com/api/v2/networks/{network}/tokens/{target_addr}/pools"
        try:
            s_res = requests.get(search_url, headers=headers, timeout=8)
            if s_res.status_code == 200:
                pools = s_res.json().get('data', [])
                if pools:
                    best_pool = pools[0]['attributes']['address']
                    sub_url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{best_pool}/ohlcv/minute?aggregate=15&limit={FETCH_LIMIT}"
                    sub_res = requests.get(sub_url, headers=headers, timeout=8)
                    if sub_res.status_code == 200:
                        ohlcv = sub_res.json().get('data', {}).get('attributes', {}).get('ohlcv_list', [])
                        if ohlcv and len(ohlcv) >= 30:
                            ohlcv.reverse()
                            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                            for col in ['open', 'high', 'low', 'close', 'volume']:
                                df[col] = df[col].astype(float)
                            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s').dt.strftime('%m/%d %H:%M')
                            return df
        except Exception:
            pass

    elif t == 'stock':
        try:
            df = yf.download(cfg['ticker'], period="5d", interval="15m", progress=False)
            if not df.empty and len(df) >= 50:
                df = df.reset_index()
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0].lower() for c in df.columns]
                else:
                    df.columns = [c.lower() for c in df.columns]
                
                time_col = 'datetime' if 'datetime' in df.columns else 'date'
                df['datetime'] = pd.to_datetime(df[time_col]).dt.strftime('%m/%d %H:%M')
                return df[['datetime', 'open', 'high', 'low', 'close', 'volume']]
        except Exception:
            pass

    return None

def backtest_strategy(name, cfg):
    df = get_kline_df(cfg)
    if df is None or len(df) < 50:
        return f"❌ {name:<8} : 數據抓取失敗", []

    # 技術指標：RSI, EMA 50, EMA 200
    df['rsi'] = calculate_rsi(df['close'], period=14)
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    trades = []
    i = 35
    while i < len(df) - 1:
        sub = df.iloc[i-25:i+1]
        sw_high = sub['high'].max()
        sw_low = sub['low'].min()
        wave = sw_high - sw_low

        if wave <= 0 or (wave / sw_low) < 0.003:
            i += 1
            continue

        candle = df.iloc[i]
        entry_price = candle['close']

        fib_0618_long = sw_high - (wave * 0.618)
        fib_0382_long = sw_high - (wave * 0.382)
        fib_0618_short = sw_low + (wave * 0.618)
        fib_0382_short = sw_low + (wave * 0.382)

        body_size = abs(candle['close'] - candle['open'])
        lower_wick = min(candle['open'], candle['close']) - candle['low']
        upper_wick = candle['high'] - max(candle['open'], candle['close'])

        trade_side = None
        stop_loss = 0
        tp1 = 0
        tp2 = 0

        # 大趨勢判定 (EMA 50)
        trend_bullish = candle['close'] >= candle['ema50']
        trend_bearish = candle['close'] <= candle['ema50']

        # 🟢 多單進場：順勢多頭 + 回踩 0.618 支撐 + 右側下影線反彈或收陽 + RSI 適中
        rejection_long = (lower_wick >= body_size * 0.6) or (candle['close'] > candle['open'])
        if trend_bullish and (candle['low'] <= fib_0618_long * 1.002) and (candle['close'] >= sw_low) and rejection_long and (candle['rsi'] <= 50):
            trade_side = "LONG"
            stop_loss = sw_low * 0.997
            tp1 = fib_0382_long
            tp2 = sw_high

        # 🔴 空單進場：順勢空頭 + 反彈 0.618 阻力 + 右側上影線受阻或收陰 + RSI 適中
        rejection_short = (upper_wick >= body_size * 0.6) or (candle['close'] < candle['open'])
        if trend_bearish and (candle['high'] >= fib_0618_short * 0.998) and (candle['close'] <= sw_high) and rejection_short and (candle['rsi'] >= 50):
            trade_side = "SHORT"
            stop_loss = sw_high * 1.003
            tp1 = fib_0382_short
            tp2 = sw_low

        if trade_side:
            outcome = "HOLDING"
            bars_held = 0

            for j in range(i + 1, min(i + 33, len(df))):
                fbar = df.iloc[j]
                bars_held += 1

                if trade_side == "LONG":
                    if fbar['low'] <= stop_loss:
                        outcome = "SL"
                        break
                    elif fbar['high'] >= tp2:
                        outcome = "TP2_FULL"
                        break
                    elif fbar['high'] >= tp1 and outcome != "TP1_HIT":
                        outcome = "TP1_HIT"
                else:
                    if fbar['high'] >= stop_loss:
                        outcome = "SL"
                        break
                    elif fbar['low'] <= tp2:
                        outcome = "TP2_FULL"
                        break
                    elif fbar['low'] <= tp1 and outcome != "TP1_HIT":
                        outcome = "TP1_HIT"

            trades.append({
                'Symbol': name,
                'Side': trade_side,
                'Time': candle['datetime'],
                'Entry': entry_price,
                'Result': outcome,
                'Curr': cfg['curr']
            })

            i += max(bars_held, 3)
        else:
            i += 1

    status_msg = f"✅ {name:<8} [{cfg['type']:<7}] : 載入 {len(df):3d} 根 K 線 | 觸發 {len(trades):2d} 次交易"
    return status_msg, trades

def main():
    send_discord_alert("🧪 **[進階趨勢回測] 啟動 EMA 趨勢 ＋ 右側確認斐波那契回測...**")
    
    status_log = []
    all_trades = []

    for name, cfg in SYMBOL_CONFIG.items():
        log_line, trades = backtest_strategy(name, cfg)
        status_log.append(log_line)
        all_trades.extend(trades)
        time.sleep(0.1)

    # 1. 輸出各標的狀態總覽
    status_summary = "📋 **[標的數據與進階訊號總覽]**\n```text\n" + "\n".join(status_log) + "\n```"
    send_discord_alert(status_summary)

    # 2. 統計回測數據
    if not all_trades:
        send_discord_alert("📊 **[回測結果]** 本週期內無符合趨勢過濾條件之進場點。")
        return

    res_df = pd.DataFrame(all_trades)
    total_trades = len(res_df)
    long_trades = len(res_df[res_df['Side'] == 'LONG'])
    short_trades = len(res_df[res_df['Side'] == 'SHORT'])

    tp1_count = len(res_df[res_df['Result'].isin(['TP1_HIT', 'TP2_FULL'])])
    tp2_count = len(res_df[res_df['Result'] == 'TP2_FULL'])
    sl_count = len(res_df[res_df['Result'] == 'SL'])
    holding_count = len(res_df[res_df['Result'] == 'HOLDING'])
    win_rate = (tp1_count / total_trades) * 100 if total_trades > 0 else 0

    trade_details = ""
    for _, r in res_df.head(10).iterrows():
        p_str = f"${r['Entry']:.4f}" if r['Entry'] < 1 else f"${r['Entry']:.2f}"
        trade_details += f"[{r['Time']}] {r['Side']:<5} {r['Symbol']:<8} @ {p_str} {r['Curr']} -> {r['Result']}\n"

    report_msg = (
        f"📊 **[BACKTEST REPORT] 斐波那契進階趨勢回測報告 (15m)**\n"
        f"```text\n"
        f"總進場次數  : {total_trades} 次 (多單: {long_trades} / 空單: {short_trades})\n"
        f"TP1 達標勝率: {win_rate:.1f}% ({tp1_count}/{total_trades})\n"
        f"TP2 終極達標: {tp2_count} 次\n"
        f"SL 停損離場 : {sl_count} 次\n"
        f"持倉中/未結 : {holding_count} 次\n"
        f"----------------------------------------\n"
        f"近期交易明細 (前 10 筆):\n"
        f"{trade_details}"
        f"```"
    )
    send_discord_alert(report_msg)
    print("=== 回測完成 ===")

if __name__ == '__main__':
    main()
