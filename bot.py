import os
import time
import requests
import ccxt
import pandas as pd

# 1. Discord Webhook URL
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 2. 加密貨幣監控清單 (Binance 現貨/永續合約通用)
CRYPTO_SYMBOLS = [
    'BTC/USDT',
    'ETH/USDT',
    'PAXG/USDT',      # 黃金代幣 (XAU)
    'PLAY/USDT',
    'LAB/USDT',
    'CLU/USDT',
    '币安人生/USDT'
]

STOCK_PERP_SYMBOLS = [
    'TSM/USDT:USDT',
    'NVDA/USDT:USDT',
    'TSLA/USDT:USDT',
    'AAPL/USDT:USDT',
    'GOOGL/USDT:USDT',
    'MU/USDT:USDT',
    'AMZN/USDT:USDT',
    'MSFT/USDT:USDT',
    'META/USDT:USDT',
    'PLTR/USDT:USDT',
    'COIN/USDT:USDT',
    'MSTR/USDT:USDT'
]

TIMEFRAME = '15m'

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

def evaluate_resonance(exchange, symbol, market_type):
    display_name = symbol.split(':')[0]
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
        if not ohlcv or len(ohlcv) < 35:
            return "INSUFFICIENT_DATA"

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['rsi'] = calculate_rsi(df['close'], period=14)
        df['vol_sma'] = df['volume'].rolling(window=20).mean()

        swing_high = df['high'][-30:].max()
        swing_low = df['low'][-30:].min()
        fib_range = swing_high - swing_low

        fib_0618 = swing_high - (fib_range * 0.618)
        fib_0382 = swing_high - (fib_range * 0.382)
        fib_0786 = swing_high - (fib_range * 0.786)

        candle = df.iloc[-2]
        current_price = candle['close']

        lower_wick = min(candle['open'], candle['close']) - candle['low']
        body_size = abs(candle['close'] - candle['open'])

        hit_fib = (candle['low'] <= fib_0618) and (candle['close'] >= fib_0618)
        rsi_oversold = candle['rsi'] <= 35
        hammer_candle = lower_wick > (body_size * 1.5)
        vol_spike = candle['volume'] > (candle['vol_sma'] * 1.5)

        stop_loss = min(candle['low'] * 0.998, fib_0786)
        tp_1 = fib_0382
        tp_2 = swing_high

        risk = max(current_price - stop_loss, 1e-4)
        reward_tp1 = max(tp_1 - current_price, 0)
        rr_ratio = reward_tp1 / risk

        print(f"[{market_type} | {display_name}] P: {current_price:.2f} | Fib: {fib_0618:.2f} | RSI: {candle['rsi']:.2f}")

        if hit_fib and rsi_oversold and hammer_candle and vol_spike:
            msg = (
                "🎯 **[SIGNAL] 共振進場確認｜" + display_name + " (" + TIMEFRAME + ")**\n"
                "```text\n"
                "Market      : " + market_type + "\n"
                "Entry Price : $" + f"{current_price:.2f}" + "\n"
                "Stop Loss   : $" + f"{stop_loss:.2f}" + "\n"
                "TP1 (0.382) : $" + f"{tp_1:.2f}" + "\n"
                "TP2 (High)  : $" + f"{tp_2:.2f}" + "\n"
                "Risk/Reward : 1 : " + f"{rr_ratio:.2f}" + "\n"
                "Condition   : Fib 0.618 + RSI 超賣 (" + f"{candle['rsi']:.1f}" + ") + 爆量長下影\n"
                "```"
            )
            send_discord_alert(msg)
            return "STAGE_3"

        elif hit_fib and rsi_oversold:
            msg = (
                "⚡ **[ALERT] 動能反轉預警｜" + display_name + " (" + TIMEFRAME + ")**\n"
                "```text\n"
                "Market: " + market_type + " | Price: $" + f"{current_price:.2f}" + " | Fib 0.618: $" + f"{fib_0618:.2f}" + " | RSI: " + f"{candle['rsi']:.1f}" + "\n"
                "Status: 觸及 0.618 且 RSI 超賣，待 K 棒收線確認。\n"
                "```"
            )
            send_discord_alert(msg)
            return "STAGE_2"

        elif hit_fib:
            msg = (
                "👀 **[WATCH] 觸及關鍵支撐｜" + display_name + " (" + TIMEFRAME + ")**\n"
                "```text\n"
                "Market: " + market_type + " | Price: $" + f"{current_price:.2f}" + " \vert{} Fib 0.618: $" + f"{fib_0618:.2f}" + " | RSI: " + f"{candle['rsi']:.1f}" + "\n"
                "Status: 價格回落至 Fib 0.618 區間。\n"
                "```"
            )
            send_discord_alert(msg)
            return "STAGE_1"

        return "NO_SIGNAL"

    except Exception as e:
        print("檢查標的略過:", symbol, e)
        return "ERROR"

def main():
    send_discord_alert("📡 **系統啟動：開始執行市場掃描...**")
    
    spot_exchange = ccxt.binance()
    perp_exchange = ccxt.binanceusdm()
    triggered_count = 0

    for sym in CRYPTO_SYMBOLS:
        status = evaluate_resonance(spot_exchange, sym, "Crypto")
        if status in ["STAGE_1", "STAGE_2", "STAGE_3"]:
            triggered_count += 1
        time.sleep(0.2)

    for sym in STOCK_PERP_SYMBOLS:
        status = evaluate_resonance(perp_exchange, sym, "TradFi Perp")
        if status in ["STAGE_1", "STAGE_2", "STAGE_3"]:
            triggered_count += 1
        time.sleep(0.2)

    if triggered_count == 0:
        total_count = len(CRYPTO_SYMBOLS) + len(STOCK_PERP_SYMBOLS)
        send_discord_alert("📋 **掃描完成**：共巡檢 `" + str(total_count) + "` 檔標的，目前皆無共振訊號。")
        
    print("=== 全數掃描完成 ===")

if __name__ == '__main__':
    main()
