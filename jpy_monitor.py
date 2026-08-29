import os
import requests
import pandas as pd
import yfinance as yf

# 1. 讀取 Discord Webhook URL (共用同一組 Secrets)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

def send_discord_alert(content):
    """發送 Discord 訊息"""
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    except Exception as err:
        print(f"推播失敗: {err}")

def calculate_rsi(series, period=14):
    """計算標準 RSI"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))

# ==========================================
# 模組 A：日幣換匯甜蜜點監控 (JPY/TWD)
# ==========================================
def check_jpy_twd_exchange():
    try:
        ticker = yf.Ticker("JPYTWD=X")
        df = ticker.history(period="3mo", interval="1d")
        if df.empty or len(df) < 10:
            return

        current_rate = df['Close'].iloc[-1]
        low_90d = df['Low'].min()
        high_90d = df['High'].max()

        # 計算當前匯率在近 90 天的百分位區間
        percentile = ((current_rate - low_90d) / (high_90d - low_90d)) * 100

        # 當處於近 90 天最低 15% 區間，或跌破重要心理整數關卡 (如 0.210)
        is_sweet_spot = (percentile <= 15.0) or (current_rate <= 0.2100)

        if is_sweet_spot:
            msg = (
                f"🇯🇵 **[FX ALERT] 日幣換匯甜蜜點通知**\n"
                f"```text\n"
                f"標的匯率 : JPY / TWD (日圓兌台幣)\n"
                f"當前匯率 : {current_rate:.4f}\n"
                f"90D 區間 : {low_90d:.4f} ~ {high_90d:.4f}\n"
                f"水位位置 : 近 90 天最低 {percentile:.1f}% 區間\n"
                f"策略建議 : 觸發階梯式換匯區間，可考慮分批進場換匯。\n"
                f"```"
            )
            send_discord_alert(msg)
            return True
        return False
    except Exception as e:
        print(f"JPY/TWD 監控異常: {e}")
        return False

# ==========================================
# 模組 B：USD/JPY 趨勢共振量化監控 (4h 週期)
# ==========================================
def check_usdjpy_resonance():
    try:
        ticker = yf.Ticker("JPY=X")
        # 抓取 4 小時 K 線 (60m 聚合或 1h 計算)
        df = ticker.history(period="1mo", interval="60m")
        if df.empty or len(df) < 35:
            return False

        df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
        df['rsi'] = calculate_rsi(df['close'], period=14)

        # 取過去 30 根 K 線計算 Fib
        swing_high = df['high'][-30:].max()
        swing_low = df['low'][-30:].min()
        fib_range = swing_high - swing_low

        fib_0618 = swing_high - (fib_range * 0.618)
        fib_0382 = swing_high - (fib_range * 0.382)

        candle = df.iloc[-2]
        current_price = candle['close']

        lower_wick = min(candle['open'], candle['close']) - candle['low']
        body_size = abs(candle['close'] - candle['open'])

        hit_fib = (candle['low'] <= fib_0618) and (candle['close'] >= fib_0618)
        rsi_oversold = candle['rsi'] <= 35
        hammer = lower_wick > (body_size * 1.5)

        # 止盈與停損點位計算
        stop_loss = candle['low'] * 0.9985
        tp_1 = fib_0382
        tp_2 = swing_high

        risk = max(current_price - stop_loss, 1e-4)
        reward = max(tp_1 - current_price, 0)
        rr_ratio = reward / risk

        if hit_fib and rsi_oversold and hammer:
            msg = (
                f"⚡ **[SIGNAL] USD/JPY 斐波那契共振進場 (多單)**\n"
                f"```text\n"
                f"標的      : USD / JPY (1h/4h)\n"
                f"現價      : {current_price:.3f}\n"
                f"停損 (SL) : {stop_loss:.3f}\n"
                f"TP1(0.382): {tp_1:.3f}\n"
                f"TP2(High) : {tp_2:.3f}\n"
                f"盈虧比    : 1 : {rr_ratio:.2f}\n"
                f"訊號條件  : Fib 0.618 踩點 + RSI 超賣 ({candle['rsi']:.1f}) + 錘子下影線\n"
                f"```"
            )
            send_discord_alert(msg)
            return True
        return False
    except Exception as e:
        print(f"USD/JPY 監控異常: {e}")
        return False

def main():
    alert_twd = check_jpy_twd_exchange()
    alert_usdjpy = check_usdjpy_resonance()

    # 若兩者皆未觸發特殊訊號，發送極簡狀態確認
    if not alert_twd and not alert_usdjpy:
        try:
            ticker = yf.Ticker("JPYTWD=X")
            df = ticker.history(period="1d")
            rate = df['Close'].iloc[-1] if not df.empty else 0.0
            send_discord_alert(f"`[FX 巡檢] JPY/TWD 現價 {rate:.4f}｜USD/JPY 無共振訊號。`")
        except Exception:
            pass

    print("=== 日幣監控完成 ===")

if __name__ == '__main__':
    main()
