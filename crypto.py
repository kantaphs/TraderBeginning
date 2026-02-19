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
    return datetime.now(timezone(timedelta(hours=7))).strftime("%d/%m/%Y %H:%M:%S")

@st.cache_data(ttl=600)
def get_live_exchange_rate():
    try:
        ticker = yf.Ticker("THB=X")
        return round(ticker.fast_info['last_price'], 2)
    except: return 35.0

def get_bot_status(sheet):
    try:
        # อ่านจากคอลัมน์ K (Bot_Status) แถวที่ 2
        val = sheet.cell(2, 11).value
        return val == "ON"
    except: return False

def set_bot_status(sheet, status):
    try:
        val = "ON" if status else "OFF"
        sheet.update_cell(2, 11, val)
    except: pass

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
        model = RandomForestRegressor(n_estimators=25, random_state=42)
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

# --- 3. UI & Control ---

sheet = init_gsheet()
live_rate = get_live_exchange_rate()
current_bal = 1000.0
df_perf = pd.DataFrame()
hunting_symbol = None
entry_price_thb = 0
current_qty = 0

if sheet:
    try:
        recs = sheet.get_all_records()
        if recs:
            df_perf = pd.DataFrame(recs)
            if not df_perf.empty:
                # ดึง Balance ล่าสุด
                if 'Balance' in df_perf.columns:
                    val = df_perf.iloc[-1]['Balance']
                    if val != "" and val != None: current_bal = float(val)
                
                # เช็คสถานะการถือครอง (HUNTING)
                h_rows = df_perf[df_perf['สถานะ'] == 'HUNTING']
                if not h_rows.empty:
                    hunting_symbol = h_rows.iloc[-1]['เหรียญ']
                    entry_price_thb = float(h_rows.iloc[-1]['ราคาซื้อ(฿)'])
                    current_qty = float(h_rows.iloc[-1]['จำนวน'])
    except: pass

# Sidebar
st.sidebar.title("🦔 Pepper Hunter")
init_money = st.sidebar.number_input("งบตั้งต้น (฿)", value=1000.0)
bot_active = get_bot_status(sheet) if sheet else False

if st.sidebar.button("START BOT" if not bot_active else "STOP BOT"):
    if sheet:
        set_bot_status(sheet, not bot_active)
        st.rerun()

# Dashboard
st.title("🦔 Pepper Hunter: Simulation")
m1, m2, m3 = st.columns(3)
m1.metric("งบปัจจุบัน", f"{current_bal:,.2f} ฿", f"{(current_bal-init_money):,.2f}")
m2.metric("สถานะพอร์ต", hunting_symbol if hunting_symbol else "ว่าง (Scanning)")
m3.metric("สถานะบอท", "RUNNING 🟢" if bot_active else "IDLE 🔴")

st.divider()

# --- 4. Radar & Logic ---
tickers = ["SOL-USD", "NEAR-USD", "RENDER-USD", "FET-USD", "LINK-USD", "DOT-USD", "XRP-USD", "ADA-USD"]
all_results = []
cols = st.columns(4)

for i, sym in enumerate(tickers):
    df_h = yf.download(sym, period="60d", interval="1d", progress=False)
    res = analyze_coin_ai(sym, df_h)
    
    if res:
        price_thb = res['Price_USD'] * live_rate
        all_results.append(res)
        is_hunting = (sym == hunting_symbol)
        
        with cols[i % 4]:
            color = "#FF4B4B" if is_hunting else "#4CAF50"
            st.markdown(f"""
            <div style="border: 2px solid {color}; padding: 10px; border-radius: 10px; text-align: center;">
                <h4 style="margin:0;">{sym} {'🎯' if is_hunting else ''}</h4>
                <h1 style="margin:0; color: {color};">{res['Score']}</h1>
                <p style="margin:0;">{price_thb:,.2f} ฿</p>
            </div>
            """, unsafe_allow_html=True)

# --- 5. หัวใจสำคัญ: ระบบซื้อขายจำลองลง Sheet (11 คอลัมน์) ---
if bot_active and sheet:
    now_str = get_now_thailand()
    
    # กรณี "มือว่าง" -> หาเหรียญซื้อ
    if not hunting_symbol:
        buy_candidates = sorted([r for r in all_results if r['Score'] >= 85], key=lambda x: x['Score'], reverse=True)
        if buy_candidates:
            target = buy_candidates[0]
            buy_p = target['Price_USD'] * live_rate
            qty = current_bal / buy_p # ซื้อหมดหน้าตัก
            
            # บันทึก: วันที่, เหรียญ, สถานะ, ราคาซื้อ(฿), ราคาขาย(฿), กำไร%, Score, Balance, จำนวน, Headline, Bot_Status
            row = [now_str, target['Symbol'], "HUNTING", buy_p, 0, "0%", target['Score'], current_bal, qty, "AI Found Strong Trend", "ON"]
            sheet.append_row(row)
            st.success(f"🚀 ซื้อ {target['Symbol']} เข้าพอร์ตเรียบร้อย!")
            time.sleep(2)
            st.rerun()

    # กรณี "มีของ" -> เช็คจุดขาย
    else:
        current_data = next((r for r in all_results if r['Symbol'] == hunting_symbol), None)
        if current_data:
            sell_p = current_data['Price_USD'] * live_rate
            profit_pct = ((sell_p - entry_price_thb) / entry_price_thb) * 100
            new_bal = current_qty * sell_p
            
            # เงื่อนไขขาย: Score ต่ำกว่า 40 หรือกำไร/ขาดทุนถึงจุดที่รับได้
            if current_data['Score'] < 40 or profit_pct < -5.0 or profit_pct > 10.0:
                row = [now_str, hunting_symbol, "SOLD", entry_price_thb, sell_p, f"{profit_pct:.2f}%", current_data['Score'], new_bal, 0, "Trend Reversed", "ON"]
                sheet.append_row(row)
                st.warning(f"💰 ขาย {hunting_symbol} แล้ว! กำไรสุทธิ: {profit_pct:.2f}%")
                time.sleep(2)
                st.rerun()

# แสดงกราฟ Performance
if not df_perf.empty:
    st.subheader("📈 กราฟพอร์ตโฟลิโอ")
    st.line_chart(df_perf['Balance'])

# ระบบสแกนต่อเนื่อง (Stealth Mode)
wait_time = random.randint(60, 120)
st.info(f"⌛ กำลังพักเครื่อง... จะเริ่มสแกนใหม่ใน {wait_time} วินาที")
time.sleep(wait_time)
st.rerun()
