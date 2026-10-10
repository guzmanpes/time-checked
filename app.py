import streamlit as st
import pandas as pd
from datetime import datetime, date
import pytz

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Phelan Falcons Live Schedule", layout="wide", initial_sidebar_state="collapsed")

# --- 2. SETTINGS & SHEET IDs ---
SHEET_ID = "1N3QLjiX4o8IwsDtGiJno-uQQ4ySijRXdy7Z7ec2kAdw"
CALENDAR_SHEET_ID = "1tVm6iLZqci_fKVv9zmN0fd_pJ7doAC-fv4A-dYNGomM"

ANCHOR_DATE = date(2026, 5, 25) 

# --- 3. CUSTOM THEMING (CSS) ---
st.markdown("""
    <style>
    .main {
        background-color: #0e1117;
    }
    h1 {
        color: #1E90FF !important; 
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        text-align: center;
        margin-bottom: 0px !important;
        padding-bottom: 2px !important;
        font-weight: bold;
        text-shadow: 1px 1px 10px rgba(30, 144, 255, 0.3);
    }
    [data-testid="stMetric"] {
        background-color: #1a1c24;
        border: 1px solid #444;
        padding: 8px 12px !important; 
        border-radius: 10px;
        margin-bottom: 8px !important; 
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        min-height: 75px; 
    }
    [data-testid="stMetricLabel"] {
        color: #FFD700 !important;
        font-size: 18px !important; 
        font-weight: bold !important;
        width: 100%;
        text-align: center;
        line-height: 1.1 !important;
    }
    [data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-size: 28px !important; 
        width: 100%;
        text-align: center;
        line-height: 1.1 !important;
    }
    .stVerticalBlock { gap: 0.8rem !important; }
    .stHorizontalBlock { gap: 0.4rem !important; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 4. CALENDAR LOOKUP FUNCTION ---
def get_daily_responsibility(cal_id, now_datetime):
    """
    Pulls current month's tab (e.g., 'October 2026') from the viewer-only 
    calendar spreadsheet, finds today's day number, and returns the text below it.
    """
    month_tab = now_datetime.strftime("%B %Y")
    day_num = str(now_datetime.day)
    
    try:
        safe_month_tab = month_tab.replace(" ", "%20")
        url = f"https://docs.google.com/spreadsheets/d/{cal_id}/gviz/tq?tqx=out:csv&sheet={safe_month_tab}"
        df = pd.read_csv(url, header=None).astype(str)
        
        for r_idx, row in df.iterrows():
            for c_idx, val in enumerate(row):
                if val.strip() == day_num:
                    if r_idx + 1 < len(df):
                        resp = df.iloc[r_idx + 1, c_idx].strip()
                        if resp.lower() not in ['nan', 'none', '', 'null']:
                            return resp
        return "None Assigned"
    except Exception:
        return "Calendar Unavailable"

# --- 5. ROTATION DAY CALCULATION ---
def get_current_rotation_day(today_date, anchor_date):
    if today_date < anchor_date:
        return "Day 1"
    days = pd.date_range(start=anchor_date, end=today_date, freq='B')
    total_school_days = len(days)
    rotation_num = ((total_school_days - 1) % 10) + 1
    return f"Day {rotation_num}"

# --- 6. DASHBOARD MAIN LOOP ---
@st.fragment(run_every=5)
def update_dashboard():
    local_tz = pytz.timezone('US/Pacific') 
    
    # ------------------------------------------------------------------
    # MOCK TIME FOR WEEKEND TESTING (Tuesday, October 20, 2026 @ 10:15 AM)
    # To return to real live time later, change this line to:
    # now = datetime.now(local_tz)
    # ------------------------------------------------------------------
    now = local_tz.localize(datetime(2026, 10, 20, 10, 15, 0))
    
    current_date_str = now.strftime("%B %d, %Y")
    current_day_of_week = now.strftime("%A")
    
    current_sheet = get_current_rotation_day(now.date(), ANCHOR_DATE)
    
    if current_day_of_week in ["Saturday", "Sunday"]:
        display_day = f"Weekend ({current_sheet} Next)"
    else:
        display_day = f"{current_day_of_week} ({current_sheet})"

    # Calculate 5-minute time slot using 'now'
    rounded_minute = (now.minute // 5) * 5
    current_slot = now.replace(minute=rounded_minute, second=0, microsecond=0).strftime("%H:%M")

    # Fetch dynamic duty from the Calendar sheet
    daily_duty = get_daily_responsibility(CALENDAR_SHEET_ID, now)

    # --- HEADER ---
    st.markdown(f"<h1>PHELAN FALCONS LIVE DAILY SCHEDULE</h1>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; color: #1E90FF; font-size: 17px; font-weight: bold; margin-top: -5px; margin-bottom: 8px;'>{display_day}, {current_date_str} | {now.strftime('%I:%M:%S %p')}</p>", unsafe_allow_html=True)

    # --- LOAD MAIN SCHEDULE SHEET ---
    try:
        safe_sheet_name = current_sheet.replace(" ", "%20")
        url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={safe_sheet_name}"
        df = pd.read_csv(url).astype(object)
        df.columns = df.columns.str.strip()
    except Exception:
        st.error(f"Error connecting to Google Sheet tab: '{current_sheet}'. Please verify tab exists.")
        return

    time_col = next((col for col in df.columns if col.lower() == 'time'), None)

    if time_col:
        df[time_col] = df[time_col].astype(str).str.strip()
        match = df[df[time_col].str.contains(current_slot, na=False)]

        if not match.empty
