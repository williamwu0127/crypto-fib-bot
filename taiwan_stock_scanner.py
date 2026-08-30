                # ----------------- 升級版：妖股潛伏與起漲前夕獵人 -----------------
                # 條件 1：前 20 日處於箱體整理（高低價差不大），但今日成交量突然爆發（量比 >= 2.5）
                # 條件 2：今日收盤剛好站上近 20 日整理區間的上緣（蓄勢待發的突破瞬間）
                # 條件 3：成交金額適中（>= 0.8 億），確保有流動性可進場
                
                recent_high_20d = float(high_s.iloc[-21:-1].max())
                recent_low_20d = float(low_s.iloc[-21:-1].min())
                box_range_pct = (recent_high_20d - recent_low_20d) / recent_low_20d # 箱體震盪幅度
                
                is_accumulating_box = box_range_pct <= 0.20 # 過去一個月在 20% 內狹幅震盪整理
                is_pre_monster_vol = vol_ma5 > 0 and (today_vol / vol_ma5) >= 2.5 # 突然爆量 2.5 倍以上
                is_breakout_edge = today_close >= recent_high_20d * 0.98 # 準備或剛突破箱體上緣
                
                if est_money_mil >= 0.8 and is_accumulating_box and is_pre_monster_vol and is_breakout_edge:
                    monster_stocks.append({
                        "sid": sid,
                        "name": name,
                        "industry": industry,
                        "close": f"{today_close:.2f}",
                        "vol_ratio": round(today_vol / vol_ma5, 1)
                    })
