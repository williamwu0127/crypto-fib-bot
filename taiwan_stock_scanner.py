import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from FinMind.Data import DataLoader

# 參數設定
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1543491812101062697/qM1ZaG4UGxu5zoyWxWZJVeL3SLDNCcKTGobB4OhBYRAazuSHRz-WHn2mLSvJ9RwKgxgf")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")

dl = DataLoader()
if FINMIND_TOKEN:
    dl.login_by_token(api_token=FINMIND_TOKEN)

def get_trading_dates(lookback_days=90):
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    return start_date, end_date

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(series, fast=12, slow=26, signal=9):
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    dif = exp1 - exp2
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist

def get_stock_pool():
    # 抓取上市與上櫃股票基本清單
    try:
        df_info = dl.taiwan_stock_info()
        stocks = df_info[df_info['type'].isin(['twse', 'tpex'])]['stock_id'].tolist()
        # 過濾純 4 位數股票代號（排除權證、特別股等）
        stocks = [s for s in stocks if len(s) == 4 and s.isdigit()]
        return stocks
    except Exception as e:
        print(f"取得股票清單失敗: {e}")
        return []

def evaluate_stock(stock_id, start_date, end_date):
    try:
        # 1. 抓取日 K 線歷史資料
        df_price = dl.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if df_price.empty or len(df_price) < 25:
            return None

        # 資料計算
        df_price['Trading_money'] = df_price['Trading_money'].astype(float)
        df_price['close'] = df_price['close'].astype(float)
        df_price['open'] = df_price['open'].astype(float)
        df_price['max'] = df_price['max'].astype(float)
        df_price['min'] = df_price['min'].astype(float)
        df_price['Trading_Volume'] = df_price['Trading_Volume'].astype(float)

        latest = df_price.iloc[-1]
        today_money = latest['Trading_money']
        today_close = latest['close']
        today_open = latest['open']
        today_high = latest['max']
        today_low = latest['min']
        today_vol = latest['Trading_Volume']

        # 均線計算
        ma5 = df_price['close'].rolling(5).mean().iloc[-1]
        ma10 = df_price['close'].rolling(10).mean().iloc[-1]
        ma20_series = df_price['close'].rolling(20).mean()
        ma20 = ma20_series.iloc[-1]
        ma20_slope = ma20 - ma20_series.iloc[-2]
        vol_ma5 = df_price['Trading_Volume'].rolling(5).mean().iloc[-1]

        # 第一階段：硬性門檻過濾
        if today_money < 50_000_000:  # 成交金額 >= 5000 萬
            return None
        if today_close < ma20:        # 跌破月線直接剔除
            return None

        score = 0
        reasons = []

        # 2. 技術與量價評分
        # 量能爆發 (+15)
        if vol_ma5 > 0 and (today_vol / vol_ma5) >= 1.5:
            score += 15
            reasons.append("帶量突破 (量比 >= 1.5)")

        # 實體紅 K 品質 (+15)
        k_range = today_high - today_low
        if k_range > 0 and (today_close - today_low) / k_range >= 0.8:
            score += 15
            reasons.append("實體紅 K 收高")

        # 均線多頭排列 (+15)
        if today_close > ma5 > ma10 > ma20 and ma20_slope > 0:
            score += 15
            reasons.append("均線多頭排列 (20MA向上)")

        # 突破 20 日新高 (+10)
        high_20d = df_price['close'].iloc[-21:-1].max()
        if today_close > high_20d:
            score += 10
            reasons.append("創 20 日收盤新高")

        # RSI & MACD (+10)
        rsi = calculate_rsi(df_price['close']).iloc[-1]
        _, _, hist = calculate_macd(df_price['close'])
        if 50 <= rsi <= 75 and hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2]:
            score += 10
            reasons.append("MACD 擴大 / RSI 處強勢區")

        # 3. 籌碼面評分 (法人動向)
        df_inst = dl.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if not df_inst.empty:
            # 投信 (Investment_Trust)
            it_df = df_inst[df_inst['name'] == 'Investment_Trust'].sort_values('date')
            if len(it_df) >= 3:
                recent_it = it_df.iloc[-3:]
                it_buy_days = (recent_it['buy'] > recent_it['sell']).sum()
                if it_buy_days >= 2 and (recent_it.iloc[-1]['buy'] > recent_it.iloc[-1]['sell']):
                    score += 20
                    reasons.append(f"投信近3日買超{it_buy_days}天")

            # 外資 (Foreign_Investor)
            foreign_df = df_inst[df_inst['name'] == 'Foreign_Investor'].sort_values('date')
            if not foreign_df.empty:
                latest_foreign = foreign_df.iloc[-1]
                if latest_foreign['buy'] > latest_foreign['sell']:
                    score += 10
                    reasons.append("外資同步買超")

        # 扣分機制
        if k_range > 0 and (today_high - today_close) / k_range > 0.4:
            score -= 20
            reasons.append("長上影線 (-20)")
        if rsi > 80:
            score -= 10
            reasons.append("RSI 過熱超買 (-10)")

        return {
            "stock_id": stock_id,
            "close": today_close,
            "turnover_mil": round(today_money / 100_000_000, 2),
            "score": score,
            "ma20": round(ma20, 2),
            "reasons": reasons
        }
    except Exception:
        return None

def send_discord_notification(results):
    if not results:
        print("今日無符合門檻之標的。")
        return

    # 按評分由大到小排序，取前 5 檔
    top_picks = sorted(results, key=lambda x: x['score'], reverse=True)[:5]
    
    fields = []
    for item in top_picks:
        reasons_text = "、".join(item['reasons']) if item['reasons'] else "無"
        fields.append({
            "name": f"🎯 【{item['stock_id']}】 總評分: {item['score']} 分",
            "value": f"• **現價**: `{item['close']}` 元 (防守 20MA: `{item['ma20']}`)\n• **成交金額**: `{item['turnover_mil']}` 億元\n• **觸發特徵**: {reasons_text}",
            "inline": False
        })

    payload = {
        "username": "台股量化選股機器人",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/3314/3314547.png",
        "embeds": [{
            "title": "📊 每日台股高勝率篩選報告",
            "description": f"掃描完成時間：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n已過濾流動性門檻與多頭排列，精選前 5 高分標的：",
            "color": 15158332 if top_picks[0]['score'] >= 80 else 3066993,
            "fields": fields,
            "footer": {
                "text": "台股策略篩選系統 • 僅供量化數據參考"
            }
        }]
    }

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code in [200, 204]:
        print("Discord 訊息推播成功！")
    else:
        print(f"推播失敗，狀態碼: {resp.status_code}, 內容: {resp.text}")

def main():
    print("開始執行台股每日掃描...")
    start_date, end_date = get_trading_dates(90)
    stock_pool = get_stock_pool()
    print(f"載入標的數: {len(stock_pool)} 檔")

    results = []
    # 進行掃描
    for idx, sid in enumerate(stock_pool):
        res = evaluate_stock(sid, start_date, end_date)
        if res and res['score'] >= 60:
            results.append(res)
            print(f"[{idx+1}/{len(stock_pool)}] 標的 {sid} 達標: {res['score']} 分")

    send_discord_notification(results)

if __name__ == "__main__":
    main()
