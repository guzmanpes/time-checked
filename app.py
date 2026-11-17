import csv
import io
import re
import urllib.parse
from datetime import datetime, date, time, timedelta

import numpy as np
import pandas as pd
import pytz
import requests
import streamlit as st

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Phelan Falcons Live Schedule", layout="wide", initial_sidebar_state="collapsed")

# --- 2. SETTINGS & SHEET IDs ---
SHEET_ID = "1N3QLjiX4o8IwsDtGiJno-uQQ4ySijRXdy7Z7ec2kAdw"
CALENDAR_SHEET_ID = "1j0YO44sn1D5jerX--ycQpwS96utTBPgDXW96ro0DG44"
GOOGLE_BASE = "https://docs.google.com/spreadsheets/d/"

# Exact tab GIDs for the duty calendar (add future months as you create them)
MONTH_GIDS = {
    (2026, 10): "1235635239",
    (2026, 11): "1793927444",
    (2026, 12): "133502854",
    (2027, 1): "865969785",
    (2027, 2): "595529875",
    (2027, 3): "1947094466",
    (2027, 4): "1119227196",
    (2027, 5): "274842464",
    (2027, 6): "375877910",
}

LOCAL_TZ = pytz.timezone("US/Pacific")

# --- ROTATION ANCHOR ---
# A known school day and its rotation number. To re-sync the rotation,
# change these two lines to any school day you know for sure.
ANCHOR_DATE = date(2026, 11, 17)
ANCHOR_DAY_NUMBER = 2

# --- NO-SCHOOL DAYS (weekdays) — rotation does NOT advance on these ---
# Snowline JUSD 2026-27 calendar. Verify against the official district calendar.
def _span(start, end):
    return [d.date() for d in pd.date_range(start, end, freq="B")]

SCHOOL_HOLIDAYS = sorted(set(
    [date(2026, 9, 7)]                              # Labor Day
    + _span("2026-10-12", "2026-10-16")             # Fall Break
    + [date(2026, 11, 11)]                          # Veterans Day
    + _span("2026-11-23", "2026-11-27")             # Thanksgiving Break
    + _span("2026-12-21", "2027-01-01")             # Winter Break
    + [date(2027, 1, 15), date(2027, 1, 18)]        # Staff Work Day, MLK Day
    + [date(2027, 2, 8), date(2027, 2, 15)]         # Lincoln, Washington
    + _span("2027-03-22", "2027-03-26")             # Spring Break
    + [date(2027, 5, 31)]                           # Memorial Day
))
LAST_DAY_OF_SCHOOL = date(2027, 6, 4)

# --- 3. CUSTOM THEMING (CSS) ---
st.markdown("""
    <style>
    .main { background-color: #0e1117; }
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
        white-space: normal !important;
    }
    .stVerticalBlock { gap: 0.8rem !important; }
    .stHorizontalBlock { gap: 0.4rem !important; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 4. SIDEBAR DEBUG OVERRIDE ---
debug_date, debug_time = None, None
with st.sidebar:
    st.header("Schedule Preview / Debug")
    use_debug = st.toggle("Enable Test Date & Time", value=False)
    if use_debug:
        debug_date = st.date_input("Test Date", value=date(2026, 11, 17))
        debug_time = st.time_input("Test Time", value=time(10, 15), step=300)
        st.caption("Turn off the toggle above to return to the live Pacific clock.")
    if st.button("Clear cached sheet data"):
        st.cache_data.clear()
        st.success("Cache cleared — next refresh pulls fresh data.")


# --- 5. NETWORK HELPERS (cached so screens don't hammer Google every 5 s) ---
@st.cache_data(ttl=60, show_spinner=False)
def fetch_csv_rows(url):
    """Download a CSV and return it as a list of rows (list of str). Raises on failure."""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig")
    if text.lstrip().lower().startswith("<!doctype html") or "<html" in text[:500].lower():
        raise ValueError("Got an HTML page instead of CSV (sheet not public?)")
    return [row for row in csv.reader(io.StringIO(text))]


# --- 6. CALENDAR LOOKUP FUNCTION ---
# Duty calendar layout (one tab per month, e.g. "November 2026"):
#   a row of date numbers (Sun..Sat), and the staff name directly BELOW each date.
MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december"]
IGNORED_WORDS = set(MONTH_NAMES) | {
    "nan", "none", "null", "notes",
    "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sun", "mon", "tue", "wed", "thu", "fri", "sat",
}


@st.cache_data(ttl=3600, show_spinner=False)
def discover_tab_gids(cal_id):
    """Read the sheet's public HTML view to map tab names -> gids. Returns {} on failure."""
    try:
        resp = requests.get(f"{GOOGLE_BASE}{cal_id}/htmlview", timeout=10)
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return {}
    found = {}
    for name, gid in re.findall(r'name:\s*"([^"]+)"[^}]*?gid:\s*"(\d+)"', html):
        found[name.strip().lower()] = gid
    for gid, name in re.findall(r'id="sheet-button-(\d+)"[^>]*>(?:<[^>]+>)*([^<]+)<', html):
        found.setdefault(name.strip().lower(), gid)
    return found


def _normalize(grid):
    width = max((len(r) for r in grid), default=0)
    return [[c.strip() for c in r] + [""] * (width - len(r)) for r in grid]


def _is_month_tab(grid, month_index):
    """True only if this tab mentions the target month and NO other month.
    (Guards against the yearly '2026' overview tab, which lists all 12 months.)"""
    text = " ".join(" ".join(r) for r in grid).lower()
    present = {m for m in MONTH_NAMES if re.search(rf"\b{m}\b", text)}
    return present == {MONTH_NAMES[month_index - 1]}


@st.cache_data(ttl=60, show_spinner=False)
def load_month_grid(cal_id, year, month):
    """Return the 2D grid for a month's tab, or None if it can't be found."""
    tab_name = date(year, month, 1).strftime("%B %Y")
    urls = []
    gid = MONTH_GIDS.get((year, month)) or discover_tab_gids(cal_id).get(tab_name.lower())
    if gid:
        urls.append(f"{GOOGLE_BASE}{cal_id}/export?format=csv&gid={gid}")
    # Last resort: GViz by tab name (validated below, since GViz returns tab 1 on a miss)
    for tab in [tab_name, tab_name.upper(), date(year, month, 1).strftime("%b %Y")]:
        urls.append(f"{GOOGLE_BASE}{cal_id}/gviz/tq?tqx=out:csv&headers=0&sheet={urllib.parse.quote(tab)}")

    for url in urls:
        try:
            grid = _normalize(fetch_csv_rows(url))
        except Exception:
            continue
        if grid and _is_month_tab(grid, month):
            return grid
    return None


def _as_day(cell):
    s = cell.split(".")[0] if re.fullmatch(r"\d{1,2}(\.0+)?", cell) else ""
    return int(s) if s and 1 <= int(s) <= 31 else None


def _find_name(grid, day, which_rows="all"):
    """Look for `day` in the date rows; return (found, name).
    which_rows: 'all' (current month), 'first' or 'last' (spill-over days in a neighbor tab)."""
    date_rows = [i for i, r in enumerate(grid) if sum(_as_day(c) is not None for c in r) >= 3]
    if not date_rows:
        return False, ""
    if which_rows == "first":
        date_rows = date_rows[:1]
    elif which_rows == "last":
        date_rows = date_rows[-1:]
    first, last = date_rows[0], date_rows[-1]
    for r in date_rows:
        for c, cell in enumerate(grid[r]):
            d = _as_day(cell)
            if d != day:
                continue
            # Skip spill-over numbers from adjacent months when scanning the current month
            if which_rows == "all" and ((r == first and d > 20) or (r == last and d < 10 and r != first)):
                continue
            if r + 1 < len(grid):
                cand = grid[r + 1][c]   # name sits directly below the date, same column only
                if cand and any(ch.isalpha() for ch in cand) and cand.lower() not in IGNORED_WORDS:
                    return True, cand
            return True, ""
    return False, ""


@st.cache_data(ttl=60, show_spinner=False)
def get_daily_responsibility(cal_id, day_date):
    grid = load_month_grid(cal_id, day_date.year, day_date.month)
    if grid is not None:
        found, name = _find_name(grid, day_date.day)
        if name:
            return name

    # Days at the edge of a month are sometimes written on the neighbor month's tab
    # (e.g. Nov 30 appears on the "December 2026" tab).
    if day_date.day >= 22:
        nxt = (day_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        g2 = load_month_grid(cal_id, nxt.year, nxt.month)
        if g2 is not None:
            _, name = _find_name(g2, day_date.day, "first")
            if name:
                return name
    elif day_date.day <= 7:
        prv = day_date.replace(day=1) - timedelta(days=1)
        g2 = load_month_grid(cal_id, prv.year, prv.month)
        if g2 is not None:
            _, name = _find_name(g2, day_date.day, "last")
            if name:
                return name

    return "None Assigned" if grid is not None else "Calendar unavailable"


# --- 7. ROTATION DAY CALCULATION (skips weekends + school holidays) ---
_HOLIDAYS_NP = np.array(SCHOOL_HOLIDAYS, dtype="datetime64[D]")


def is_school_day(d):
    return bool(np.is_busday(np.datetime64(d), holidays=_HOLIDAYS_NP))


def next_school_day(d):
    d = d + timedelta(days=1)
    while not is_school_day(d):
        d += timedelta(days=1)
    return d


def get_rotation_number(d):
    """Rotation number (1-10) for school day d, counted from the anchor."""
    offset = int(np.busday_count(np.datetime64(ANCHOR_DATE), np.datetime64(d), holidays=_HOLIDAYS_NP))
    return ((ANCHOR_DAY_NUMBER - 1 + offset) % 10) + 1


# --- 8. TIME HELPERS ---
def parse_sheet_time(value):
    """Turn '8:00', '08:00', '8:00:00 AM', '1:05 PM', '13:05' into a time object."""
    s = str(value).strip().upper()
    if not s or s in ("NAN", "NONE"):
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?", s)
    if not m:
        return None
    h, mnt, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if ampm == "PM" and h != 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0
    if h > 23 or mnt > 59:
        return None
    return time(h, mnt)


@st.cache_data(ttl=60, show_spinner=False)
def load_rotation_sheet(sheet_name):
    url = f"{GOOGLE_BASE}{SHEET_ID}/gviz/tq?tqx=out:csv&headers=1&sheet={urllib.parse.quote(sheet_name)}"
    rows = fetch_csv_rows(url)
    df = pd.DataFrame(rows[1:], columns=[c.strip() for c in rows[0]])
    return df


def render_row(teams_list, row):
    if teams_list:
        cols = st.columns(len(teams_list))
        for i, team in enumerate(teams_list):
            with cols[i]:
                val = str(row[team]).strip().strip("[]'\"")
                if val.lower() in ("nan", "none", ""):
                    val = "---"
                st.metric(label=team, value=val)


def render_duty_card(duty):
    st.columns(1)[0].metric(label="Bilingual Associate on call", value=duty)


# --- 9. DASHBOARD MAIN LOOP ---
@st.fragment(run_every=5)
def update_dashboard():
    if use_debug:
        now = LOCAL_TZ.localize(datetime.combine(debug_date, debug_time))
    else:
        now = datetime.now(LOCAL_TZ)
    today = now.date()

    school_today = is_school_day(today) and today <= LAST_DAY_OF_SCHOOL
    if school_today:
        rotation_day = f"Day {get_rotation_number(today)}"
        display_day = f"{now.strftime('%A')} ({rotation_day})"
    else:
        nxt = next_school_day(today)
        label = "Weekend" if today.weekday() >= 5 else "No School"
        display_day = f"{label} (Day {get_rotation_number(nxt)} on {nxt.strftime('%a %b %d').replace(' 0', ' ')})"

    # --- HEADER ---
    st.markdown("<h1>PHELAN FALCONS LIVE DAILY SCHEDULE</h1>", unsafe_allow_html=True)
    mode_badge = " [PREVIEW MODE]" if use_debug else ""
    date_str = now.strftime("%B %d, %Y").replace(" 0", " ")
    st.markdown(
        f"<p style='text-align: center; color: #1E90FF; font-size: 17px; font-weight: bold; "
        f"margin-top: -5px; margin-bottom: 8px;'>{display_day}, {date_str} | "
        f"{now.strftime('%I:%M:%S %p').lstrip('0')}{mode_badge}</p>",
        unsafe_allow_html=True,
    )

    if not school_today:
        st.info("No school today. The schedule will resume on the next school day.")
        return

    daily_duty = get_daily_responsibility(CALENDAR_SHEET_ID, today)

    # --- LOAD MAIN SCHEDULE SHEET ---
    try:
        df = load_rotation_sheet(rotation_day)
    except Exception:
        st.error(f"Couldn't load Google Sheet tab '{rotation_day}'. Check the tab exists and the sheet is shared.")
        render_duty_card(daily_duty)
        return

    time_col = next((c for c in df.columns if c.lower() == "time"), None)
    if not time_col:
        st.error(f"Missing 'Time' column on tab '{rotation_day}'.")
        render_duty_card(daily_duty)
        return

    # Pick the latest row whose time is at or before now (works for any time format)
    times = df[time_col].map(parse_sheet_time)
    valid = df[times.notna()].assign(_t=times[times.notna()])
    current = valid[valid["_t"] <= now.time().replace(second=0, microsecond=0)]

    row = current.loc[current["_t"].idxmax()] if not current.empty else None
    # Rows are 5-minute slots, so a gap of 10+ minutes past the last row means the day is over
    stale = row is not None and (
        datetime.combine(today, now.time()) - datetime.combine(today, row["_t"])
    ) >= timedelta(minutes=10)

    if row is None or stale:
        if row is None and not valid.empty:
            msg = f"School day hasn't started yet on {rotation_day}."
        else:
            msg = f"No activities scheduled right now on {rotation_day}."
        st.info(msg)
        render_duty_card(daily_duty)
        return

    all_cols = [c for c in df.columns if c and c != time_col and "Unnamed" not in c]
    top_tier = [c for c in all_cols if c.upper() in ("TK", "K")]
    mid_tier = [c for c in all_cols if any(x in c.upper() for x in ("1ST", "2ND", "3RD"))]
    bot_tier = [c for c in all_cols if any(x in c.upper() for x in ("4TH", "5TH"))]
    used = set(top_tier + mid_tier + bot_tier)
    other_tier = [c for c in all_cols if c not in used]

    st.markdown("<div style='margin-top: 5px;'></div>", unsafe_allow_html=True)
    for tier in (top_tier, mid_tier, bot_tier, other_tier):
        render_row(tier, row)
    render_duty_card(daily_duty)


# --- 10. RUN DASHBOARD ---
update_dashboard()
