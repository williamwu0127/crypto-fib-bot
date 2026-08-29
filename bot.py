import os
import time
import requests
import ccxt
import pandas as pd

# 1. 讀取 Discord Webhook URL
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 2. 定義監控幣種與時間週期
SYMBOLS = [
    'BTC/USDT',
    'ETH/USDT',
    'MU/USDT',
    'XAU/USDT',
    'PLAY/USDT',
    'LAB/USDT'
]
TIMEFRAME = '1h'

def calculate_rsi(series, period=14):
    """純 Pandas 計算標準 RSI"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def check_fib_resonance(exchange, symbol):
    try:
        # 抓取最近 100 根 K 線 (OHLCV)
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # 計算指標
        df['rsi'] = calculate_rsi(df['close'], period=14)
        df['vol_sma'] = df['volume'].rolling(window=20).mean()

        # 抓取過去 30 根 K 棒高低點計算 Fib 0.618 支撐位
        swing_high = df['high'][-30:].max()
        swing_low = df['low'][-30:].min()
        fib_0618 = swing_high - ((swing_high - swing_low) * 0.618)

        # 取得上一根已收盤的 K 棒 (倒數第 2 根)
        candle = df.iloc[-2]

        lower_wick = min(candle['open'], candle['close']) - candle['low']
        body_size = abs(candle['close'] - candle['open'])

        # 共振條件判定
        hit_fib = (candle['low'] <= fib_0618) and (candle['close'] >= fib_0618)
        hammer_candle = lower_wick > (body_size * 1.5)
        vol_spike = candle['volume'] > (candle['vol_sma'] * 1.5)
        rsi_oversold = candle['rsi'] <= 35

        print(f"[{symbol}] 收盤價: {candle['close']} | Fib 0.618: {fib_0618:.2f} | RSI: {candle['rsi']:.2f}")

        # 條件成立時發送通知
        if hit_fib and hammer_candle and vol_spike and rsi_oversold:
            msg = {
                "content": (
                    f"🚨 **【多幣種監控：共振進場訊號】**\n"
                    f"**標的**：{symbol} ({TIMEFRAME})\n"
                    f"**收盤價**：${candle['close']}\n"
                    f"**Fib 0.618 支撐位**：${fib_0618:.4f}\n"
                    f"**RSI 數值**：{candle['rsi']:.2f}\n"
                    f"**條件**：踩點 0.618 + 長下影線 + 爆量 + RSI 超賣"
                )
            }
            if DISCORD_WEBHOOK_URL:
                requests.post(DISCORD_WEBHOOK_URL, json=msg)
            print(f"--> {symbol} 訊號觸發，已推播至 Discord！")

    except Exception as e:
        print(f"檢查 {symbol} 時發生錯誤: {e}")

def main():
    exchange = ccxt.binance()
    print(f"=== 開始執行多幣種掃描 (共 {len(SYMBOLS)} 個幣種) ===")
    
    for symbol in SYMBOLS:
        check_fib_resonance(exchange, symbol)
        time.sleep(1)
        
    print("=== 全數掃描完成 ===")

if __name__ == '__main__':
    main()
