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
    """ดึงเวลาปัจจุบันในโซนไทย (GMT+7) ในรูปแบบ dd/mm/yyyy hh:mm:ss"""
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
    return ["SOL-USD", "NEAR-USD", "RENDER-USD", "FET-USD", "LINK-USD", "DOT-USD", "XRP-USD", "ADA-USD"]

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
current_bal = 1000.0
df_perf = pd.DataFrame()

# ดึงข้อมูลจาก Sheet และจัดการเรื่อง Balance
if sheet:
    try:
        recs = sheet.get_all_records()
        if recs:
            df_perf = pd.DataFrame(recs)
            if not df_perf.empty and 'Balance' in df_perf.columns:
                recs_with_balance = df_perf[df_perf['Balance'] != ""] # กรองเฉพาะแถวที่มีตัวเลข
                if not recs_with_balance.empty:
                    current_bal = float(recs_with_balance.iloc[-1]['Balance'])
                else:
                    current_bal = init_money # ถ้าไม่มีประวัติเลย ให้ใช้งบตั้งต้นที่กรอกมา
            else:
                current_bal = init_money # ถ้า Sheet ว่างเปล่า ให้ใช้งบตั้งต้น
    except: pass

# Sidebar
init_money = st.sidebar.number_input("งบตั้งต้น (บาท)", value=1000.0)
profit_goal = st.sidebar.number_input("กำไรที่ต้องการ (บาท)", value=10000.0)
live_rate = get_live_exchange_rate()
st.sidebar.metric("ค่าเงิน USD/THB (Live)", f"{live_rate} ฿")
st.sidebar.write(f"🕒 อัปเดตล่าสุด: {get_now_thailand()}")

bot_active = get_bot_status(sheet) if sheet else False
if st.sidebar.button("START" if not bot_active else "STOP"):
    if sheet:
        set_bot_status(sheet, not bot_active)
        st.rerun()

# Dashboard
st.title("🦔 Pepper Hunter")
target_total = init_money + profit_goal
profit_now = current_bal - init_money

m1, m2, m3 = st.columns(3)
m1.metric("งบปัจจุบัน", f"{current_bal:,.2f} ฿", f"{profit_now:,.2f} ฿")
m2.metric("เป้าหมายเส้นชัย", f"{target_total:,.2f} ฿")
m3.metric("สถานะบอท", "RUNNING 🟢" if bot_active else "IDLE 🔴")

st.divider()

if bot_active:
    if current_bal >= target_total:
        st.balloons()
        st.success(f"🏆 ภารกิจสำเร็จเมื่อ {get_now_thailand()}!")
        set_bot_status(sheet, False)
    else:
        st.subheader(f"🔍 สแกนตลาด ณ เวลา {get_now_thailand()}")
        all_picks = []
        tickers = get_top_safe_tickers()
        
        with st.status("AI กำลังวิเคราะห์...", expanded=False):
            for sym in tickers:
                df_h = yf.download(sym, period="60d", interval="1d", progress=False)
                if not df_h.empty:
                    res = analyze_coin_ai(sym, df_h)
                    if res:
                        price_thb = res['Price_USD'] * live_rate
                        if current_bal >= (price_thb * 0.05):
                            all_picks.append({
                                "Symbol": sym,
                                "Price_THB": price_thb,
                                "Score": res['Score']
                            })
        
        top_6 = sorted(all_picks, key=lambda x: x['Score'], reverse=True)[:6]
        
        cols = st.columns(3)
        for i, coin in enumerate(top_6):
            with cols[i % 3]:
                st.info(f"**{coin['Symbol']}**")
                st.write(f"ราคา: {coin['Price_THB']:,.2f} ฿")
                st.write(f"AI Score: **{coin['Score']}**")
                if coin['Score'] >= 85:
                    st.write("🔥 *Signal: STRONG BUY*")

        # สุ่มเวลาพัก 30-60 วินาที เพื่อความเป็นธรรมชาติ
        time.sleep(random.randint(30, 60))
        st.rerun()

if not df_perf.empty:
    st.subheader("📉 พอร์ตโฟลิโอ")
    # แสดงกราฟโดยใช้คอลัมน์ Balance และใช้ Timestamp เป็นแกน X (ถ้ามี)
    if 'Timestamp' in df_perf.columns:
        df_perf['Timestamp'] = pd.to_datetime(df_perf['Timestamp'], format="%d/%m/%Y %H:%M:%S")
        chart_data = df_perf.set_index('Timestamp')['Balance']
        st.line_chart(chart_data)
    else:
        st.line_chart(df_perf['Balance'])


