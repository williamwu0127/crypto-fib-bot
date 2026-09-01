"""
Multi-Asset ICT/SMC Pro Quantitative Backtest Engine (365 Days)
================================================================================
【完整交易邏輯與架構備份說明】
1. 資金與沙盒架構:
   - 標的範圍: BTC, ETH, SOL, BNB, DOGE (加密貨幣) 及 XAU/PAXG (黃金)。
   - 獨立資金池: 每種標的各自擁有獨立的 100.0 USDT 起始資金與複利帳戶，互不干涉。
   - 報表排序: 嚴格按照加密貨幣在前（BTC, ETH, SOL, BNB, DOGE）、黃金在後（XAU）。

2. 加密貨幣策略模型 (SMC/ICT Pro: 流動性獵取 + OB訂單塊 + FVG + OTE折價區 + 10x槓桿):
   - 趨勢定錨 (4H): EMA20 vs EMA50 相對位置確認中長線主控方向。
   - 流動性獵取 (Liquidity Sweep): 
     * 做多前置: 價格曾插針掃破前期 1H 擺動低點 (SSL) 後迅速收回 (海龜湯模型)。
     * 做空前置: 價格曾插針掃破前期 1H 擺動高點 (BSL) 後迅速收回。
   - 區域鎖定 (1H OB 訂單塊 + FVG + iFVG):
     * 看漲 OB: 爆發上漲前最後一根陰線實體與區間。
     * 看跌 OB: 爆發下跌前最後一根陽線實體與區間。
   - 深度折價/溢價區 (OTE 斐波那契 0.618 ~ 0.79):
     * 做多需回調至 OTE 折價區 (0.618 ~ 0.79)，且觸碰 OB / FVG 區間。
     * 做空需反彈至 OTE 溢價區 (0.618 ~ 0.79)，且觸碰 OB / FVG 區間。
   - 微觀進場確認 (15m): 15m K線踩入區域後實體收盤尊重 (Respect) 確認進場。
   - 風控與止損 (SL): 設在 OB 訂單塊極值外側加上 0.2% 緩衝區 (Buffer)，不設死板絕對防守。每筆交易風險為帳戶權益的 1%。
   - 分批止盈 (TP): 
     * TP1: 達到 2.0R 盈虧比 (或前方次級流動性池) 時平倉 50% 部位，並將剩餘部位止損推至開倉價 (保本)。
     * TP2: 達到 5.0R 盈虧比 (對標大級別 EQH/EQL 流動性獵取目標) 時全數平倉。

3. 黃金策略模型 (XAU / PAXG):
   - 宏觀定錨 (1D): MA60 判斷多空。
   - 突破進場 (4H): 4H 唐奇安通道 (Donchian 20) 突破。
   - 風控與動態保本: 5% 風控 / 10x 槓桿，1.5 ATR 初始止損，浮盈達 2.0R 時移動保本，5.0R 全額止盈。
================================================================================
"""

import os
import time
import requests
import pandas as pd
import numpy as np

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SYMBOLS = {
    'BTC':  {'s': 'BTCUSDT',  'interval': '15m', 'mode': 'crypto_ict_pro', 'lev': 10.0},
    'ETH':  {'s': 'ETHUSDT',  'interval': '15m', 'mode': 'crypto_ict_pro', 'lev': 10.0},
    'SOL':  {'s': 'SOLUSDT',  'interval': '15m', 'mode': 'crypto_ict_pro', 'lev': 10.0},
    'BNB':  {'s': 'BNBUSDT',  'interval': '15m', 'mode': 'crypto_ict_pro', 'lev': 10.0},
    'DOGE': {'s': 'DOGEUSDT', 'interval': '15m', 'mode': 'crypto_ict_pro', 'lev': 10.0},
    'XAU':  {'s': 'PAXGUSDT', 'interval': '4h',  'mode': 'gold_macro_donchian', 'lev': 10.0}
}

INITIAL_WALLET_PER_ASSET = 100.0
FEE_RATE = 0.0004

def send_discord(text):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=8)
        except Exception:
            pass

def fetch_binance_klines(symbol, interval, days=365):
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    all_klines = []
    curr_start = start_ms
    
    step_ms = (15 * 60 * 1000) if interval == '15m' else (60 * 60 * 1000 if interval == '1h' else (4 * 60 * 60 * 1000))
    if interval == '1d':
        step_ms = 24 * 60 * 60 * 1000

    while curr_start < now_ms:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&startTime={curr_start}&limit=1000"
        try:
            res = requests.get(url, timeout=10).json()
            if not isinstance(res, list) or len(res) == 0:
                break
            all_klines.extend(res)
            curr_start = res[-1][0] + step_ms
            time.sleep(0.03)
        except Exception:
            break

    if len(all_klines) > 0:
        cols = ['t', 'o', 'h', 'l', 'c', 'v', 'ct', 'q', 'n', 'tb', 'tq', 'i']
        df = pd.DataFrame(all_klines, columns=cols).drop_duplicates(subset=['t'])
        for col in ['o', 'h', 'l', 'c', 'v']:
            df[col] = df[col].astype(float)
        df['time'] = pd.to_datetime(df['t'], unit='ms')
        return df[['time', 'o', 'h', 'l', 'c', 'v']].sort_values('time').reset_index(drop=True)
    return None

def run_independent_sandbox_backtest():
    days = 365
    period_title = "365 天期 (ICT Pro: 流動性+OB+FVG+OTE 獨立100U沙盒)"
    print(f"\n==================================================")
    print(f">>> 開始執行【{period_title}】多資產獨立資金回測...")
    print(f"==================================================")

    asset_results = {}
    sorted_symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XAU']

    for sym in sorted_symbols:
        cfg = SYMBOLS[sym]
        wallet = float(INITIAL_WALLET_PER_ASSET)
        completed_trades = []
        print(f"獨立跑背測標的: {sym} (起始資金: ${wallet:.2f} USDT)...", flush=True)
        
        # 1. 黃金策略模式
        if cfg['mode'] == 'gold_macro_donchian':
            df_4h = fetch_binance_klines(cfg['s'], '4h', days=days + 30)
            df_1d = fetch_binance_klines(cfg['s'], '1d', days=days + 60)
            if df_4h is None or df_1d is None:
                continue

            df_1d['ma60'] = df_1d['c'].rolling(60).mean()
            df_1d['d_date'] = df_1d['time'].dt.floor('D')
            d_map = df_1d.set_index('d_date')['c'].gt(df_1d.set_index('d_date')['ma60']).to_dict()

            df_4h['d_date'] = df_4h['time'].dt.floor('D')
            df_4h['macro_bull'] = df_4h['d_date'].map(d_map).ffill().fillna(True)
            df_4h['dc_high'] = df_4h['h'].shift(1).rolling(20).max()
            df_4h['dc_low'] = df_4h['l'].shift(1).rolling(20).min()
            tr = np.maximum(df_4h['h'] - df_4h['l'], np.maximum(abs(df_4h['h'] - df_4h['c'].shift(1)), abs(df_4h['l'] - df_4h['c'].shift(1))))
            df_4h['atr'] = tr.rolling(14).mean().fillna(df_4h['c'] * 0.015)

            pos = None
            for i in range(25, len(df_4h)):
                bar = df_4h.iloc[i]
                if pos is not None:
                    side, entry, sl, tp, be_tgt, qty, be_done = pos['side'], pos['entry'], pos['sl'], pos['tp'], pos['be_target'], pos['qty'], pos['is_be_moved']
                    if side == 'LONG':
                        if not be_done and bar['h'] >= be_tgt:
                            pos['sl'] = entry
                            pos['is_be_moved'] = True
                        if bar['l'] <= pos['sl']:
                            pnl = qty * (pos['sl'] - entry) - qty * (entry + pos['sl']) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                        if bar['h'] >= tp:
                            pnl = qty * (tp - entry) - qty * (entry + tp) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                    elif side == 'SHORT':
                        if not be_done and bar['l'] <= be_tgt:
                            pos['sl'] = entry
                            pos['is_be_moved'] = True
                        if bar['h'] >= pos['sl']:
                            pnl = qty * (entry - pos['sl']) - qty * (entry + pos['sl']) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                        if bar['l'] <= tp:
                            pnl = qty * (entry - tp) - qty * (entry + tp) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue

                if pos is None and wallet > 5.0:
                    bull = bar['macro_bull']
                    if bull and bar['c'] > bar['dc_high']:
                        entry = bar['c']
                        sl = entry - (bar['atr'] * 1.5)
                        risk_dist = entry - sl
                        if risk_dist > 0:
                            qty = (wallet * 0.05) / risk_dist
                            if (qty * entry) > (wallet * cfg['lev']):
                                qty = (wallet * cfg['lev']) / entry
                            pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp': entry + (risk_dist * 5.0), 'be_target': entry + (risk_dist * 2.0), 'qty': qty, 'is_be_moved': False}
                    elif not bull and bar['c'] < bar['dc_low']:
                        entry = bar['c']
                        sl = entry + (bar['atr'] * 1.5)
                        risk_dist = sl - entry
                        if risk_dist > 0:
                            qty = (wallet * 0.05) / risk_dist
                            if (qty * entry) > (wallet * cfg['lev']):
                                qty = (wallet * cfg['lev']) / entry
                            pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp': entry - (risk_dist * 5.0), 'be_target': entry - (risk_dist * 2.0), 'qty': qty, 'is_be_moved': False}

        # 2. 加密貨幣 ICT/SMC Pro 策略 (流動性獵取 + OB + FVG + OTE + 10x)
        elif cfg['mode'] == 'crypto_ict_pro':
            df_15m = fetch_binance_klines(cfg['s'], '15m', days=days + 15)
            df_1h  = fetch_binance_klines(cfg['s'], '1h', days=days + 30)
            df_4h  = fetch_binance_klines(cfg['s'], '4h', days=days + 60)
            if df_15m is None or df_1h is None or df_4h is None:
                continue

            # 4H 趨勢定錨
            df_4h['ema20'] = df_4h['c'].ewm(span=20, adjust=False).mean()
            df_4h['ema50'] = df_4h['c'].ewm(span=50, adjust=False).mean()
            df_4h['h_date'] = df_4h['time'].dt.floor('H')
            h4_map = df_4h.set_index('h_date')['ema20'].ge(df_4h.set_index('h_date')['ema50']).to_dict()

            # 1H 流動性結構 (Swing High/Low) 與 OB / FVG 標記
            df_1h['swing_high'] = df_1h['h'].rolling(5).max()
            df_1h['swing_low']  = df_1h['l'].rolling(5).min()

            h1_ict_map = {}
            for j in range(3, len(df_1h)):
                b_curr = df_1h.iloc[j]
                b_prev = df_1h.iloc[j-1]
                b_prev2 = df_1h.iloc[j-2]
                b_prev3 = df_1h.iloc[j-3]
                h_time = b_curr['time'].floor('H')

                # FVG & iFVG
                bull_fvg = b_curr['l'] > b_prev2['h']
                bear_fvg = b_curr['h'] < b_prev2['l']

                # Bullish OB (大漲前最後一根陰線) / Bearish OB (大跌前最後一根陽線)
                bull_ob = (b_prev['c'] < b_prev['o']) and (b_curr['c'] > b_prev['h'])
                bear_ob = (b_prev['c'] > b_prev['o']) and (b_curr['c'] < b_prev['l'])

                # Liquidity Sweep (前波低點/高點被插針並收回)
                sweep_low = (b_curr['l'] < b_prev3['swing_low']) and (b_curr['c'] > b_prev3['swing_low'])
                sweep_high = (b_curr['h'] > b_prev3['swing_high']) and (b_curr['c'] < b_prev3['swing_high'])

                h1_ict_map[h_time] = {
                    'bull_fvg': bull_fvg,
                    'bear_fvg': bear_fvg,
                    'bull_ob': bull_ob,
                    'bear_ob': bear_ob,
                    'sweep_low': sweep_low,
                    'sweep_high': sweep_high,
                    'ob_bull_low': b_prev['l'],
                    'ob_bear_high': b_prev['h'],
                    'fvg_bull_zone': (b_prev2['h'], b_curr['l']) if bull_fvg else (b_prev['l'], b_curr['h']),
                    'fvg_bear_zone': (b_curr['h'], b_prev2['l']) if bear_fvg else (b_curr['l'], b_prev['h'])
                }

            pos = None
            for i in range(25, len(df_15m)):
                bar = df_15m.iloc[i]
                prev_bar = df_15m.iloc[i-1]

                if pos is not None:
                    side, entry, sl, tp1, tp2, qty, tp1_hit = pos['side'], pos['entry'], pos['sl'], pos['tp1'], pos['tp2'], pos['qty'], pos['tp1_hit']
                    if side == 'LONG':
                        if bar['l'] <= sl:
                            rem_qty = qty * 0.5 if tp1_hit else qty
                            pnl = rem_qty * (sl - entry) - rem_qty * (entry + sl) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                        if not tp1_hit and bar['h'] >= tp1:
                            pos['tp1_hit'] = True
                            pnl_tp1 = (qty * 0.5) * (tp1 - entry) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                            wallet += pnl_tp1
                            pos['sl'] = entry
                            completed_trades.append({'pnl': pnl_tp1})
                        if pos['tp1_hit'] and bar['h'] >= tp2:
                            pnl_tp2 = (qty * 0.5) * (tp2 - entry) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                            wallet += pnl_tp2
                            completed_trades.append({'pnl': pnl_tp2})
                            pos = None
                            continue
                    elif side == 'SHORT':
                        if bar['h'] >= sl:
                            rem_qty = qty * 0.5 if tp1_hit else qty
                            pnl = rem_qty * (entry - sl) - rem_qty * (entry + sl) * FEE_RATE
                            wallet += pnl
                            completed_trades.append({'pnl': pnl})
                            pos = None
                            continue
                        if not tp1_hit and bar['l'] <= tp1:
                            pos['tp1_hit'] = True
                            pnl_tp1 = (qty * 0.5) * (entry - tp1) - (qty * 0.5) * (entry + tp1) * FEE_RATE
                            wallet += pnl_tp1
                            pos['sl'] = entry
                            completed_trades.append({'pnl': pnl_tp1})
                        if pos['tp1_hit'] and bar['l'] <= tp2:
                            pnl_tp2 = (qty * 0.5) * (entry - tp2) - (qty * 0.5) * (entry + tp2) * FEE_RATE
                            wallet += pnl_tp2
                            completed_trades.append({'pnl': pnl_tp2})
                            pos = None
                            continue

                if pos is None and wallet > 5.0:
                    t_hour = bar['time'].floor('H')
                    h4_bull = h4_map.get(t_hour, True)
                    ict_info = h1_ict_map.get(t_hour, None)
                    if ict_info is None:
                        continue

                    # 15m OTE (0.618 ~ 0.79 折價/溢價區間)
                    sub = df_15m.iloc[i-25:i+1]
                    h_wave, l_wave = sub['h'].max(), sub['l'].min()
                    wave = h_wave - l_wave
                    if wave > 0:
                        # 做多: 折價區 OTE (0.618 ~ 0.79)
                        ote_bull_high = h_wave - (wave * 0.618)
                        ote_bull_low  = h_wave - (wave * 0.790)

                        # 做空: 溢價區 OTE (0.618 ~ 0.79)
                        ote_bear_low  = l_wave + (wave * 0.618)
                        ote_bear_high = l_wave + (wave * 0.790)

                        # 做多條件: 4H 偏多 + (1H 獵取流動性 OR 踩入 OB/FVG) + 落在 15m OTE 區間 + 15m 陽線尊重收穩
                        long_trigger = (
                            h4_bull and
                            (ict_info['bull_fvg'] or ict_info['bull_ob'] or ict_info['sweep_low']) and
                            (bar['l'] <= ote_bull_high and bar['c'] >= ote_bull_low) and
                            (bar['c'] > prev_bar['c'] and bar['c'] > bar['o'])
                        )

                        # 做空條件: 4H 偏空 + (1H 獵取流動性 OR 觸碰 OB/FVG) + 落在 15m OTE 區間 + 15m 陰線尊重收穩
                        short_trigger = (
                            not h4_bull and
                            (ict_info['bear_fvg'] or ict_info['bear_ob'] or ict_info['sweep_high']) and
                            (bar['h'] >= ote_bear_low and bar['c'] <= ote_bear_high) and
                            (bar['c'] < prev_bar['c'] and bar['c'] < bar['o'])
                        )

                        if long_trigger:
                            entry = bar['c']
                            # 止損錨定於 OB 低點或波段低點外側 + 0.2% 緩衝
                            sl_anchor = min(ict_info['ob_bull_low'], l_wave)
                            sl = sl_anchor * (1.0 - 0.002)
                            risk_dist = entry - sl
                            if risk_dist > 0:
                                qty = (wallet * 0.01) / risk_dist
                                if (qty * entry) > (wallet * cfg['lev']):
                                    qty = (wallet * cfg['lev']) / entry
                                tp1 = entry + (risk_dist * 2.0)
                                tp2 = entry + (risk_dist * 5.0)
                                pos = {'side': 'LONG', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}
                        elif short_trigger:
                            entry = bar['c']
                            # 止損錨定於 OB 高點或波段高點外側 + 0.2% 緩衝
                            sl_anchor = max(ict_info['ob_bear_high'], h_wave)
                            sl = sl_anchor * (1.0 + 0.002)
                            risk_dist = sl - entry
                            if risk_dist > 0:
                                qty = (wallet * 0.01) / risk_dist
                                if (qty * entry) > (wallet * cfg['lev']):
                                    qty = (wallet * cfg['lev']) / entry
                                tp1 = entry - (risk_dist * 2.0)
                                tp2 = entry - (risk_dist * 5.0)
                                pos = {'side': 'SHORT', 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'qty': qty}

        tot_t = len(completed_trades)
        wins = sum(1 for t in completed_trades if t['pnl'] > 0)
        wr = (wins / tot_t * 100) if tot_t > 0 else 0.0
        net_pnl = wallet - INITIAL_WALLET_PER_ASSET
        roi = (net_pnl / INITIAL_WALLET_PER_ASSET) * 100

        asset_results[sym] = {
            'total': tot_t, 'wins': wins, 'wr': wr, 'final_wallet': wallet, 'net_pnl': net_pnl, 'roi': roi
        }

    report_lines = [
        "```text",
        f"【多資產獨立 100U ICT/SMC Pro 沙盒回測報告 - {period_title}】",
        "--------------------------------------------------------------------",
        "資金配置: 每種標的各自獨立 100.0 USDT 帳戶",
        "加密貨幣: BTC, ETH, SOL, BNB, DOGE (1%風控 / 10x槓桿 / 流動性+OB+FVG+OTE)",
        "貴金屬:   XAU (5% 風控 / 10x 槓桿 / 4H 唐奇安策略)",
        "--------------------------------------------------------------------",
        "各標的獨立帳戶績效排序:"
    ]
    
    for sym in sorted_symbols:
        if sym in asset_results:
            st = asset_results[sym]
            report_lines.append(f" - {sym.ljust(5)} | 次數: {str(st['total']).ljust(3)} 筆 | 勝率: {st['wr']:6.2f}% | 最終餘額: ${st['final_wallet']:7.2f} ({st['roi']:+.2f}%)")
    
    report_lines.append("```")
    report = "\n".join(report_lines)
    
    print(report)
    send_discord(report)

if __name__ == '__main__':
    run_independent_sandbox_backtest()
