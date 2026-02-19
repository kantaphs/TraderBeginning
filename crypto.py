import streamlit as st
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import gspread
import time
import random
import numpy as np
from google.oauth2.service_account import Credentials
from sklearn.ensemble import RandomForestRegressor
from datetime import datetime, timedelta, timezone

# --- 1. การตั้งค่าหน้าจอ ---
st.set_page_config(page_title="🦔 Pepper Hunter: Trend Hunter", layout="wide")

# --- 2. ฟังก์ชันสนับสนุน ---

def init_gsheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        sh = client.open("Blue-chip Bet")
        return sh.worksheet("trade_learning")
    except Exception as e:
        st.error(f"❌ เชื่อมต่อ Sheet ไม่ได้: {e}")
        return None

def get_now_thailand():
    now = datetime.now(timezone(timedelta(hours=7)))
    return now.strftime("%d/%m/%Y %H:%M:%S")

def get_live_exchange_rate():
    try:
        ticker = yf.Ticker("THB=X")
        return round(ticker.fast_info['last_price'], 2)
    except: return 35.0

def get_bot_status(sheet):
    try:
        val = sheet.cell(2, 11).value # Bot_Status อยู่คอลัมน์ K (11)
        return val == "ON"
    except: return False

def set_bot_status(sheet, status):
    try:
        val = "ON" if status else "OFF"
        sheet.update_cell(2, 11, val)
    except: pass

def get_top_safe_tickers():
    return ["SOL-USD", "NEAR-USD", "RENDER-USD", "FET-USD", "LINK-USD", "DOT-USD", "XRP-USD", "ADA-USD", "BTC-USD", "ETH-USD", "BNB-USD", "SUI-USD"]

def analyze_coin_ai(symbol, df_history):
    try:
        df = df_history.copy()
        if len(df) < 50: return None
        df.ta.rsi(length=14, append=True)
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df = df.dropna()
        
        X = df[['Close', 'RSI_14', 'EMA_20', 'EMA_50']].iloc[:-1]
        y = df['Close'].shift(-1).iloc[:-1]
        model = RandomForestRegressor(n_estimators=50, random_state=42)
        model.fit(X.values, y.values)
        
        last_row = df.iloc[[-1]]
        cur_p = float(last_row['Close'].iloc[0])
        score = 0
        if cur_p > float(last_row['EMA_20'].iloc[0]) > float(last_row['EMA_50'].iloc[0]): score += 50
        if 40 < float(last_row['RSI_14'].iloc[0]) < 65: score += 30
        pred_p = model.predict(last_row[['Close', 'RSI_14', 'EMA_20', 'EMA_50']].values)[0]
        if pred_p > cur_p: score += 20
        
        return {"Symbol": symbol, "Price_USD": cur_p, "Score": score}
    except: return None

# --- 3. UI & Logic ---

sheet = init_gsheet()
live_rate = get_live_exchange_rate()
current_bal = 1000.0
df_perf = pd.DataFrame()

# ดึงข้อมูลจาก Sheet และหาเหรียญที่ถืออยู่ (HUNTING)
current_hunt = None
current_row_idx = None

if sheet:
    try:
        recs = sheet.get_all_records()
        if recs:
            df_perf = pd.DataFrame(recs)
            if not df_perf.empty:
                # หา Balance ล่าสุด
                if 'Balance' in df_perf.columns:
                    val = df_perf.iloc[-1]['Balance']
                    if val != "": current_bal = float(val)
                
                # เช็คว่ามีเหรียญสถานะ HUNTING ไหม
                hunting_rows = df_perf[df_perf['สถานะ'] == 'HUNTING']
                if not hunting_rows.empty:
                    current_hunt = hunting_rows.iloc[-1].to_dict()
                    current_row_idx = hunting_rows.index[-1] + 2 # Google Sheet index
    except: pass

# Sidebar
init_money = st.sidebar.number_input("งบตั้งต้น (บาท)", value=1000.0)
profit_goal = st.sidebar.number_input("กำไรที่ต้องการ (บาท)", value=10000.0)
trailing_pct = st.sidebar.slider("Trailing Stop (%)", 1.0, 10.0, 5.0)
st.sidebar.metric("ค่าเงิน USD/THB (Live)", f"{live_rate} ฿")

bot_active = get_bot_status(sheet) if sheet else False
if st.sidebar.button("START" if not bot_active else "STOP"):
    if sheet:
        set_bot_status(sheet, not bot_active)
        st.rerun()

# Dashboard
st.title("🦔 Pepper Hunter: Trend Hunter")
target_total = init_money + profit_goal
profit_now = current_bal - init_money

m1, m2, m3 = st.columns(3)
m1.metric("งบปัจจุบัน", f"{current_bal:,.2f} ฿", f"{profit_now:,.2f} ฿")
m2.metric("เป้าหมายเส้นชัย", f"{target_total:,.2f} ฿")
m3.metric("สถานะบอท", "HUNTING 🔥" if current_hunt else ("RUNNING 🟢" if bot_active else "IDLE 🔴"))

st.divider()

if bot_active:
    # --- กรณีที่ 1: กำลังถือเหรียญ (ล่าอยู่) ---
    if current_hunt:
        st.subheader(f"🎯 กำลังล่า: {current_hunt['เหรียญ']}")
        ticker_now = yf.Ticker(current_hunt['เหรียญ'])
        price_usd = ticker_now.fast_info['last_price']
        price_thb = price_usd * live_rate
        
        # คำนวณกำไรและขยับ Trailing Stop (ใช้ Headline เก็บ High)
        entry_p = float(current_hunt['ราคาซื้อ(฿)'])
        diff_pct = ((price_thb - entry_p) / entry_p) * 100
        
        try: last_high = float(current_hunt['Headline']) if current_hunt['Headline'] != "" else price_thb
        except: last_high = price_thb
        
        new_high = max(last_high, price_thb)
        stop_price = new_high * (1 - (trailing_pct / 100))
        
        c1, c2, c3 = st.columns(3)
        c1.metric("ราคาปัจจุบัน", f"{price_thb:,.2f} ฿", f"{diff_pct:.2f}%")
        c2.metric("จุดขาย (Trailing)", f"{stop_price:,.2f} ฿")
        c3.metric("ราคาสูงสุด", f"{new_high:,.2f} ฿")

        # อัปเดตข้อมูลลง Sheet
        sheet.update_cell(current_row_idx, 6, f"{diff_pct:.2f}%") # กำไร%
        sheet.update_cell(current_row_idx, 10, round(new_high, 2)) # Headline
        
        # เงื่อนไขการขาย
        if price_thb <= stop_price:
            st.warning("🚨 หลุดจุด Trailing Stop! กำลังขาย...")
            sheet.update_cell(current_row_idx, 3, "SOLD")
            sheet.update_cell(current_row_idx, 5, round(price_thb, 2))
            sheet.update_cell(current_row_idx, 8, round(price_thb * float(current_hunt['จำนวน']), 2))
            time.sleep(2)
            st.rerun()

    # --- กรณีที่ 2: มือว่าง กำลังสแกนหาตัวใหม่ ---
    else:
        st.subheader("🔍 AI Watchlist & Scanning")
        watchlist = []
        tickers = get_top_safe_tickers()
        
        with st.status("AI กำลังสแกนตลาด...", expanded=True):
            for sym in tickers:
                df_h = yf.download(sym, period="60d", interval="1d", progress=False)
                res = analyze_coin_ai(sym, df_h)
                if res:
                    price_thb = res['Price_USD'] * live_rate
                    # เพิ่มเข้า Watchlist ถ้าเงินพอซื้อ
                    if current_bal >= (price_thb * 0.01): # ขั้นต่ำ 1% ของเหรียญ
                        watchlist.append({
                            "Symbol": sym, "Price_THB": price_thb, "Score": res['Score']
                        })
        
        # แสดง Watchlist
        if watchlist:
            watchlist = sorted(watchlist, key=lambda x: x['Score'], reverse=True)
            cols = st.columns(4)
            for i, item in enumerate(watchlist[:4]):
                with cols[i]:
                    st.metric(item['Symbol'], f"{item['Score']} pts", f"{item['Price_THB']:,.0f} ฿", delta_color="normal")
            
            # ตรวจสอบจุดซื้อ (Score >= 85)
            best_pick = watchlist[0]
            if best_pick['Score'] >= 85:
                st.success(f"🔥 พบช้างตัวใหญ่! กำลังเข้าซื้อ {best_pick['Symbol']}")
                qty = current_bal / best_pick['Price_THB']
                new_row = [
                    get_now_thailand(), best_pick['Symbol'], "HUNTING", 
                    round(best_pick['Price_THB'], 2), "", "0%", 
                    best_pick['Score'], round(current_bal, 2), qty, round(best_pick['Price_THB'], 2)
                ]
                sheet.append_row(new_row)
                time.sleep(2)
                st.rerun()

    time.sleep(60)
    st.rerun()

# กราฟพอร์ต
if not df_perf.empty:
    st.subheader("📉 Performance Chart")
    chart_data = df_perf[df_perf['Balance'] != ""].copy()
    if 'วันที่' in chart_data.columns:
        chart_data['วันที่'] = pd.to_datetime(chart_data['วันที่'], format="%d/%m/%Y %H:%M:%S")
        st.line_chart(chart_data.set_index('วันที่')['Balance'])
