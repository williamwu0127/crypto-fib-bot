import time
import ccxt
import pandas as pd
import numpy as np

# 19 檔標的清單
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
# 過去 7 天約為 7 * 24 * 4 = 672 根 15m K 線，多抓取一些確保歷史指標完整
FETCH_LIMIT = 800

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
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['rsi'] = calculate_rsi(df['close'], period=14)
        df['vol_sma'] = df['volume'].rolling(window=20).mean()

        # 從第 35 根開始遍歷模擬每一根 K 線收盤時的狀態
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

                # 追蹤進場後的後續 K 線 (最長觀察 48 根 K 棒 = 12 小時)
                outcome = "HOLDING"
                exit_price = entry_price
                bars_held = 0

                for j in range(i + 1, min(i + 49, len(df))):
                    future_bar = df.iloc[j]
                    bars_held += 1

                    # 1. 檢查是否觸及 SL
                    if future_bar['low'] <= stop_loss:
                        outcome = "SL"
                        exit_price = stop_loss
                        break
                    # 2. 檢查是否觸及 TP2
                    elif future_bar['high'] >= tp_2:
                        outcome = "TP2_FULL"
                        exit_price = tp_2
                        break
                    # 3. 檢查是否觸及 TP1
                    elif future_bar['high'] >= tp_1 and outcome != "TP1_HIT":
                        outcome = "TP1_HIT"
                        exit_price = tp_1

                records.append({
                    'Symbol': display_name,
                    'Market': market_name,
                    'Time': candle['datetime'],
                    'Entry': entry_price,
                    'SL': stop_loss,
                    'TP1': tp_1,
                    'TP2': tp_2,
                    'Result': outcome,
                    'Bars': bars_held
                })

                # 進場後跳過已持倉期間，避免同一次反彈重複開單
                i += max(bars_held, 1)
            else:
                i += 1

    except Exception as e:
        print(f"回測 {symbol} 失敗: {e}")

    return records

def main():
    print("🚀 開始執行過去 7 天 19 檔標的回測...")
    spot_exchange = ccxt.binance()
    perp_exchange = ccxt.binanceusdm()

    all_results = []

    for sym in CRYPTO_SYMBOLS:
        res = run_backtest_on_symbol(spot_exchange, sym, "現貨")
        all_results.extend(res)
        time.sleep(0.2)

    for sym in STOCK_PERP_SYMBOLS:
        res = run_backtest_on_symbol(perp_exchange, sym, "美股合約")
        all_results.extend(res)
        time.sleep(0.2)

    if not all_results:
        print("\n過去 7 天內 19 檔標的皆未出現符合「四重共振（0.618+RSI<=35+長下影+爆量）」的進場訊號。")
        return

    res_df = pd.DataFrame(all_results)
    total_trades = len(res_df)
    tp1_count = len(res_df[res_df['Result'].isin(['TP1_HIT', 'TP2_FULL'])])
    tp2_count = len(res_df[res_df['Result'] == 'TP2_FULL'])
    sl_count = len(res_df[res_df['Result'] == 'SL'])
    holding_count = len(res_df[res_df['Result'] == 'HOLDING'])

    win_rate = (tp1_count / total_trades) * 100 if total_trades > 0 else 0

    print("\n" + "="*50)
    print("📊 【過去一週回測統計報告】")
    print("="*50)
    print(f"總進場機會 (Trades)    : {total_trades} 次")
    print(f"達標 TP1 (第一止盈)   : {tp1_count} 次 (勝率: {win_rate:.1f}%)")
    print(f"達標 TP2 (前高完全止盈): {tp2_count} 次")
    print(f"觸發 SL (停損離場)     : {sl_count} 次")
    print(f"持倉中 / 時間到未達標  : {holding_count} 次")
    print("="*50)

    print("\n詳細每筆交易明細：")
    for _, r in res_df.iterrows():
        print(f"[{r['Time']}] {r['Market']} {r['Symbol']} | Entry: {r['Entry']:.2f} | 狀態: {r['Result']}")

if __name__ == '__main__':
    main()
