import os
import time
import requests
import ccxt
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 17 檔指定監控標的 (涵蓋加密貨幣、美股合約、原油 CLU 與黃金 XAU)
TARGET_SYMBOLS = [
    'BTC', 'ETH', 'XAU', 'TSM', 'MU', 'SPCX', 'CLU', 
    'GOOGL', 'SAMSUNG', 'NVDA', 'GLW', 'TSLA', 'AAPL', 
    'LAB', 'PLAY', 'AMZN', '币安人生'
]

TIMEFRAME = '15m'
FETCH_LIMIT = 800

def send_discord_alert(content):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
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

def resolve_symbol_and_fetch(exchange, raw_name):
    """
    動態配對各類資產的 API 代號：
    - XAU -> PAXG/USDT 或 XAU/USDT
    - CLU -> CL/USDT, CLU/USDT (原油)
    - 美股/加密貨幣合約 -> 標準 USDT:USDT 格式
    """
    candidates = []
    
    if raw_name.upper() == 'XAU':
        candidates = ['PAXG/USDT:USDT', 'PAXG/USDT', 'XAU/USDT:USDT', 'XAUUSDT']
    elif raw_name.upper() == 'CLU':
        candidates = ['CLU/USDT:USDT', 'CL/USDT:USDT', 'OIL/USDT:USDT', 'CLU/USDT', 'CLUUSDT']
    else:
        candidates = [
            f"{raw_name}/USDT:USDT",
            f"{raw_name}/USDT",
            f"{raw_name}USDT",
            f"1000{raw_name}/USDT:USDT"
        ]

    for sym in candidates:
        try:
            ohlcv = exchange.fetch_ohlcv(sym, TIMEFRAME, limit=FETCH_LIMIT)
            if ohlcv and len(ohlcv) >= 60:
                return sym, ohlcv
        except Exception:
            continue
            
    return None, None

def run_backtest_on_symbol(exchange, raw_name):
    symbol, ohlcv = resolve_symbol_and_fetch(exchange, raw_name)
    records = []
    
    if not ohlcv:
        print(f"⚠️ 標的 [{raw_name}] 嘗試多種格式仍未取得數據，已跳過。")
        return records

    display_name = raw_name.upper()
    print(f"✅ 成功載入 [{display_name}] (API 代號: {symbol})，共 {len(ohlcv)} 根 K 線，開始運算...")

    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%m/%d %H:%M')
    df['rsi'] = calculate_rsi(df['close'], period=14)

    i = 25
    while i < len(df) - 1:
        sub = df.iloc[i-20:i+1]
        
        sw_high = sub['high'].max()
        sw_low = sub['low'].min()
        wave = sw_high - sw_low

        if wave <= 0 or (wave / sw_low) < 0.004:
            i += 1
            continue

        candle = df.iloc[i]
        entry_price = candle['close']

        # 斐波那契關鍵點位 (0.618 / 0.382)
        fib_long_0618 = sw_high - (wave * 0.618)
        fib_short_0618 = sw_low + (wave * 0.618)
        fib_long_0382 = sw_high - (wave * 0.382)
        fib_short_0382 = sw_low + (wave * 0.382)

        trade_side = None
        stop_loss = 0
        tp_1 = 0
        tp_2 = 0

        # 多單：觸及 0.618 支撐區間
        if candle['low'] <= fib_long_0618 * 1.002 and candle['close'] >= sw_low:
            trade_side = "LONG"
            stop_loss = sw_low * 0.997
            tp_1 = fib_long_0382
            tp_2 = sw_high

        # 空單：觸及 0.618 阻力區間
        elif candle['high'] >= fib_short_0618 * 0.998 and candle['close'] <= sw_high:
            trade_side = "SHORT"
            stop_loss = sw_high * 1.003
            tp_1 = fib_short_0382
            tp_2 = sw_low

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
                    elif fbar['high'] >= tp_2:
                        outcome = "TP2_FULL"
                        break
                    elif fbar['high'] >= tp_1 and outcome != "TP1_HIT":
                        outcome = "TP1_HIT"
                else:
                    if fbar['high'] >= stop_loss:
                        outcome = "SL"
                        break
                    elif fbar['low'] <= tp_2:
                        outcome = "TP2_FULL"
                        break
                    elif fbar['low'] <= tp_1 and outcome != "TP1_HIT":
                        outcome = "TP1_HIT"

            records.append({
                'Symbol': display_name,
                'Side': trade_side,
                'Time': candle['datetime'],
                'Entry': entry_price,
                'Result': outcome
            })

            i += max(bars_held, 2)
        else:
            i += 1

    return records

def main():
    send_discord_alert("🧪 **[BACKTEST] 啟動 17 檔指定標的 (含原油/美股/幣種) 多空回測...**")
    
    perp_exchange = ccxt.binanceusdm({'enableRateLimit': True})
    spot_exchange = ccxt.binance({'enableRateLimit': True})
    all_results = []

    for name in TARGET_SYMBOLS:
        # 優先搜尋合約市場，查無再搜尋現貨市場
        res = run_backtest_on_symbol(perp_exchange, name)
        if not res:
            res = run_backtest_on_symbol(spot_exchange, name)
        all_results.extend(res)
        time.sleep(0.1)

    if not all_results:
        send_discord_alert("📋 **[BACKTEST REPORT]** 本輪未產生交易數據。")
        return

    res_df = pd.DataFrame(all_results)
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
        trade_details += f"[{r['Time']}] {r['Side']} {r['Symbol']} @ ${r['Entry']:.2f} -> {r['Result']}\n"

    report_msg = (
        f"📊 **[BACKTEST REPORT] 17 檔標的多空斐波那契報告 (15m)**\n"
        f"```text\n"
        f"總進場次數  : {total_trades} 次 (多: {long_trades} / 空: {short_trades})\n"
        f"TP1 達標勝率: {win_rate:.1f}% ({tp1_count}/{total_trades})\n"
        f"TP2 終極達標: {tp2_count} 次\n"
        f"SL 停損離場 : {sl_count} 次\n"
        f"持倉/未觸發 : {holding_count} 次\n"
        f"----------------------------------------\n"
        f"近期交易明細:\n"
        f"{trade_details}"
        f"```"
    )
    send_discord_alert(report_msg)
    print("=== 回測完成 ===")

if __name__ == '__main__':
    main()
