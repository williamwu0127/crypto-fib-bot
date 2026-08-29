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

def send_discord_alert(content):
    """發送 Discord Webhook 通知"""
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content})
    except Exception as err:
        print(f"發送 Discord 失敗: {err}")

def calculate_rsi(series, period=14):
    """純 Pandas 計算 RSI"""
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

        # 取得上一根已收盤的 K 棒
        candle = df.iloc[-2]

        lower_wick = min(candle['open'], candle['close']) - candle['low']
        body_size = abs(candle['close'] - candle['open'])

        # 條件判定
        hit_fib = (candle['low'] <= fib_0618) and (candle['close'] >= fib_0618)
        rsi_oversold = candle['rsi'] <= 35
        hammer_candle = lower_wick > (body_size * 1.5)
        vol_spike = candle['volume'] > (candle['vol_sma'] * 1.5)

        print(f"[{symbol}] 現價: {candle['close']} | Fib: {fib_0618:.2f} | RSI: {candle['rsi']:.2f}")

        # 判斷階段
        if hit_fib and rsi_oversold and hammer_candle and vol_spike:
            msg = (
                f"🔥 **【階段三：完全共振進場訊號】**\n"
                f"**標的**：`{symbol}` ({TIMEFRAME})\n"
                f"**現價**：`${candle['close']}`\n"
                f"**Fib 0.618 支撐**：`${fib_0618:.4f}`\n"
                f"**RSI**：`{candle['rsi']:.2f}`\n"
                f"**狀態**：✅ 踩點 0.618 + ✅ RSI 超賣 + ✅ 長下影線 + ✅ 爆量"
            )
            send_discord_alert(msg)
            return "STAGE_3"

        elif hit_fib and rsi_oversold:
            msg = (
                f"⚡ **【階段二：動能預警 - 準備反轉】**\n"
                f"**標的**：`{symbol}` ({TIMEFRAME})\n"
                f"**現價**：`${candle['close']}`\n"
                f"**Fib 0.618 支撐**：`${fib_0618:.4f}`\n"
                f"**RSI**：`{candle['rsi']:.2f}`\n"
                f"**狀態**：✅ 踩點 0.618 + ✅ RSI 超賣 (等待 K 線與量能確認)"
            )
            send_discord_alert(msg)
            return "STAGE_2"

        elif hit_fib:
            msg = (
                f"👀 **【階段一：觀察提醒 - 觸及支撐】**\n"
                f"**標的**：`{symbol}` ({TIMEFRAME})\n"
                f"**現價**：`${candle['close']}`\n"
                f"**Fib 0.618 支撐**：`${fib_0618:.4f}`\n"
                f"**RSI**：`{candle['rsi']:.2f}`\n"
                f"**狀態**：✅ 價格已回落至 Fib 0.618 關鍵區域"
            )
            send_discord_alert(msg)
            return "STAGE_1"

        return "NO_SIGNAL"

    except Exception as e:
        print(f"檢查 {symbol} 時發生錯誤: {e}")
        return "ERROR"

def main():
    # 1. 啟動通知
    send_discord_alert("🤖 **【交易監控機器人】開始執行本小時多幣種掃描...**")
    
    exchange = ccxt.binance()
    triggered_count = 0
    
    # 2. 依序檢查各幣種
    for symbol in SYMBOLS:
        status = check_fib_resonance(exchange, symbol)
        if status in ["STAGE_1", "STAGE_2", "STAGE_3"]:
            triggered_count += 1
        time.sleep(1)
        
    # 3. 若全部幣種皆無觸發任何訊號，發送彙總通知
    if triggered_count == 0:
        no_signal_msg = (
            f"ℹ️ **【掃描完成】**\n"
            f"本輪已檢查 `{len(SYMBOLS)}` 個標的（{', '.join([s.split('/')[0] for s in SYMBOLS])}）。\n"
            f"**結果**：目前均未觸及 Fib 0.618 關鍵條件，持續監控中。"
        )
        send_discord_alert(no_signal_msg)
        
    print("=== 全數掃描完成 ===")

if __name__ == '__main__':
    main()
