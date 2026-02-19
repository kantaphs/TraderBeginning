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

def get_live_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        return ticker.fast_info['last_price']
    except: return None

def get_live_exchange_rate():
    try:
        ticker = yf.Ticker("THB=X")
        return round(ticker.fast_info['last_price'], 2)
    except: return 35.0

# --- 3. Logic สายล่า (Trend Hunter) ---

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
        ema20 = float(last_row['EMA_20'].iloc[0])
        ema50 = float(last_row['EMA_50'].iloc[0])
        rsi = float(last_row['RSI_14'].iloc[0])
        
        score = 0
        if cur_p > ema20 > ema50: score += 50
        if 40 < rsi < 70: score += 30
        pred_p = model.predict(last_row[['Close', 'RSI_14', 'EMA_20', 'EMA_50']].values)[0]
        if pred_p > cur_p: score += 20
        
        return {"Symbol": symbol, "Price_USD": cur_p, "Score": score, "EMA20_USD": ema20}
    except: return None

# --- 4. Main UI & Loop ---

sheet = init_gsheet()
live_rate = get_live_exchange_rate()

# ดึงข้อมูลทั้งหมดจาก Sheet
data = sheet.get_all_records() if sheet else []
df_perf = pd.DataFrame(data)

# ตรวจสอบสถานะบอท (Column K แถว 2)
bot_active = False
if sheet:
    try: bot_active = sheet.cell(2, 11).value == "ON"
    except: pass

# ตรวจสอบว่ามีเหรียญที่ถืออยู่ไหม (สถานะ 'HUNTING')
current_hunt = None
if not df_perf.empty:
    hunting_rows = df_perf[df_perf['สถานะ'] == 'HUNTING']
    if not hunting_rows.empty:
        current_hunt = hunting_rows.iloc[-1].to_dict()
        # หาตำแหน่งแถวใน Google Sheet (index + 2 เพราะ row 1 คือ header และ index เริ่มที่ 0)
        current_row_idx = hunting_rows.index[-1] + 2 

# Sidebar
st.sidebar.title("🌲 Hunter Settings")
init_money = st.sidebar.number_input("งบตั้งต้น (บาท)", value=1000.0)
trailing_percent = st.sidebar.slider("Trailing Stop (%)", 1.0, 10.0, 5.0)

if st.sidebar.button("START" if not bot_active else "STOP"):
    if sheet:
        sheet.update_cell(2, 11, "ON" if not bot_active else "OFF")
        st.rerun()

# Dashboard Header
st.title("🦔 Pepper Hunter: Trend Hunter")
m1, m2, m3 = st.columns(3)
cur_bal = float(df_perf.iloc[-1]['Balance']) if not df_perf.empty else init_money
m1.metric("งบปัจจุบัน", f"{cur_bal:,.2f} ฿")
m2.metric("สถานะ", "ON 🔥" if bot_active else "OFF ❄️")
m3.metric("โหมด", "สายล่า (Trend)")

st.divider()

if bot_active:
    # --- กรณีที่ 1: กำลังล่าเหรียญอยู่ (HUNTING) ---
    if current_hunt:
        st.subheader(f"🎯 กำลังล่า: {current_hunt['เหรียญ']}")
        price_usd = get_live_price(current_hunt['เหรียญ'])
        if price_usd:
            price_thb = price_usd * live_rate
            diff_pct = ((price_thb - current_hunt['ราคาซื้อ(฿)']) / current_hunt['ราคาซื้อ(฿)']) * 100
            
            # คำนวณ Trailing Stop (ใช้ Headline เก็บราคาสูงสุดชั่วคราว)
            try: last_high = float(current_hunt['Headline']) if current_hunt['Headline'] != "" else price_thb
            except: last_high = price_thb
            
            new_high = max(last_high, price_thb)
            stop_price = new_high * (1 - (trailing_percent / 100))
            
            # แสดงผลการล่า
            c1, c2, c3 = st.columns(3)
            c1.metric("ราคาปัจจุบัน", f"{price_thb:,.2f} ฿", f"{diff_pct:.2f}%")
            c2.metric("จุดขาย (Trailing Stop)", f"{stop_price:,.2f} ฿")
            c3.metric("ราคาสูงสุดที่เคยทำได้", f"{new_high:,.2f} ฿")

            # อัปเดตข้อมูลลง Sheet (Real-time tracking)
            sheet.update_cell(current_row_idx, 6, f"{diff_pct:.2f}%") # กำไร%
            sheet.update_cell(current_row_idx, 8, round(price_thb * current_hunt['จำนวน'], 2)) # Balance
            sheet.update_cell(current_row_idx, 10, round(new_high, 2)) # Headline (เก็บ High)

            # เงื่อนไขการขาย: ราคาหลุด Trailing Stop
            if price_thb <= stop_price:
                st.warning("⚠️ เทรนด์เริ่มจบ... กำลังขายปิดดีล")
                final_bal = price_thb * current_hunt['จำนวน']
                sheet.update_cell(current_row_idx, 3, "SOLD") # สถานะ
                sheet.update_cell(current_row_idx, 5, round(price_thb, 2)) # ราคาขาย
                time.sleep(2)
                st.rerun()
    
    # --- กรณีที่ 2: มือว่าง กำลังสแกนหาตัวใหม่ ---
    else:
        st.subheader("🔍 กำลังสแกนหาช้างตัวใหญ่...")
        tickers = ["SOL-USD", "NEAR-USD", "RENDER-USD", "FET-USD", "LINK-USD", "DOT-USD", "XRP-USD"]
        found_coin = None
        
        with st.status("AI กำลังวิเคราะห์ตลาด...", expanded=True):
            for sym in tickers:
                df_h = yf.download(sym, period="60d", interval="1d", progress=False)
                res = analyze_coin_ai(sym, df_h)
                if res and res['Score'] >= 85:
                    found_coin = res
                    st.write(f"✅ พบสัญญาณซื้อ: {sym} (Score: {res['Score']})")
                    break # สายล่าเลือกทีละตัว All-in
        
        if found_coin:
            # คำนวณจำนวนที่ซื้อได้
            buy_price_thb = found_coin['Price_USD'] * live_rate
            qty = cur_bal / buy_price_thb
            
            # บันทึกการซื้อลง Sheet
            new_row = [
                get_now_thailand(), 
                found_coin['Symbol'], 
                "HUNTING", 
                round(buy_price_thb, 2), 
                "", 
                "0%", 
                found_coin['Score'], 
                round(cur_bal, 2), 
                qty, 
                round(buy_price_thb, 2) # Headline เก็บ High เริ่มต้น
            ]
            sheet.append_row(new_row)
            st.success(f"🚀 เริ่มล่า {found_coin['Symbol']} เรียบร้อย!")
            time.sleep(2)
            st.rerun()

    # หน่วงเวลา Loop
    time.sleep(30)
    st.rerun()

# --- 5. Portfolio Chart ---
if not df_perf.empty:
    st.subheader("📉 ประวัติการล่า")
    chart_df = df_perf[df_perf['Balance'] != ""].copy()
    if 'วันที่' in chart_df.columns:
        chart_df['วันที่'] = pd.to_datetime(chart_df['วันที่'], format="%d/%m/%Y %H:%M:%S")
        st.line_chart(chart_df.set_index('วันที่')['Balance'])
