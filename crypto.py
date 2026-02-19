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

@st.cache_data(ttl=3600) # จำค่าเงินไว้ 1 ชม. เพื่อลดภาระ API
def get_live_exchange_rate():
    try:
        ticker = yf.Ticker("THB=X")
        return round(ticker.fast_info['last_price'], 2)
    except: return 35.0

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
        
        # ลด n_estimators เหลือ 25 เพื่อให้คำนวณไวขึ้นแต่ยังแม่นยำ
        model = RandomForestRegressor(n_estimators=25, random_state=42)
        model.fit(X.values, y.values)
        
        last_row = df.iloc[[-1]]
        cur_p = float(last_row['Close'].iloc[0])
        score = 0
        
        # 1. เช็คเทรนด์ (50 คะแนน)
        if cur_p > float(last_row['EMA_20'].iloc[0]) > float(last_row['EMA_50'].iloc[0]):
            score += 50
        # 2. เช็คแรงซื้อที่ไม่ Overbought (30 คะแนน)
        if 40 < float(last_row['RSI_14'].iloc[0]) < 68:
            score += 30
        # 3. เช็คการพยากรณ์ราคา (20 คะแนน)
        pred_p = model.predict(last_row[['Close', 'RSI_14', 'EMA_20', 'EMA_50']].values)[0]
        if pred_p > cur_p:
            score += 20
        
        return {"Symbol": symbol, "Price_USD": cur_p, "Score": score}
    except: return None

# --- 3. UI Logic ---

sheet = init_gsheet()
live_rate = get_live_exchange_rate()
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
                # เช็คเหรียญที่ถืออยู่
                h_rows = df_perf[df_perf['สถานะ'] == 'HUNTING']
                if not h_rows.empty: hunting_symbol = h_rows.iloc[-1]['เหรียญ']
    except: pass

# Sidebar
st.sidebar.title("🦔 Pepper Stealth Bot")
init_money = st.sidebar.number_input("งบตั้งต้น", value=1000.0)
profit_goal = st.sidebar.number_input("กำไรเป้าหมาย", value=10000.0)

# Dashboard
st.title("🦔 Pepper Hunter: Stealth Dashboard")
m1, m2, m3 = st.columns(3)
m1.metric("งบปัจจุบัน", f"{current_bal:,.2f} ฿")
m2.metric("เป้าหมาย", f"{init_money + profit_goal:,.2f} ฿")
m3.metric("สถานะ", "HUNTING 🎯" if hunting_symbol else "SCANNING 🔍")

st.divider()

# --- 4. Radar Logic (แบบเห็นผลไว) ---
tickers = ["SOL-USD", "NEAR-USD", "RENDER-USD", "FET-USD", "LINK-USD", "DOT-USD", "XRP-USD", "ADA-USD", "BTC-USD", "ETH-USD", "SUI-USD"]
cols = st.columns(4)
all_results = []

# ใช้ container เพื่อความไหลลื่นของ UI
with st.container():
    for i, sym in enumerate(tickers):
        # สุ่มดีเลย์สั้นๆ (0.1 - 0.5 วินาที) เพื่อพรางตัวจากการ Request ถี่เกินไป
        time.sleep(random.uniform(0.1, 0.5))
        
        df_h = yf.download(sym, period="60d", interval="1d", progress=False)
        res = analyze_coin_ai(sym, df_h)
        
        if res:
            price_thb = res['Price_USD'] * live_rate
            all_results.append(res)
            
            with cols[i % 4]:
                color = "#FF4B4B" if sym == hunting_symbol else "#4CAF50"
                st.markdown(f"""
                <div style="border: 1px solid {color}; padding: 10px; border-radius: 10px; text-align: center;">
                    <p style="margin:0; font-size: 0.8em; color: gray;">{sym}</p>
                    <h2 style="margin:0; color: {color};">{res['Score']}</h2>
                    <p style="margin:0; font-weight: bold;">{price_thb:,.2f} ฿</p>
                </div>
                """, unsafe_allow_html=True)

# --- 5. Stealth Re-run ---
# สุ่มเวลาพักระหว่าง 45-90 วินาที เพื่อไม่ให้ความถี่ในการเข้าเว็บ Yahoo เท่ากันเป๊ะทุกครั้ง
wait_time = random.randint(45, 90)
st.write(f"🕒 จะสแกนรอบถัดไปในอีก {wait_time} วินาที...")
time.sleep(wait_time)
st.rerun()
