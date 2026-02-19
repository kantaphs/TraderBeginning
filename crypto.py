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
st.set_page_config(page_title="🦔 Pepper Hunter: Turbo", layout="wide")

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
        val = sheet.cell(2, 11).value
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
        model = RandomForestRegressor(n_estimators=20, random_state=42) # ลด n เพื่อความเร็ว
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

# --- 3. UI & Control Logic ---

sheet = init_gsheet()
current_bal = 1000.0
df_perf = pd.DataFrame()
hunting_symbol = None

if sheet:
    try:
        recs = sheet.get_all_records()
        if recs:
            df_perf = pd.DataFrame(recs)
            if not df_perf.empty:
                if 'Balance' in df_perf.columns:
                    val = df_perf.iloc[-1]['Balance']
                    if val != "": current_bal = float(val)
                # เช็คว่ามีตัวไหนถืออยู่ไหม (HUNTING)
                h_rows = df_perf[df_perf['สถานะ'] == 'HUNTING']
                if not h_rows.empty:
                    hunting_symbol = h_rows.iloc[-1]['เหรียญ']
    except: pass

# Sidebar
init_money = st.sidebar.number_input("งบตั้งต้น (บาท)", value=1000.0)
profit_goal = st.sidebar.number_input("กำไรที่ต้องการ (บาท)", value=10000.0)
live_rate = get_live_exchange_rate()
st.sidebar.metric("ค่าเงิน USD/THB", f"{live_rate} ฿")

bot_active = get_bot_status(sheet) if sheet else False
if st.sidebar.button("START" if not bot_active else "STOP"):
    if sheet:
        set_bot_status(sheet, not bot_active)
        st.rerun()

# Dashboard
st.title("🦔 Pepper Hunter: Radar")
target_total = init_money + profit_goal
profit_now = current_bal - init_money

m1, m2, m3 = st.columns(3)
m1.metric("งบปัจจุบัน", f"{current_bal:,.2f} ฿", f"{profit_now:,.2f} ฿")
m2.metric("เป้าหมาย", f"{target_total:,.2f} ฿")
m3.metric("สถานะบอท", "RUNNING 🟢" if bot_active else "IDLE 🔴")

st.divider()

# --- ส่วน Radar แสดงผลเหรียญ (โชว์ทันที) ---
st.subheader(f"📡 Hunter's Radar ({get_now_thailand()})")
tickers = get_top_safe_tickers()

# สร้าง columns รอไว้
cols = st.columns(4)
all_picks = []

# สแกนทีละตัวและโชว์ทันที
for i, sym in enumerate(tickers):
    with st.spinner(f"กำลังวิเคราะห์ {sym}..."):
        df_h = yf.download(sym, period="60d", interval="1d", progress=False)
        if not df_h.empty:
            res = analyze_coin_ai(sym, df_h)
            if res:
                price_thb = res['Price_USD'] * live_rate
                is_hunting = (sym == hunting_symbol)
                
                # โชว์ Card ทันทีใน Column
                with cols[i % 4]:
                    border = "2px solid #FF4B4B" if is_hunting else "1px solid #4CAF50"
                    label = f"{sym} 🎯" if is_hunting else sym
                    st.markdown(f"""
                    <div style="border: {border}; padding: 15px; border-radius: 10px; background-color: #1E1E1E; text-align: center; margin-bottom: 10px;">
                        <h3 style="margin:0;">{label}</h3>
                        <h1 style="margin:5px 0; color: {'#FF4B4B' if res['Score'] >= 85 else '#4CAF50'};">{res['Score']}</h1>
                        <p style="margin:0; font-size: 0.9em;">{price_thb:,.2f} ฿</p>
                    </div>
                    """, unsafe_allow_html=True)
                
                all_picks.append(res)

st.divider()

# Logic การทำงาน (ถ้าบอทเปิดอยู่)
if bot_active:
    # ตรวจสอบเงื่อนไขซื้อ (กรณีมือว่าง)
    if not hunting_symbol and all_picks:
        top_pick = sorted(all_picks, key=lambda x: x['Score'], reverse=True)[0]
        if top_pick['Score'] >= 85:
            st.success(f"🔥 สัญญาณซื้อ {top_pick['Symbol']}!")
            # ตรงนี้คุณสามารถเพิ่มโค้ดบันทึกลง Sheet ได้
            
    time.sleep(60)
    st.rerun()

# กราฟพอร์ต
if not df_perf.empty:
    st.subheader("📉 พอร์ตโฟลิโอ")
    st.line_chart(df_perf['Balance'])
