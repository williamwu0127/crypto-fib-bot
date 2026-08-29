import os
import time
import requests
import ccxt
import pandas as pd
import numpy as np

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
FETCH_LIMIT = 1500  # 擴展至約 15 天數據以獲取足夠統計樣本

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
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=FETCH_LIMIT)
        if not ohlcv or len(ohlcv) < 60:
            return records

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%m/%d %H:%M')
        df['rsi'] = calculate_rsi(df['close'], period=14)

        i = 30
        while i < len(df) - 1:
            window = df.iloc[max(0, i-30):i+1]
            
            swing_high = window['high'].max()
            swing_low = window['low'].min()
            wave_range = swing_high - swing_low

            if wave_range <= 0 or (wave_range / swing_low) < 0.008:  # 過濾波幅小於 0.8% 的橫盤無效波段
                i += 1
                continue

            high_pos = window['high'].values.argmax()
            low_pos = window['low'].values.argmin()

            candle = df.iloc[i]
            entry_price = candle['close']

            trade_side = None
            stop_loss = 0
            tp_1 = 0
            tp_2 = 0

            # 1. 多頭架構：低點在先，創出波段高點後回踩
            if low_pos < high_pos:
                fib_0618 = swing_high - (wave_range * 0.618)
                fib_0786 = swing_high - (wave_range * 0.786)
                fib_0382 = swing_high - (wave_range * 0.382)

                # 回踩 0.618~0.786 區間且收陽線或下影線承接
                in_fib_zone = (candle['low'] <= fib_0618 * 1.002) and (candle['close'] >= fib_0786 * 0.998)
                rsi_ok = candle['rsi'] <= 50

                if in_fib_zone and rsi_ok and (candle['close'] >= candle['open'] or (min(candle['open'], candle['close']) - candle['low']) > 0):
                    trade_side = "LONG"
                    stop_loss = swing_low * 0.997
                    tp_1 = fib_0382
                    tp_2 = swing_high

            # 2. 空頭架構：高點在先，創出波段低點後反彈
            elif high_pos < low_pos:
                fib_0618 = swing_low + (wave_range * 0.618)
                fib_0786 = swing_low + (wave_range * 0.786)
                fib_0382 = swing_low + (wave_range * 0.382)

                # 反彈 0.618~0.786 區間且收陰線或上影線承壓
                in_fib_zone = (candle['high'] >= fib_0618 * 0.998) and (candle['close'] <= fib_0786 * 1.002)
                rsi_ok = candle['rsi'] >= 50

                if in_fib_zone and rsi_ok and (candle['close'] <= candle['open'] or (candle['high'] - max(candle['open'], candle['close'])) > 0):
                    trade_side = "SHORT"
                    stop_loss = swing_high * 1.003
                    tp_1 = fib_0382
                    tp_2 = swing_low

            if trade_side:
                outcome = "HOLDING"
                bars_held = 0

                for j in range(i + 1, min(i + 49, len(df))):
                    future_bar = df.iloc[j]
                    bars_held += 1

                    if trade_side == "LONG":
                        if future_bar['low'] <= stop_loss:
                            outcome = "SL"
                            break
                        elif future_bar['high'] >= tp_2:
                            outcome = "TP2_FULL"
                            break
                        elif future_bar['high'] >= tp_1 and outcome != "TP1_HIT":
                            outcome = "TP1_HIT"
                    else:
                        if future_bar['high'] >= stop_loss:
                            outcome = "SL"
                            break
                        elif future_bar['low'] <= tp_2:
                            outcome = "TP2_FULL"
                            break
                        elif future_bar['low'] <= tp_1 and outcome != "TP1_HIT":
                            outcome = "TP1_HIT"

                records.append({
                    'Symbol': display_name,
                    'Side': trade_side,
                    'Market': market_name,
                    'Time': candle['datetime'],
                    'Entry': entry_price,
                    'Result': outcome
                })

                i += max(bars_held, 3)
            else:
                i += 1

    except Exception as e:
        print(f"回測 {symbol} 略過: {e}")

    return records

def main():
    send_discord_alert("🧪 **[BACKTEST] 執行「動態斐波那契拉線（多空雙向）」回測...**")
    
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
        send_discord_alert("📋 **[BACKTEST REPORT]** 未觸發波段回踩訊號。")
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
        f"📊 **[BACKTEST REPORT] 動態斐波那契拉線回測 (15m)**\n"
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
    print("=== 動態 Fib 回測完成 ===")

if __name__ == '__main__':
    main()
