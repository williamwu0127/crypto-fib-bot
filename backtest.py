import os
import time
import requests
import ccxt
import pandas as pd
import numpy as np

# 1. 讀取 Discord Webhook URL
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 2. 加密貨幣監控清單 (Binance 現貨/永續合約通用)
CRYPTO_SYMBOLS = [
    'BTC/USDT',
    'ETH/USDT',
    'PAXG/USDT',      # 黃金代幣 (XAU)
    'PLAY/USDT',
    'LAB/USDT',
    'CLU/USDT',
    '币安人生/USDT'
]

# 3. 幣安美股永續合約監控清單 (TradFi Perps)
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
FETCH_LIMIT = 800

def send_discord_alert(content):
    """發送 Discord 訊息"""
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
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=FETCH_LIMIT)
        if not ohlcv or len(ohlcv) < 100:
            return records

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%m/%d %H:%M')
        df['rsi'] = calculate_rsi(df['close'], period=14)
        df['vol_sma'] = df['volume'].rolling(window=20).mean()

        i = 35
        while i < len(df) - 1:
            sub_df = df.iloc[:i+1]
            swing_high = sub_df['high'][-30:].max()
            swing_low = sub_df['low'][-30:].min()
            fib_range = swing_high - swing_low

            fib_0618 = swing_high - (fib_range * 0.618)
            fib_0382 = swing_high - (fib_range * 0.382)
            fib_0786 = swing_high - (fib_range * 0.786)

            candle = sub_df.iloc[-1]
            entry_price = candle['close']
            lower_wick = min(candle['open'], candle['close']) - candle['low']
            body_size = abs(candle['close'] - candle['open'])

            # 4 重共振進場條件
            hit_fib = (candle['low'] <= fib_0618) and (candle['close'] >= fib_0618)
            rsi_oversold = candle['rsi'] <= 35
            hammer = lower_wick > (body_size * 1.5)
            vol_spike = candle['volume'] > (candle['vol_sma'] * 1.5)

            if hit_fib and rsi_oversold and hammer and vol_spike:
                stop_loss = min(candle['low'] * 0.998, fib_0786)
                tp_1 = fib_0382
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

                records.append({
                    'Symbol': display_name,
                    'Market': market_name,
                    'Time': candle['datetime'],
                    'Entry': entry_price,
                    'Result': outcome
                })

                i += max(bars_held, 1)
            else:
                i += 1

    except Exception as e:
        print(f"回測 {symbol} 略過: {e}")

    return records

def main():
    send_discord_alert("🧪 **[BACKTEST] 開始執行過去 7 天 19 檔標的回測...**")
    
    spot_exchange = ccxt.binance()
    perp_exchange = ccxt.binanceusdm()
    all_results = []

    for sym in CRYPTO_SYMBOLS:
        all_results.extend(run_backtest_on_symbol(spot_exchange, sym, "現貨"))
        time.sleep(0.15)

    for sym in STOCK_PERP_SYMBOLS:
        all_results.extend(run_backtest_on_symbol(perp_exchange, sym, "合約"))
        time.sleep(0.15)

    if not all_results:
        send_discord_alert("📋 **[BACKTEST REPORT] 過去 7 天回測結果**\n```text\n未觸發任何完全共振進場條件 (0.618 + RSI<=35 + 長下影 + 爆量)。\n```")
        return

    res_df = pd.DataFrame(all_results)
    total_trades = len(res_df)
    tp1_count = len(res_df[res_df['Result'].isin(['TP1_HIT', 'TP2_FULL'])])
    tp2_count = len(res_df[res_df['Result'] == 'TP2_FULL'])
    sl_count = len(res_df[res_df['Result'] == 'SL'])
    holding_count = len(res_df[res_df['Result'] == 'HOLDING'])
    win_rate = (tp1_count / total_trades) * 100 if total_trades > 0 else 0

    # 組合交易明細 (最多列出前 10 筆)
    trade_details = ""
    for _, r in res_df.head(10).iterrows():
        trade_details += f"[{r['Time']}] {r['Symbol']} @ ${r['Entry']:.2f} -> {r['Result']}\n"

    report_msg = (
        f"📊 **[BACKTEST REPORT] 過去 7 天量化回測報告 (15m)**\n"
        f"```text\n"
        f"總進場次數  : {total_trades} 次\n"
        f"TP1 達標勝率: {win_rate:.1f}% ({tp1_count}/{total_trades})\n"
        f"TP2 終極達標: {tp2_count} 次\n"
        f"SL 停損離場 : {sl_count} 次\n"
        f"持倉/未觸發 : {holding_count} 次\n"
        f"----------------------------------------\n"
        f"交易明細紀錄 (近期):\n"
        f"{trade_details}"
        f"```"
    )
    send_discord_alert(report_msg)
    print("=== 回測與推播完成 ===")

if __name__ == '__main__':
    main()
