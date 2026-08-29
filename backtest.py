import os
import time
import requests
import ccxt
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 加密貨幣標的
CRYPTO_SYMBOLS = [
    'BTC/USDT',
    'ETH/USDT',
    'PAXG/USDT',      # 黃金代幣 (XAU)
    'PLAY/USDT',
    'LAB/USDT',
    'CLU/USDT',
    '币安人生/USDT'
]

# 幣安合約標的 (若美股合約無數據會自動略過並在 log 提示)
STOCK_PERP_SYMBOLS = [
    'TSM/USDT:USDT',    # 台積電
    'NVDA/USDT:USDT',   # 輝達
    'TSLA/USDT:USDT',   # 特斯拉
    'AAPL/USDT:USDT',   # 蘋果
    'GOOGL/USDT:USDT',  # 谷歌
    'MU/USDT:USDT',     # 美光
    'AMZN/USDT:USDT',   # 亞馬遜
    'MSFT/USDT:USDT',   # 微軟
    'META/USDT:USDT',   # Meta
    'PLTR/USDT:USDT',   # Palantir
    'COIN/USDT:USDT',   # Coinbase
    'MSTR/USDT:USDT'    # 微策略
]

TIMEFRAME = '15m'
FETCH_LIMIT = 1000

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

def run_backtest_on_symbol(exchange, symbol, market_name):
    display_name = symbol.split(':')[0]
    records = []
    
    # 嘗試抓取 K 線 (含相容處理)
    ohlcv = None
    target_symbols = [symbol, symbol + ":USDT", symbol.replace('/', '')]
    
    for s in target_symbols:
        try:
            ohlcv = exchange.fetch_ohlcv(s, TIMEFRAME, limit=FETCH_LIMIT)
            if ohlcv and len(ohlcv) >= 60:
                break
        except Exception:
            continue

    if not ohlcv or len(ohlcv) < 60:
        print(f"⚠️ [{market_name}] {display_name} 無法獲取足夠 K 線數據，略過。")
        return records

    print(f"✅ [{market_name}] {display_name} 成功載入 {len(ohlcv)} 根 K 線，開始計算 Fib 波段...")

    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%m/%d %H:%M')
    df['rsi'] = calculate_rsi(df['close'], period=14)

    i = 25
    while i < len(df) - 1:
        sub = df.iloc[i-20:i+1]
        
        sw_high = sub['high'].max()
        sw_low = sub['low'].min()
        wave = sw_high - sw_low

        if wave <= 0 or (wave / sw_low) < 0.005:
            i += 1
            continue

        candle = df.iloc[i]
        entry_price = candle['close']

        # Fib 關鍵水位
        fib_long_0618 = sw_high - (wave * 0.618)
        fib_short_0618 = sw_low + (wave * 0.618)

        fib_long_0382 = sw_high - (wave * 0.382)
        fib_short_0382 = sw_low + (wave * 0.382)

        trade_side = None
        stop_loss = 0
        tp_1 = 0
        tp_2 = 0

        # 多單：觸及 Fib 0.618 支撐且收陽線/下影線
        if candle['low'] <= fib_long_0618 and candle['close'] >= sw_low:
            trade_side = "LONG"
            stop_loss = sw_low * 0.997
            tp_1 = fib_long_0382
            tp_2 = sw_high

        # 空單：觸及 Fib 0.618 阻力且收陰線/上影線
        elif candle['high'] >= fib_short_0618 and candle['close'] <= sw_high:
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
                'Market': market_name,
                'Time': candle['datetime'],
                'Entry': entry_price,
                'Result': outcome
            })

            i += max(bars_held, 2)
        else:
            i += 1

    return records

def main():
    send_discord_alert("🧪 **[BACKTEST] 啟動多空斐波那契回測（含相容修復）...**")
    
    spot = ccxt.binance()
    perp = ccxt.binanceusdm()
    all_results = []

    for sym in CRYPTO_SYMBOLS:
        all_results.extend(run_backtest_on_symbol(spot, sym, "現貨"))
        time.sleep(0.15)

    for sym in STOCK_PERP_SYMBOLS:
        all_results.extend(run_backtest_on_symbol(perp, sym, "合約"))
        time.sleep(0.15)

    if not all_results:
        send_discord_alert("📋 **[BACKTEST REPORT]** 本輪仍無交易數據。")
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
        f"📊 **[BACKTEST REPORT] 多空斐波那契回測報告 (15m)**\n"
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
