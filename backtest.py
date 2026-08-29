import os
import time
import requests
import ccxt
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 監控標的清單
TARGET_SYMBOLS = [
    'BTC', 'ETH', 'PAXG', 'TSM', 'MU', 'SPCX', 'CLU', 
    'GOOGL', 'SAMSUNG', 'NVDA', 'GLW', 'TSLA', 'AAPL', 
    'LAB', 'PLAY', 'AMZN'
]

TIMEFRAME = '15m'
FETCH_LIMIT = 800

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
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

def fetch_kline_safe(symbol_name):
    """直接調用公開 REST API，完全避開 451 封鎖"""
    pair = f"{symbol_name.upper()}USDT"
    url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={TIMEFRAME}&limit={FETCH_LIMIT}"
    
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) >= 50:
                df = pd.DataFrame(data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
                ])
                df['open'] = df['open'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                df['close'] = df['close'].astype(float)
                df['volume'] = df['volume'].astype(float)
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%m/%d %H:%M')
                return df
    except Exception:
        pass
    return None

def run_backtest():
    send_discord_alert("🧪 **[BACKTEST] 啟動無地域限制回測引擎...**")
    
    status_log = []
    all_trades = []

    for name in TARGET_SYMBOLS:
        # 特別代號轉換 (例如黃金對應 PAXG)
        query_sym = 'PAXG' if name == 'XAU' else name
        df = fetch_kline_safe(query_sym)
        
        if df is None or len(df) < 50:
            status_log.append(f"❌ {name:<8} : 公開現貨無 {query_sym}USDT")
            continue

        status_log.append(f"✅ {name:<8} : 成功載入 {len(df)} 根 15m K 線")
        df['rsi'] = calculate_rsi(df['close'], period=14)

        i = 35
        while i < len(df) - 1:
            sub_df = df.iloc[:i+1]
            swing_high = sub_df['high'][-30:].max()
            swing_low = sub_df['low'][-30:].min()
            wave_range = swing_high - swing_low

            if wave_range <= 0:
                i += 1
                continue

            fib_0618 = swing_high - (wave_range * 0.618)
            fib_0382 = swing_high - (wave_range * 0.382)

            candle = sub_df.iloc[-1]
            entry_price = candle['close']

            # 動態 Fib 多單條件
            in_fib_zone = (candle['low'] <= fib_0618 * 1.003) and (candle['close'] >= fib_0618 * 0.995)
            rsi_condition = candle['rsi'] <= 45
            lower_wick = min(candle['open'], candle['close']) - candle['low']
            body_size = abs(candle['close'] - candle['open'])
            rejection = (lower_wick >= body_size * 0.8) or (candle['close'] > candle['open'])

            if in_fib_zone and rsi_condition and rejection:
                stop_loss = min(candle['low'] * 0.998, swing_low * 0.999)
                tp_1 = fib_0382 if fib_0382 > entry_price else swing_high
                tp_2 = swing_high

                outcome = "HOLDING"
                bars_held = 0

                for j in range(i + 1, min(i + 49, len(df))):
                    future_bar = df.iloc[j]
                    bars_held += 1

                    if future_bar['low'] <= stop_loss:
                        outcome = "SL"
                        break
                    elif future_bar['high'] >= tp_2:
                        outcome = "TP2_FULL"
                        break
                    elif future_bar['high'] >= tp_1 and outcome != "TP1_HIT":
                        outcome = "TP1_HIT"

                all_trades.append({
                    'Symbol': name,
                    'Side': 'LONG',
                    'Time': candle['datetime'],
                    'Entry': entry_price,
                    'Result': outcome
                })

                i += max(bars_held, 2)
            else:
                i += 1
        time.sleep(0.1)

    # 1. 診斷推播
    status_msg = "🔍 **[標的數據載入狀態]**\n```text\n" + "\n".join(status_log) + "\n```"
    send_discord_alert(status_msg)

    # 2. 結果統計
    if not all_trades:
        send_discord_alert("📋 **[策略統計]** 本輪未產生交易訊號。")
        return

    res_df = pd.DataFrame(all_trades)
    total_trades = len(res_df)
    tp1_count = len(res_df[res_df['Result'].isin(['TP1_HIT', 'TP2_FULL'])])
    tp2_count = len(res_df[res_df['Result'] == 'TP2_FULL'])
    sl_count = len(res_df[res_df['Result'] == 'SL'])
    holding_count = len(res_df[res_df['Result'] == 'HOLDING'])
    win_rate = (tp1_count / total_trades) * 100 if total_trades > 0 else 0

    trade_details = ""
    for _, r in res_df.head(10).iterrows():
        trade_details += f"[{r['Time']}] {r['Symbol']} @ ${r['Entry']:.2f} -> {r['Result']}\n"

    report_msg = (
        f"📊 **[BACKTEST REPORT] 斐波那契回測結果 (15m)**\n"
        f"```text\n"
        f"總進場次數  : {total_trades} 次\n"
        f"TP1 達標勝率: {win_rate:.1f}% ({tp1_count}/{total_trades})\n"
        f"TP2 終極達標: {tp2_count} 次\n"
        f"SL 停損離場 : {sl_count} 次\n"
        f"持倉/未觸發 : {holding_count} 次\n"
        f"----------------------------------------\n"
        f"近期交易明細 (前10筆):\n"
        f"{trade_details}"
        f"```"
    )
    send_discord_alert(report_msg)

if __name__ == '__main__':
    run_backtest()
