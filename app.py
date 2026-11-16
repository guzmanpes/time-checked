import streamlit as st
import pandas as pd
from datetime import datetime, date
import pytz
import requests
import urllib.parse

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Phelan Falcons Live Schedule", layout="wide", initial_sidebar_state="collapsed")

# --- 2. SETTINGS & SHEET IDs ---
SHEET_ID = "1N3QLjiX4o8IwsDtGiJno-uQQ4ySijRXdy7Z7ec2kAdw"
CALENDAR_SHEET_ID = "1j0YO44sn1D5jerX--ycQpwS96utTBPgDXW96ro0DG44"

# Map exact tab GIDs here (add future months as you create them)
MONTH_GIDS = {
    (2026, 10): "1235635239",
    (2026, 11): "1793927444",
}

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
    Fetches the active month's sheet using its exact GID if mapped in MONTH_GIDS,
    otherwise falls back to searching by tab name. Scans the 2D matrix for today's date.
    """
    target_day = str(now_datetime.day)
    current_month_full = now_datetime.strftime("%B").lower()
    current_month_abbr = now_datetime.strftime("%b").lower()
    
    ignored_words = {
        'nan', 'none', 'null', '0', '2026', '2027', 'notes',
        'october', 'november', 'december', 'january', 'february', 'march', 
        'april', 'may', 'june', 'july', 'august', 'september',
        'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday',
        'sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'
    }

    urls_to_try = []
    
    # 1. Priority: Direct GID export (prevents GViz silent fallback to wrong tab)
    gid = MONTH_GIDS.get((now_datetime.year, now_datetime.month))
    if gid:
        urls_to_try.append((f"https://docs.google.com/spreadsheets/d/{cal_id}/export?format=csv&gid={gid}", True))
        
    # 2. Fallback: Tab name queries for future unmapped months
    tab_candidates = [
        now_datetime.strftime("%B %Y"),          # "November 2026"
        now_datetime.strftime("%B %Y").upper(),  # "NOVEMBER 2026"
        now_datetime.strftime("%b %Y"),          # "Nov 2026"
        now_datetime.strftime("%b").upper(),     # "NOV"
        now_datetime.strftime("%B").upper()      # "NOVEMBER"
    ]
    for tab in tab_candidates:
        encoded = urllib.parse.quote(tab)
        urls_to_try.append((f"https://docs.google.com/spreadsheets/d/{cal_id}/gviz/tq?tqx=out:csv&sheet={encoded}", False))

    for csv_url, is_exact_gid in urls_to_try:
        try:
            df = pd.read_csv(csv_url, header=None).fillna("").astype(str)
            
            # If using a fallback tab-name URL, verify the sheet actually contains this month's header
            # (prevents GViz from silently serving October when a tab name doesn't match)
            if not is_exact_gid:
                sheet_text = " ".join(df.values.flatten()).lower()
                if current_month_full not in sheet_text and current_month_abbr not in sheet_text:
                    continue

            # Scan 2D grid line-by-line for current day number
            for r_idx in range(len(df)):
                for c_idx in range(len(df.columns)):
                    raw_cell = str(df.iloc[r_idx, c_idx]).strip()
                    cell_val = raw_cell.split('.')[0]
                    
                    if cell_val == target_day and len(raw_cell) <= 4:
                        # Scan rows directly beneath in same column and adjacent offsets
                        for r_offset in [1, 2]:
                            if r_idx + r_offset < len(df):
                                for c_offset in [0, -1, 1, -2, 2]:
                                    t_c = c_idx + c_offset
                                    if 0 <= t_c < len(df.columns):
                                        candidate = str(df.iloc[r_idx + r_offset, t_c]).strip()
                                        
                                        if candidate and any(char.isalpha() for char in candidate):
                                            if candidate.lower() not in ignored_words:
                                                return candidate
        except Exception:
            continue

    return "None Assigned"

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
    
    # LIVE REAL-TIME CLOCK (Pacific Time)
    now = datetime.now(local_tz)
    
    current_date_str = now.strftime("%B %d, %Y")
    current_day_of_week = now.strftime("%A")
    
    current_sheet = get_current_rotation_day(now.date(), ANCHOR_DATE)
    
    if current_day_of_week in ["Saturday", "Sunday"]:
        display_day = f"Weekend ({current_sheet} Next)"
    else:
        display_day = f"{current_day_of_week} ({current_sheet})"

    rounded_minute = (now.minute // 5) * 5
    current_slot = now.replace(minute=rounded_minute, second=0, microsecond=0).strftime("%H:%M")

    # Fetch live duty from Calendar sheet
    daily_duty = get_daily_responsibility(CALENDAR_SHEET_ID, now)

    # --- HEADER ---
    st.markdown(f"<h1>PHELAN FALCONS LIVE DAILY SCHEDULE</h1>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; color: #1E90FF; font-size: 17px; font-weight: bold; margin-top: -5px; margin-bottom: 8px;'>{display_day}, {current_date_str} | {now.strftime('%I:%M:%S %p')}</p>", unsafe_allow_html=True)

    # --- LOAD MAIN SCHEDULE SHEET ---
    try:
        safe_sheet_name = urllib.parse.quote(current_sheet)
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

        if not match.empty:
            all_cols = [c for c in df.columns if c != time_col and "Unnamed" not in c]
            
            top_tier = [c for c in all_cols if c.upper() in ["TK", "K"]]
            mid_tier = [c for c in all_cols if any(x in c.upper() for x in ["1ST", "2ND", "3RD"])]
            bot_tier = [c for c in all_cols if any(x in c.upper() for x in ["4TH", "5TH"])]
            used_cols = top_tier + mid_tier + bot_tier
            other_tier = [c for c in all_cols if c not in used_cols]

            def render_row(teams_list):
                if teams_list:
                    cols = st.columns(len(teams_list))
                    for i, team in enumerate(teams_list):
                        with cols[i]:
                            val = str(match[team].values[0]).strip("[]'\"")
                            if val.lower() in ['nan', 'none', '']: 
                                val = "---"
                            st.metric(label=team, value=val)

            st.markdown("<div style='margin-top: 5px;'></div>", unsafe_allow_html=True)
            render_row(top_tier)
            render_row(mid_tier)
            render_row(bot_tier)
            render_row(other_tier)
            
            # Metric card for Bilingual Associate on Call
            st.columns(1)[0].metric(label="Bilingual Associate on call", value=daily_duty)
            
        else:
            st.info(f"No activities scheduled for slot {current_slot} on {current_sheet}.")
    else:
        st.error("Missing 'Time' column in Google Sheet.")

# --- 7. RUN DASHBOARD ---
update_dashboard()
