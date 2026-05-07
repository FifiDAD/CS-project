"""Shared CSS, color maps, header/nav/footer rendering for TradeWatch pages."""
import streamlit as st
from datetime import datetime

# ── Color maps ────────────────────────────────────────────────────────────────
SC = {
    "Operational":             "#22c55e",
    "Operational - Alert":     "#eab308",
    "Operational - High Risk": "#f97316",
    "Critical - Avoid":        "#ef4444",
    "Unavailable":             "#6b7280",
}
SBG = {
    "Operational":             "rgba(34,197,94,0.1)",
    "Operational - Alert":     "rgba(234,179,8,0.1)",
    "Operational - High Risk": "rgba(249,115,22,0.1)",
    "Critical - Avoid":        "rgba(239,68,68,0.1)",
    "Unavailable":             "rgba(107,114,128,0.1)",
}

def risk_col(s: int) -> str:
    if s >= 70: return "#ef4444"
    if s >= 40: return "#f97316"
    if s >= 15: return "#eab308"
    return "#22c55e"

TOPIC_COLOR = {"conflict":"#ef4444","shipping":"#3b82f6","weather":"#22c55e","trade":"#a855f7","other":"#666666"}
TOPIC_ICON  = {"conflict":"💥","shipping":"🚢","weather":"⛈","trade":"📦","other":"📰"}
CONG_COL    = {"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"}
IMPACT_COL  = {"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"}
IMPACT_ICON = {"Critical":"🔴","High":"🟠","Medium":"🟡","Low":"🟢"}

# ── CSS ───────────────────────────────────────────────────────────────────────
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@300;400;500;600;700&display=swap');

*, *::before, *::after {
  font-family: 'Fira Code', 'SF Mono', 'Cascadia Code', 'Monaco', monospace !important;
  box-sizing: border-box;
}

:root {
  --bg:         #0a0a0a;
  --bg2:        #111111;
  --surface:    #141414;
  --surface2:   #1e1e1e;
  --border:     #2a2a2a;
  --border2:    #444444;
  --text:       #e8e8e8;
  --text2:      #aaaaaa;
  --text3:      #666666;
  --text4:      #444444;
  --critical:   #ef4444;
  --high:       #f97316;
  --elevated:   #eab308;
  --normal:     #22c55e;
  --info:       #3b82f6;
  --live:       #44ff88;
  --accent:     #3b82f6;
  --map-bg:     #020a08;
}

#MainMenu, footer, header,
button[data-testid="baseButton-headerNoPadding"],
section[data-testid="stSidebar"],
.stDeployButton,
[data-testid="collapsedControl"]  { display: none !important; }

.stApp                            { background: var(--bg) !important; }
.block-container                  { padding: 0 !important; max-width: 100% !important; }
section.main > div                { padding: 0 !important; }

p, span, div, label, li, td, th,
.stMarkdown, .stText              { color: var(--text) !important; font-size: 12px !important; }
h1, h2, h3                        { color: var(--text) !important; letter-spacing: 0.02em; }

::-webkit-scrollbar               { width: 4px; height: 4px; }
::-webkit-scrollbar-track         { background: var(--bg); }
::-webkit-scrollbar-thumb         { background: #333; border-radius: 2px; }
::-webkit-scrollbar-thumb:hover   { background: #555; }

.js-plotly-plot .plotly            { background: transparent !important; }

div[data-testid="metric-container"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: 4px !important;
  padding: 8px 10px !important;
}
div[data-testid="stMetricValue"]    { font-size: 14px !important; font-weight: 600 !important; }
div[data-testid="stMetricLabel"]    { font-size: 10px !important; color: var(--text3) !important; text-transform: uppercase; letter-spacing: 0.4px; }

div[data-testid="stExpander"]      { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 4px !important; }
div[data-testid="stExpander"] summary { font-size: 11px !important; color: var(--text2) !important; }

.stButton > button                 { background: var(--surface2) !important; border: 1px solid var(--border) !important;
                                     color: var(--text2) !important; border-radius: 4px !important;
                                     font-size: 10px !important; padding: 4px 10px !important;
                                     text-transform: uppercase; letter-spacing: 0.4px;
                                     transition: all 0.15s ease; }
.stButton > button:hover           { border-color: var(--accent) !important; color: var(--text) !important; }

/* ── Selectbox / Input trigger ──────────────────────────────────────────── */
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
.stTextInput > div > div          { background: var(--surface2) !important; border-color: var(--border) !important;
                                    font-size: 12px !important; border-radius: 4px !important; color: var(--text) !important; }

/* selected value text inside trigger */
div[data-baseweb="select"] span,
div[data-baseweb="select"] div[class*="placeholder"]
                                  { color: var(--text2) !important; }
div[data-baseweb="select"] div[aria-selected="true"] span,
div[data-baseweb="select"] [class*="singleValue"]
                                  { color: var(--text) !important; }

/* dropdown arrow icon */
div[data-baseweb="select"] svg    { fill: var(--text3) !important; }

/* ── Selectbox popup / menu ─────────────────────────────────────────────── */
div[data-baseweb="popover"],
ul[data-baseweb="menu"]           { background: var(--surface2) !important;
                                    border: 1px solid var(--border) !important;
                                    border-radius: 4px !important;
                                    box-shadow: 0 8px 24px rgba(0,0,0,0.6) !important; }

li[data-baseweb="option"],
div[role="option"]                { background: var(--surface2) !important;
                                    color: var(--text2) !important;
                                    font-size: 11px !important;
                                    padding: 8px 12px !important;
                                    border-bottom: 1px solid var(--border) !important;
                                    cursor: pointer !important; }

li[data-baseweb="option"]:hover,
div[role="option"]:hover,
li[data-baseweb="option"][aria-selected="true"],
div[role="option"][aria-selected="true"]
                                  { background: #1a2744 !important;
                                    color: var(--text) !important; }

/* selectbox label */
div[data-testid="stSelectbox"] label,
div[data-testid="stMultiSelect"] label
                                  { color: var(--text3) !important;
                                    font-size: 9px !important;
                                    text-transform: uppercase !important;
                                    letter-spacing: 0.4px !important; }

.stDataFrame                       { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 4px !important; }
.stDataFrame table                 { font-size: 11px !important; }
.stDataFrame th                    { background: var(--bg2) !important; color: var(--text3) !important;
                                     font-size: 9px !important; text-transform: uppercase; letter-spacing: 0.4px; }

hr                                 { border-color: var(--border) !important; margin: 8px 0 !important; }
div[data-testid="stAlert"]         { border-radius: 4px !important; font-size: 11px !important; }
div[data-testid="stSlider"]        { padding: 4px 0 !important; }
div[data-testid="stSpinner"]       { color: var(--text3) !important; font-size: 11px !important; }

/* ── Header ─────────────────────────────────────────────────────────────── */
.tw-header {
  display: flex; align-items: center; justify-content: space-between;
  height: 40px; padding: 0 16px;
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 999;
}
.tw-header-logo { font-size: 13px; font-weight: 700; color: var(--text); letter-spacing: 0.06em; }
.tw-header-meta { font-size: 10px; color: var(--text3); letter-spacing: 0.3px; }

/* ── Live dot ────────────────────────────────────────────────────────────── */
.tw-live-dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  margin-right: 5px; vertical-align: middle;
  animation: live-blink 1.5s ease-in-out infinite;
}
@keyframes live-blink {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.4; transform: scale(0.85); }
}

/* ── Nav bar ─────────────────────────────────────────────────────────────── */
.tw-nav-wrap {
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  padding: 0 8px;
}
div[data-testid="stPageLink"] {
  padding: 0 !important; margin: 0 !important;
}
div[data-testid="stPageLink"] a {
  color: var(--text3) !important;
  font-size: 10px !important;
  font-weight: 600 !important;
  text-decoration: none !important;
  text-transform: uppercase !important;
  letter-spacing: 0.5px !important;
  padding: 8px 12px !important;
  display: block !important;
  border-bottom: 2px solid transparent !important;
  transition: color 0.1s, border-color 0.1s !important;
}
div[data-testid="stPageLink"] a:hover {
  color: var(--text) !important;
  border-bottom-color: var(--border2) !important;
}
div[data-testid="stPageLink"] a[aria-current="page"] {
  color: var(--accent) !important;
  border-bottom-color: var(--accent) !important;
}

/* ── Panel ───────────────────────────────────────────────────────────────── */
.tw-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 10px 12px;
  margin-bottom: 4px;
}
.tw-panel-title {
  font-size: 10px; font-weight: 700; color: var(--text3);
  text-transform: uppercase; letter-spacing: 0.5px;
  margin-bottom: 8px; padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center;
}
.tw-panel-badge {
  font-size: 9px; font-weight: 600; padding: 1px 6px;
  border-radius: 2px; text-transform: uppercase; letter-spacing: 0.4px;
}

/* ── Route row ───────────────────────────────────────────────────────────── */
.tw-route-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 8px; margin: 2px 0;
  border-radius: 3px; cursor: pointer;
  transition: background 0.1s ease;
  border-left: 3px solid transparent;
}
.tw-route-row:hover { background: var(--surface2); }

/* ── Badge ───────────────────────────────────────────────────────────────── */
.tw-badge {
  font-size: 9px; font-weight: 600; padding: 2px 6px;
  border-radius: 2px; text-transform: uppercase;
  letter-spacing: 0.4px; white-space: nowrap;
}

/* ── Risk bar ────────────────────────────────────────────────────────────── */
.tw-risk-bar-bg  { background: var(--bg2); border-radius: 2px; height: 4px; margin-top: 3px; overflow: hidden; }
.tw-risk-bar-fill{ height: 4px; border-radius: 2px; transition: width 0.3s ease; }

/* ── Alert item ──────────────────────────────────────────────────────────── */
.tw-alert {
  padding: 6px 8px; margin: 2px 0; border-radius: 3px;
  border-left: 3px solid var(--border2);
  background: rgba(255,255,255,0.02);
  font-size: 11px;
}

/* ── Market row ──────────────────────────────────────────────────────────── */
.tw-market-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 5px 0; border-bottom: 1px solid var(--border); font-size: 11px;
}
.tw-market-row:last-child { border-bottom: none; }

/* ── News item ───────────────────────────────────────────────────────────── */
.tw-news {
  padding: 7px 8px; margin: 2px 0; border-radius: 3px;
  border-left: 2px solid var(--border2);
  background: rgba(255,255,255,0.01);
}

/* ── Intel brief ─────────────────────────────────────────────────────────── */
.tw-brief {
  background: rgba(59,130,246,0.06);
  border: 1px solid rgba(59,130,246,0.25);
  border-left: 3px solid var(--accent);
  border-radius: 4px; padding: 10px 12px; margin-bottom: 12px;
}

/* ── Comparison table ────────────────────────────────────────────────────── */
.tw-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.tw-table th { padding: 6px 8px; text-align: left; color: var(--text3); font-size: 9px;
               text-transform: uppercase; letter-spacing: 0.4px; border-bottom: 1px solid var(--border2); }
.tw-table td { padding: 7px 8px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.tw-table tr:hover td { background: rgba(255,255,255,0.02); }

/* ── Section label ───────────────────────────────────────────────────────── */
.tw-label {
  font-size: 9px; font-weight: 700; color: var(--text3);
  text-transform: uppercase; letter-spacing: 0.5px; margin: 10px 0 4px;
}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def render_header(crit: int, high: int, total: int, worst_status: str, count: int) -> None:
    dot_col = SC.get(worst_status, "#666")
    sbg     = SBG.get(worst_status, "rgba(100,100,100,0.1)")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    st.markdown(f"""
<div class="tw-header">
  <div style="display:flex;align-items:center;gap:20px">
    <div class="tw-header-logo">🌍 TRADEWATCH</div>
    <div style="display:flex;gap:14px">
      <span style="font-size:10px;color:#ef4444">
        <span class="tw-live-dot" style="background:#ef4444"></span>{crit} CRITICAL
      </span>
      <span style="font-size:10px;color:#f97316">{high} HIGH</span>
      <span style="font-size:10px;color:#666">{total} TOTAL</span>
    </div>
    <div style="font-size:10px;background:{sbg};border:1px solid {dot_col}44;
                border-radius:2px;padding:2px 8px;color:{dot_col}">
      {worst_status.upper()}
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:16px">
    <span style="font-size:10px;color:#22c55e">
      <span class="tw-live-dot" style="background:#22c55e"></span>LIVE
    </span>
    <span class="tw-header-meta">{now_str}{f" · #{count}" if count else ""}</span>
  </div>
</div>
""", unsafe_allow_html=True)


def render_nav() -> None:
    st.markdown('<div class="tw-nav-wrap">', unsafe_allow_html=True)
    c0, c1, c2, c3, c4, c5, _ = st.columns([1, 1, 1, 1, 1, 1, 3])
    with c0:
        st.page_link("app.py", label="Overview", icon="🌍")
    with c1:
        st.page_link("pages/0_Landing.py", label="Welcome", icon="🏠")
    with c2:
        st.page_link("pages/1_Route_Planner.py", label="Routes", icon="🗺️")
    with c3:
        st.page_link("pages/2_Intel_Feed.py", label="Intel", icon="📡")
    with c4:
        st.page_link("pages/3_Market_Costs.py", label="Market", icon="📊")
    with c5:
        st.page_link("pages/4_MariNav_Router.py", label="MariNav", icon="🧭")
    st.markdown('</div>', unsafe_allow_html=True)


def render_footer() -> None:
    st.markdown(f"""
<div style="background:#0a0a0a;border-top:1px solid #1a1a1a;padding:8px 16px;
            display:flex;justify-content:space-between;margin-top:8px">
  <span style="font-size:9px;color:#444">TradeWatch v5.0 · Shipping Route Intelligence</span>
  <span style="font-size:9px;color:#444">GDELT · AISStream · NewsAPI · Guardian · FRED · Open-Meteo · Ship&Bunker</span>
  <span style="font-size:9px;color:#444">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</span>
</div>
""", unsafe_allow_html=True)
