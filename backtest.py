import os
import time
import requests
import ccxt
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

CRYPTO_SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'PAXG/USDT',
    'PLAY/USDT', 'LAB/USDT', 'CLU/USDT'
]

STOCK_PERP_SYMBOLS = [
    'TSM/USDT:USDT', 'NVDA/USDT:USDT', 'TSLA/USDT:USDT',
    'AAPL/USDT:USDT', 'GOOGL/USDT:USDT', 'MU/USDT:USDT',
    'AMZN/USDT:USDT', 'MSFT/USDT:USDT', 'META/USDT:USDT',
    'PLTR/USDT:USDT', 'COIN/USDT:USDT', 'MSTR/USDT:USDT'
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
        df['ema_fast'] = df['close'].ewm(span=20, adjust=False).mean()

        i = 35
        while i < len(df) - 1:
            sub_df = df.iloc[:i+1]
            
            # 尋找過去 30 根的波段高低點
            recent_high = sub_df['high'][-30:].max()
            recent_low = sub_df['low'][-30:].min()
            wave_range = recent_high - recent_low

            if wave_range <= 0:
                i += 1
                continue

            # 幾何邏輯：Fib 0.618 回調支撐位 = 波段高點 - 0.618 * 波段幅度
            fib_0618_support = recent_high - (wave_range * 0.618)
            fib_0382_tp = recent_high - (wave_range * 0.382)

            candle = sub_df.iloc[-1]
            entry_price = candle['close']

            # 進場條件：
            # 1. 價格回踩 Fib 0.618 支撐區間 (容許 0.3% 浮動帶)
            in_fib_zone = (candle['low'] <= fib_0618_support * 1.003) and (candle['close'] >= fib_0618_support * 0.995)
            # 2. RSI 處於相對低位 (<= 45)
            rsi_condition = candle['rsi'] <= 45
            # 3. 收陽線或下影線承接
            lower_wick = min(candle['open'], candle['close']) - candle['low']
            body_size = abs(candle['close'] - candle['open'])
            rejection = (lower_wick >= body_size * 0.8) or (candle['close'] > candle['open'])

            if in_fib_zone and rsi_condition and rejection:
                stop_loss = min(candle['low'] * 0.998, recent_low * 0.999)
                tp_1 = fib_0382_tp if fib_0382_tp > entry_price else recent_high
                tp_2 = recent_high

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

                i += max(bars_held, 2)
            else:
                i += 1

    except Exception as e:
        print(f"回測 {symbol} 略過: {e}")

    return records

def main():
    send_discord_alert("🧪 **[BACKTEST] 執行修復後 Fib 波段回測...**")
    
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
        send_discord_alert("📋 **[BACKTEST REPORT] 過去 7 天回測**\n```text\n未觸發任何訊號。\n```")
        return

    res_df = pd.DataFrame(all_results)
    total_trades = len(res_df)
    tp1_count = len(res_df[res_df['Result'].isin(['TP1_HIT', 'TP2_FULL'])])
    tp2_count = len(res_df[res_df['Result'] == 'TP2_FULL'])
    sl_count = len(res_df[res_df['Result'] == 'SL'])
    holding_count = len(res_df[res_df['Result'] == 'HOLDING'])
    win_rate = (tp1_count / total_trades) * 100 if total_trades > 0 else 0

    trade_details = ""
    for _, r in res_df.head(12).iterrows():
        trade_details += f"[{r['Time']}] {r['Symbol']} @ ${r['Entry']:.2f} -> {r['Result']}\n"

    report_msg = (
        f"📊 **[BACKTEST REPORT] 動態 Fib 波段 7 天回測 (15m)**\n"
        f"```text\n"
        f"總進場次數  : {total_trades} 次\n"
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
