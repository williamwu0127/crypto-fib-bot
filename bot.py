import os
import time
import requests
import ccxt
import pandas as pd
from datetime import datetime

# 1. 讀取 Discord Webhook URL
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# 2. 標的清單
CRYPTO_SYMBOLS = [
    'BTC/USDT',
    'ETH/USDT',
    'PAXG/USDT',      # XAU 黃金代幣
    'PLAY/USDT',
    'LAB/USDT',
    'CLU/USDT',
    '币安人生/USDT'
]

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

TIMEFRAME = '15m'  # 15 分鐘 K 線週期

def send_discord_alert(content):
    """發送 Discord 訊息"""
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    except Exception as err:
        print(f"推播失敗: {err}")

def calculate_rsi(series, period=14):
    """計算 RSI 指標"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))

def evaluate_resonance(exchange, symbol, asset_class="Crypto"):
    display_name = symbol.split(':')[0]
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        if len(df) < 35:
            return "INSUFFICIENT_DATA"

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
        reward = max(tp_1 - current_price, 0)
        rr_ratio = reward / risk

        print(f"[{asset_class} | {display_name}] Close: {current_price:.2f} | Fib 0.618: {fib_0618:.2f} | RSI: {candle['rsi']:.2f}")

        # 階段三：完全共振進場
        if hit_fib and rsi_oversold and hammer_candle and vol_spike:
            msg = (
                f"🎯 **[SIGNAL] 共振進場確認｜{display_name} ({TIMEFRAME})**\n"
                f"```text\n"
                f"Entry Price : ${current_price:.2f}\n"
                f"Stop Loss   : ${stop_loss:.2f}\n"
                f"TP1 (0.382) : ${tp_1:.2f}\n"
                f"TP2 (High)  : ${tp_2:.2f}\n"
                f"Risk/Reward : 1 : {rr_ratio:.2f}\n"
                f"Condition   : Fib 0.618 + RSI Oversold ({candle['rsi']:.1f}) + Vol Spike + Hammer\n"
                f"```"
            )
            send_discord_alert(msg)
            return "STAGE_3"

        # 階段二：動能預警
        elif hit_fib and rsi_oversold:
            msg = (
                f"⚡ **[ALERT] 動能反轉預警｜{display_name} ({TIMEFRAME})**\n"
                f"```text\n"
                f"Price: ${current_price:.2f} | Fib 0.618: ${fib_0618:.2f} | RSI: {candle['rsi']:.1f}\n"
                f"Status: 觸及 0.618 支撐區 且 RSI 超賣，等待 K 線收盤確認。\n"
                f"```"
            )
            send_discord_alert(msg)
            return "STAGE_2"

        # 階段一：觸碰支撐
        elif hit_fib:
            msg = (
                f"👀 **[WATCH] 觸及關鍵支撐｜{display_name} ({TIMEFRAME})**\n"
                f"```text\n"
                f"Price: ${current_price:.2f} \vert{} Fib 0.618:${fib_0618:.2f} | RSI: {candle['rsi']:.1f}\n"
                f"Status: 進入 0.618 斐波那契回撤區間。\n"
                f"```"
            )
            send_discord_alert(msg)
            return "STAGE_1"

        return "NO_SIGNAL"

    except Exception as e:
        print(f"Error checking {symbol}: {e}")
        return "ERROR"

def main():
    spot_exchange = ccxt.binance()
    perp_exchange = ccxt.binanceusdm()
    triggered_count = 0

    # 1. 掃描加密貨幣
    for sym in CRYPTO_SYMBOLS:
        status = evaluate_resonance(spot_exchange, sym, asset_class="Crypto")
        if status in ["STAGE_1", "STAGE_2", "STAGE_3"]:
            triggered_count += 1
        time.sleep(0.2)

    # 2. 掃描美股合約
    for sym in STOCK_PERP_SYMBOLS:
        status = evaluate_resonance(perp_exchange, sym, asset_class="TradFi Perp")
        if status in ["STAGE_1", "STAGE_2", "STAGE_3"]:
            triggered_count += 1
        time.sleep(0.2)

    # 3. 若無訊號，發送極簡狀態回報
    if triggered_count == 0:
        total_assets = len(CRYPTO_SYMBOLS) + len(STOCK_PERP_SYMBOLS)
        now_str = datetime.utcnow().strftime("%H:%M UTC")
        send_discord_alert(f"`[{now_str}] 系統巡檢：{total_assets} 檔標的均未觸發共振條件。`")

    print("=== 掃描完成 ===")

if __name__ == '__main__':
    main()
