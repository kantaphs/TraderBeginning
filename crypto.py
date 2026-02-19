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
st.set_page_config(page_title="🦔 Pepper Hunter", layout="wide")

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
        price = ticker.fast_info['last_price']
        return round(price, 2)
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

# --- 3. UI & Control Logic ---

sheet = init_gsheet()
df_perf = pd.DataFrame()

# Sidebar Setup
init_money = st.sidebar.number_input("งบตั้งต้น (บาท)", value=1000.0)
profit_goal = st.sidebar.number_input("กำไรที่ต้องการ (บาท)", value=10000.0)
live_rate = get_live_exchange_rate()
st.sidebar.metric("ค่าเงิน USD/THB (Live)", f"{live_rate} ฿")
st.sidebar.write(f"🕒 อัปเดตล่าสุด: {get_now_thailand()}")

# ดึงข้อมูลสถานะปัจจุบันจาก Sheet
current_bal = init_money
hunting_symbol = None

if sheet:
    try:
        recs = sheet.get_all_records()
        if recs:
            df_perf = pd.DataFrame(recs)
            if not df_perf.empty:
                # อัปเดต Balance จากแถวล่าสุด
                if 'Balance' in df_perf.columns:
                    val = df_perf.iloc[-1]['Balance']
                    if val != "" and val != 0: current_bal = float(val)
                
                # ตรวจสอบว่ามีเหรียญไหนที่สถานะเป็น HUNTING หรือไม่
                hunting_rows = df_perf[df_perf['สถานะ'] == 'HUNTING']
                if not hunting_rows.empty:
                    hunting_symbol = hunting_rows.iloc[-1]['เหรียญ']
    except: pass

bot_active = get_bot_status(sheet) if sheet else False
if st.sidebar.button("START" if not bot_active else "STOP"):
    if sheet:
        set_bot_status(sheet, not bot_active)
        st.rerun()

# Dashboard Header
st.title("🦔 Pepper Hunter")
target_total = init_money + profit_goal
profit_now = current_bal - init_money

m1, m2, m3 = st.columns(3)
m1.metric("งบปัจจุบัน", f"{current_bal:,.2f} ฿", f"{profit_now:,.2f} ฿")
m2.metric("เป้าหมายเส้นชัย", f"{target_total:,.2f} ฿")
m3.metric("สถานะบอท", "RUNNING 🟢" if bot_active else "IDLE 🔴")

st.divider()

# --- ส่วนการแสดงผลเหรียญ (Radar) ---
st.subheader(f"📡 Market Radar & AI Analysis")
tickers = get_top_safe_tickers()
all_results = []

# ใช้ Status Spinner เพื่อความสวยงามระหว่างวิเคราะห์
with st.status("AI กำลังวิเคราะห์สัญญาณเทรนด์...", expanded=False):
    for sym in tickers:
        df_h = yf.download(sym, period="60d", interval="1d", progress=False)
        if not df_h.empty:
            res = analyze_coin_ai(sym, df_h)
            if res:
                price_thb = res['Price_USD'] * live_rate
                all_results.append({
                    "Symbol": sym,
                    "Price_THB": price_thb,
                    "Score": res['Score'],
                    "is_hunting": (sym == hunting_symbol)
                })

# เรียงลำดับตาม Score สูงสุด
all_results = sorted(all_results, key=lambda x: x['Score'], reverse=True)

# แสดงผลแบบ Grid (4 คอลัมน์)
cols = st.columns(4)
for i, coin in enumerate(all_results):
    with cols[i % 4]:
        # ใส่ Icon เป้าเล็งถ้ากำลังถืออยู่
        title = f"{coin['Symbol']} 🎯" if coin['is_hunting'] else coin['Symbol']
        
        # กล่องข้อมูลเหรียญ
        st.markdown(f"""
        <div style="border: 1px solid {'#FF4B4B' if coin['is_hunting'] else '#4CAF50'}; 
                    padding: 10px; border-radius: 10px; background-color: #1E1E1E;">
            <h4 style="margin:0;">{title}</h4>
            <h2 style="margin:5px 0; color: {'#FF4B4B' if coin['Score'] >= 80 else '#4CAF50'};">
                {coin['Score']} <small style="font-size:0.5em;">pts</small>
            </h2>
            <p style="margin:0; font-size: 0.9em;">ราคา: {coin['Price_THB']:,.2f} ฿</p>
        </div>
        """, unsafe_allow_html=True)
        st.write("") # เว้นช่องไฟ

st.divider()

# Logic การทำงานเบื้องหลัง
if bot_active:
    # ตรวจสอบจุดซื้อ (กรณีมือว่าง)
    if not hunting_symbol:
        best_pick = all_results[0]
        if best_pick['Score'] >= 85:
            st.success(f"🚀 พบสัญญาณซื้อ! กำลังล่า {best_pick['Symbol']}")
            # ในที่นี้คุณสามารถเพิ่มโค้ด append_row เพื่อเริ่มซื้อใน Sheet ได้เลย
            
    # หน่วงเวลา Rerun
    time.sleep(60)
    st.rerun()

# กราฟพอร์ต
if not df_perf.empty:
    st.subheader("📉 ประวัติพอร์ตโฟลิโอ")
    if 'Timestamp' in df_perf.columns: # หรือ 'วันที่' ตามหัวข้อใน Sheet คุณ
        chart_col = 'วันที่' if 'วันที่' in df_perf.columns else 'Timestamp'
        df_perf[chart_col] = pd.to_datetime(df_perf[chart_col], errors='coerce')
        st.line_chart(df_perf.set_index(chart_col)['Balance'])
    else:
        st.line_chart(df_perf['Balance'])
