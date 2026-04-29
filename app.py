"""TradeWatch — Shipping Route Intelligence · worldmonitor-style"""

import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

from config import EVENT_TYPES
from sample_data import get_events_data
from api_integrations import APIClient
from analytics import RiskAnalytics
from maps import create_dashboard_map
from components import (
    filter_events,
    render_comparison_table,
    generate_intel_brief,
)
from dynamic_status import (
    compute_shipping_status,
    compute_risk_summary,
    compute_port_congestion,
    get_news_feed,
)
from api_config import CACHE_TTL_EVENTS

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TradeWatch",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════════════════════════
# CSS — worldmonitor design system
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@300;400;500;600;700&display=swap');

/* ── Reset & root ────────────────────────────────────────────────────────── */
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

/* ── Hide Streamlit chrome ───────────────────────────────────────────────── */
#MainMenu, footer, header,
button[data-testid="baseButton-headerNoPadding"],
section[data-testid="stSidebar"],
.stDeployButton,
[data-testid="collapsedControl"]  { display: none !important; }

/* ── Base ────────────────────────────────────────────────────────────────── */
.stApp                            { background: var(--bg) !important; }
.block-container                  { padding: 0 !important; max-width: 100% !important; }
section.main > div                { padding: 0 !important; }

/* ── Typography ─────────────────────────────────────────────────────────── */
p, span, div, label, li, td, th,
.stMarkdown, .stText              { color: var(--text) !important; font-size: 12px !important; }
h1, h2, h3                        { color: var(--text) !important; letter-spacing: 0.02em; }

/* ── Scrollbars ─────────────────────────────────────────────────────────── */
::-webkit-scrollbar               { width: 4px; height: 4px; }
::-webkit-scrollbar-track         { background: var(--bg); }
::-webkit-scrollbar-thumb         { background: #333; border-radius: 2px; }
::-webkit-scrollbar-thumb:hover   { background: #555; }

/* ── Plotly charts ──────────────────────────────────────────────────────── */
.js-plotly-plot .plotly            { background: transparent !important; }

/* ── Streamlit metric overrides ─────────────────────────────────────────── */
div[data-testid="metric-container"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: 4px !important;
  padding: 8px 10px !important;
}
div[data-testid="stMetricValue"]    { font-size: 14px !important; font-weight: 600 !important; }
div[data-testid="stMetricLabel"]    { font-size: 10px !important; color: var(--text3) !important; text-transform: uppercase; letter-spacing: 0.4px; }

/* ── Tabs ───────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"]  { background: var(--bg2) !important; border-bottom: 1px solid var(--border) !important; gap: 0; }
.stTabs [data-baseweb="tab"]       { background: transparent !important; color: var(--text3) !important;
                                     border-radius: 0 !important; padding: 8px 16px !important;
                                     font-size: 11px !important; font-weight: 500 !important;
                                     letter-spacing: 0.4px; text-transform: uppercase;
                                     border-bottom: 2px solid transparent !important; }
.stTabs [aria-selected="true"]     { color: var(--text) !important; border-bottom: 2px solid var(--accent) !important; }
.stTabs [data-baseweb="tab-panel"] { background: var(--bg) !important; padding: 16px !important; }

/* ── Expanders ──────────────────────────────────────────────────────────── */
div[data-testid="stExpander"]      { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 4px !important; }
div[data-testid="stExpander"] summary { font-size: 11px !important; color: var(--text2) !important; }

/* ── Buttons ────────────────────────────────────────────────────────────── */
.stButton > button                 { background: var(--surface2) !important; border: 1px solid var(--border) !important;
                                     color: var(--text2) !important; border-radius: 4px !important;
                                     font-size: 10px !important; padding: 4px 10px !important;
                                     text-transform: uppercase; letter-spacing: 0.4px;
                                     transition: all 0.15s ease; }
.stButton > button:hover           { border-color: var(--accent) !important; color: var(--text) !important; }

/* ── Inputs/selects ─────────────────────────────────────────────────────── */
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
.stTextInput > div > div          { background: var(--surface2) !important; border-color: var(--border) !important;
                                    font-size: 12px !important; border-radius: 4px !important; }

/* ── Dataframe ──────────────────────────────────────────────────────────── */
.stDataFrame                       { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 4px !important; }
.stDataFrame table                 { font-size: 11px !important; }
.stDataFrame th                    { background: var(--bg2) !important; color: var(--text3) !important;
                                     font-size: 9px !important; text-transform: uppercase; letter-spacing: 0.4px; }

/* ── Dividers ───────────────────────────────────────────────────────────── */
hr                                 { border-color: var(--border) !important; margin: 8px 0 !important; }

/* ── Alerts ─────────────────────────────────────────────────────────────── */
div[data-testid="stAlert"]         { border-radius: 4px !important; font-size: 11px !important; }

/* ── Sliders ────────────────────────────────────────────────────────────── */
div[data-testid="stSlider"]        { padding: 4px 0 !important; }

/* ── Spinner ────────────────────────────────────────────────────────────── */
div[data-testid="stSpinner"]       { color: var(--text3) !important; font-size: 11px !important; }

/* ── Custom components ──────────────────────────────────────────────────── */

/* Header strip */
.tw-header {
  display: flex; align-items: center; justify-content: space-between;
  height: 40px; padding: 0 16px;
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 999;
}
.tw-header-logo { font-size: 13px; font-weight: 700; color: var(--text); letter-spacing: 0.06em; }
.tw-header-meta { font-size: 10px; color: var(--text3); letter-spacing: 0.3px; }

/* Live dot */
.tw-live-dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  margin-right: 5px; vertical-align: middle;
  animation: live-blink 1.5s ease-in-out infinite;
}
@keyframes live-blink {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.4; transform: scale(0.85); }
}

/* Panel */
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

/* Route row */
.tw-route-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 8px; margin: 2px 0;
  border-radius: 3px; cursor: pointer;
  transition: background 0.1s ease;
  border-left: 3px solid transparent;
}
.tw-route-row:hover { background: var(--surface2); }

/* Status badge */
.tw-badge {
  font-size: 9px; font-weight: 600; padding: 2px 6px;
  border-radius: 2px; text-transform: uppercase;
  letter-spacing: 0.4px; white-space: nowrap;
}

/* Risk score bar */
.tw-risk-bar-bg {
  background: var(--bg2); border-radius: 2px; height: 4px;
  margin-top: 3px; overflow: hidden;
}
.tw-risk-bar-fill {
  height: 4px; border-radius: 2px; transition: width 0.3s ease;
}

/* Alert item */
.tw-alert {
  padding: 6px 8px; margin: 2px 0; border-radius: 3px;
  border-left: 3px solid var(--border2);
  background: rgba(255,255,255,0.02);
  font-size: 11px;
}

/* Market row */
.tw-market-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 5px 0; border-bottom: 1px solid var(--border);
  font-size: 11px;
}
.tw-market-row:last-child { border-bottom: none; }

/* News item */
.tw-news {
  padding: 7px 8px; margin: 2px 0; border-radius: 3px;
  border-left: 2px solid var(--border2);
  background: rgba(255,255,255,0.01);
}

/* Intel brief */
.tw-brief {
  background: rgba(59,130,246,0.06);
  border: 1px solid rgba(59,130,246,0.25);
  border-left: 3px solid var(--accent);
  border-radius: 4px; padding: 10px 12px; margin-bottom: 12px;
}

/* Comparison table */
.tw-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.tw-table th { padding: 6px 8px; text-align: left; color: var(--text3); font-size: 9px;
               text-transform: uppercase; letter-spacing: 0.4px; border-bottom: 1px solid var(--border2); }
.tw-table td { padding: 7px 8px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.tw-table tr:hover td { background: rgba(255,255,255,0.02); }

/* Section label */
.tw-label {
  font-size: 9px; font-weight: 700; color: var(--text3);
  text-transform: uppercase; letter-spacing: 0.5px; margin: 10px 0 4px;
}

/* Port badge */
.tw-port {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 8px; margin: 2px; border-radius: 3px;
  border: 1px solid var(--border); font-size: 10px;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=CACHE_TTL_EVENTS)
def _load_core_data():
    events         = get_events_data()
    oil_price      = APIClient.get_oil_price()
    shipping_idx   = APIClient.get_shipping_index()
    exchange_rates = APIClient.get_exchange_rates()
    return events, oil_price, shipping_idx, exchange_rates


with st.spinner(""):
    events_df, oil_price, shipping_index, exchange_rates = _load_core_data()

events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()

with st.spinner(""):
    shipping_df  = compute_shipping_status(events_json)
    risk_df      = compute_risk_summary(events_json)
    port_cong_df = compute_port_congestion(events_json)
    news_feed_df = get_news_feed()

analytics      = RiskAnalytics.get_summary_metrics(events_df, oil_price, shipping_index)
filtered_events = filter_events(events_df)

auto_interval   = st.session_state.get("refresh_interval", 10)
count           = st_autorefresh(interval=auto_interval * 60 * 1000, limit=None, key="tw_refresh")


# ── Derived values ────────────────────────────────────────────────────────────
def _parse_delay_h(s):
    try:    return float(str(s).replace(" hours","").replace("+","").strip())
    except: return 0.0

if len(shipping_df) > 0:
    shipping_df["_delay_h"]   = shipping_df["Average Delay"].apply(_parse_delay_h)
    shipping_df["_composite"] = shipping_df["Risk Score"] / 100 + shipping_df["_delay_h"] / 48
    best_route = shipping_df.loc[shipping_df["_composite"].idxmin(), "Route"]
    best_score = int(shipping_df.loc[shipping_df["_composite"].idxmin(), "Risk Score"])
    worst_status = shipping_df.sort_values("Risk Score", ascending=False).iloc[0]["Status"]
else:
    best_route, best_score, worst_status = "N/A", 0, "Operational"

SC = {
    "Operational":              "#22c55e",
    "Operational - Alert":      "#eab308",
    "Operational - High Risk":  "#f97316",
    "Critical - Avoid":         "#ef4444",
}
SBG = {
    "Operational":              "rgba(34,197,94,0.1)",
    "Operational - Alert":      "rgba(234,179,8,0.1)",
    "Operational - High Risk":  "rgba(249,115,22,0.1)",
    "Critical - Avoid":         "rgba(239,68,68,0.1)",
}
dot_col = SC.get(worst_status, "#666")

RISK_COL = lambda s: "#ef4444" if s >= 70 else "#f97316" if s >= 40 else "#eab308" if s >= 15 else "#22c55e"
TOPIC_COLOR = {"conflict":"#ef4444","shipping":"#3b82f6","weather":"#22c55e","trade":"#a855f7","other":"#666666"}
TOPIC_ICON  = {"conflict":"💥","shipping":"🚢","weather":"⛈","trade":"📦","other":"📰"}
CONG_COL    = {"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"}


# ══════════════════════════════════════════════════════════════════════════════
# HEADER STRIP
# ══════════════════════════════════════════════════════════════════════════════

crit  = analytics.get("critical_events", 0)
high  = analytics.get("high_events", 0)
total = analytics.get("total_events", 0)
now_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

st.markdown(f"""
<div class="tw-header">
  <div style="display:flex;align-items:center;gap:20px">
    <div class="tw-header-logo">🌍 TRADEWATCH</div>
    <div style="display:flex;gap:14px">
      <span style="font-size:10px;color:#ef4444">
        <span class="tw-live-dot" style="background:#ef4444"></span>
        {crit} CRITICAL
      </span>
      <span style="font-size:10px;color:#f97316">{high} HIGH</span>
      <span style="font-size:10px;color:#666">{total} TOTAL</span>
    </div>
    <div style="font-size:10px;background:{SBG.get(worst_status,'rgba(100,100,100,0.1)')};
                border:1px solid {dot_col}44;border-radius:2px;padding:2px 8px;color:{dot_col}">
      {worst_status.upper()}
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:16px">
    <span style="font-size:10px;color:#22c55e">
      <span class="tw-live-dot" style="background:#22c55e"></span>LIVE
    </span>
    <span class="tw-header-meta">{now_str} · #{count}</span>
  </div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SPLIT — MAP (60%) │ PANELS (40%)
# ══════════════════════════════════════════════════════════════════════════════

map_col, panels_col = st.columns([3, 2], gap="small")

# ─────────────────────────────────────────────────────────────────────────────
# LEFT — GLOBE MAP
# ─────────────────────────────────────────────────────────────────────────────
with map_col:
    route_statuses = {}
    if len(shipping_df) > 0:
        route_statuses = dict(zip(shipping_df["Route"], shipping_df["Status"]))

    globe_fig = create_dashboard_map(
        filtered_events,
        show_routes=True,
        route_statuses=route_statuses,
        port_congestion_df=port_cong_df if len(port_cong_df) > 0 else None,
    )
    # Override map background to match design
    globe_fig.update_layout(
        paper_bgcolor="#0a0a0a",
        margin=dict(l=0, r=0, t=0, b=0),
        height=520,
    )
    globe_fig.update_geos(bgcolor="#0a0a0a", landcolor="#0a2018", oceancolor="#020a08")
    st.plotly_chart(globe_fig, use_container_width=True,
                    config={"scrollZoom": True, "displayModeBar": False})

    # Recommended route bar below map
    if best_route != "N/A":
        rc = RISK_COL(best_score)
        st.markdown(f"""
<div style="background:rgba(34,197,94,0.05);border:1px solid rgba(34,197,94,0.2);
            border-left:3px solid #22c55e;border-radius:3px;padding:8px 12px;
            display:flex;justify-content:space-between;align-items:center">
  <span style="font-size:11px;color:#22c55e;font-weight:600">
    ✓ RECOMMENDED ROUTE
  </span>
  <span style="font-size:13px;font-weight:700;color:#e8e8e8">{best_route}</span>
  <span style="font-size:11px;color:{rc}">Risk {best_score}/100</span>
  <span style="font-size:10px;color:#666">lowest risk + delay composite</span>
</div>""", unsafe_allow_html=True)

    # Route mini-strip (compact row below map)
    if len(shipping_df) > 0:
        st.markdown('<div class="tw-label" style="margin-top:10px">Chokepoints</div>', unsafe_allow_html=True)
        strip_cols = st.columns(len(shipping_df))
        for col, (_, row) in zip(strip_cols, shipping_df.iterrows()):
            with col:
                sc      = SC.get(row["Status"], "#666")
                score   = int(row["Risk Score"])
                rc_fill = RISK_COL(score)
                name    = row["Route"].replace("Canal","C.").replace("Strait of","Str.").replace("Strait","Str.").replace("English Channel","Eng.Ch.")
                st.markdown(f"""
<div style="background:var(--surface);border:1px solid var(--border);border-top:2px solid {sc};
            border-radius:3px;padding:7px 8px;text-align:center">
  <div style="font-size:9px;font-weight:700;color:{sc};text-transform:uppercase;
              letter-spacing:0.3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{name}</div>
  <div style="font-size:18px;font-weight:700;color:{rc_fill};line-height:1.2;margin-top:2px">{score}</div>
  <div style="font-size:8px;color:#666">/100</div>
  <div class="tw-risk-bar-bg" style="margin-top:4px">
    <div class="tw-risk-bar-fill" style="width:{score}%;background:{rc_fill}"></div>
  </div>
  <div style="font-size:8px;color:#666;margin-top:3px">{row["Average Delay"]}</div>
</div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# RIGHT — PANELS GRID
# ─────────────────────────────────────────────────────────────────────────────
with panels_col:

    # ── PANEL: Route Status ───────────────────────────────────────────────────
    if len(shipping_df) > 0:
        st.markdown(f"""
<div class="tw-panel">
  <div class="tw-panel-title">
    Route Status
    <span class="tw-panel-badge" style="background:rgba(59,130,246,0.12);color:#3b82f6;border:1px solid rgba(59,130,246,0.3)">
      {len(shipping_df)} routes
    </span>
  </div>""", unsafe_allow_html=True)

        route_rows_html = ""
        for _, row in shipping_df.sort_values("Risk Score", ascending=False).iterrows():
            sc     = SC.get(row["Status"], "#666")
            sbg    = SBG.get(row["Status"], "transparent")
            score  = int(row["Risk Score"])
            rc     = RISK_COL(score)
            is_sel = st.session_state.get("selected_route") == row["Route"]
            sel_bg = "background:rgba(59,130,246,0.05);" if is_sel else ""
            route_rows_html += f"""
<div class="tw-route-row" style="{sel_bg}border-left-color:{sc}">
  <div>
    <div style="font-size:11px;font-weight:600;color:#e8e8e8">{row['Route']}</div>
    <div style="font-size:9px;color:#666;margin-top:1px">{row['Nearby Events']} events · {row['News Signals']} signals</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:15px;font-weight:700;color:{rc}">{score}</div>
    <div style="font-size:8px;color:#555">/100</div>
  </div>
  <div>
    <span class="tw-badge" style="background:{sbg};color:{sc};border:1px solid {sc}44">
      {row['Status'].replace('Operational - ','').replace('Critical - ','')}
    </span>
    <div style="font-size:9px;color:#666;margin-top:2px;text-align:right">{row['Cost Impact']} · {row['Average Delay']}</div>
  </div>
</div>"""

        st.markdown(route_rows_html + "</div>", unsafe_allow_html=True)

        # Route select buttons (invisible but functional)
        sel_cols = st.columns(len(shipping_df))
        for col, (_, row) in zip(sel_cols, shipping_df.iterrows()):
            with col:
                if st.button(f"▸", key=f"sel_{row['Route']}", use_container_width=True,
                             help=f"Select {row['Route']}"):
                    st.session_state["selected_route"] = row["Route"]
                    st.rerun()

    # ── PANEL: Market ─────────────────────────────────────────────────────────
    market_html = '<div class="tw-panel"><div class="tw-panel-title">Market Pulse</div>'
    if oil_price:
        pct = (oil_price - 90) / 90 * 100
        delta_col = "#22c55e" if pct < 0 else "#ef4444"
        delta_sym = "▲" if pct >= 0 else "▼"
        market_html += f"""
<div class="tw-market-row">
  <span style="color:#aaa">🛢 WTI Crude</span>
  <span style="font-weight:600">${oil_price:.2f}<span style="color:{delta_col};font-size:9px;margin-left:6px">{delta_sym}{abs(pct):.1f}%</span></span>
</div>"""

    if shipping_index:
        trend_sym = "▲" if shipping_index > 3500 else "▼" if shipping_index < 2500 else "─"
        trend_col = "#ef4444" if shipping_index > 3500 else "#22c55e" if shipping_index < 2500 else "#666"
        market_html += f"""
<div class="tw-market-row">
  <span style="color:#aaa">⚓ Freight Idx</span>
  <span style="font-weight:600">{shipping_index:,.0f}<span style="color:{trend_col};font-size:9px;margin-left:6px">{trend_sym}</span></span>
</div>"""

    if exchange_rates:
        for ccy, rate in list(exchange_rates.items())[:4]:
            market_html += f"""
<div class="tw-market-row">
  <span style="color:#aaa">💱 USD/{ccy}</span>
  <span style="font-weight:600">{rate:.4f}</span>
</div>"""

    if oil_price:
        bunker = oil_price * 6.35
        market_html += f"""
<div class="tw-market-row">
  <span style="color:#aaa">⛽ Bunker HFO</span>
  <span style="font-weight:600">${bunker:.0f}/ton</span>
</div>"""

    market_html += "</div>"
    st.markdown(market_html, unsafe_allow_html=True)

    # ── PANEL: Live Events ────────────────────────────────────────────────────
    IMPACT_COL = {"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"}
    IMPACT_ICON= {"Critical":"🔴","High":"🟠","Medium":"🟡","Low":"🟢"}

    events_html = f"""
<div class="tw-panel">
  <div class="tw-panel-title">
    Live Events
    <span class="tw-panel-badge" style="background:rgba(239,68,68,0.1);color:#ef4444;border:1px solid rgba(239,68,68,0.3)">
      {len(filtered_events)} active
    </span>
  </div>"""

    if not filtered_events.empty:
        recent = filtered_events.sort_values("date", ascending=False).head(7)
        for _, ev in recent.iterrows():
            ic  = IMPACT_COL.get(ev["impact"], "#666")
            ico = IMPACT_ICON.get(ev["impact"], "⚪")
            try:
                ts = pd.Timestamp(ev["date"]).strftime("%b %d %H:%M")
            except:
                ts = ""
            desc = str(ev.get("description",""))[:60]
            events_html += f"""
<div class="tw-alert" style="border-left-color:{ic}">
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="color:{ic};font-size:9px;font-weight:700;text-transform:uppercase">{ico} {ev['impact']} · {ev['type']}</span>
    <span style="color:#555;font-size:9px">{ts}</span>
  </div>
  <div style="font-size:10px;color:#aaa">{ev['location']} — {desc}</div>
</div>"""
    else:
        events_html += '<div style="color:#555;font-size:11px;padding:8px">No active events</div>'

    events_html += "</div>"
    st.markdown(events_html, unsafe_allow_html=True)

    # ── PANEL: Port Congestion ────────────────────────────────────────────────
    ports_html = f"""
<div class="tw-panel">
  <div class="tw-panel-title">Port Congestion</div>"""

    if len(port_cong_df) > 0:
        for _, p in port_cong_df.sort_values("Score", ascending=False).iterrows():
            cc  = CONG_COL.get(p["Congestion"], "#666")
            cbg = f"background:rgba{tuple(int(cc[i:i+2],16) for i in (1,3,5))}0.08)"
            score = int(p["Score"])
            ports_html += f"""
<div style="display:flex;align-items:center;justify-content:space-between;
            padding:5px 8px;margin:2px 0;border-radius:3px;border-left:3px solid {cc};
            background:rgba(255,255,255,0.01)">
  <span style="font-size:11px;font-weight:600;color:#e8e8e8">{p['Port']}</span>
  <div style="flex:1;margin:0 10px">
    <div style="background:#111;border-radius:1px;height:3px">
      <div style="background:{cc};width:{score}%;height:3px;border-radius:1px"></div>
    </div>
  </div>
  <div style="text-align:right;min-width:60px">
    <span class="tw-badge" style="background:{cc}18;color:{cc};border:1px solid {cc}33">
      {p['Congestion']}
    </span>
  </div>
  <span style="font-size:9px;color:#555;margin-left:8px;min-width:20px">{score}</span>
</div>"""
    else:
        ports_html += '<div style="color:#555;font-size:11px;padding:8px">Loading port data…</div>'

    ports_html += "</div>"
    st.markdown(ports_html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TABS SECTION
# ══════════════════════════════════════════════════════════════════════════════

tab1, tab2, tab3 = st.tabs([
    "ROUTE PLANNER",
    "INTEL FEED",
    "MARKET & COSTS",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Route Planner
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    planner_left, planner_right = st.columns([3, 2], gap="large")

    with planner_left:
        # Scenario selector
        route_names = shipping_df["Route"].tolist() if len(shipping_df) > 0 else []
        sc_col1, sc_col2 = st.columns([3, 1])
        with sc_col1:
            scenario_route = st.selectbox(
                "SIMULATE ROUTE FAILURE →",
                ["None (live data)"] + route_names,
                key="scenario_route",
                label_visibility="visible",
            )
        with sc_col2:
            event_filter = st.selectbox("TYPE", ["All Types"] + list(EVENT_TYPES.keys()),
                                        key="event_type_tab", label_visibility="visible")

        scenario_overrides = {}
        if scenario_route != "None (live data)":
            scenario_overrides[scenario_route] = "Critical - Avoid"
            st.markdown(f"""
<div style="background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.2);
            border-left:3px solid #ef4444;border-radius:3px;padding:6px 10px;margin-bottom:8px;
            font-size:11px;color:#ef4444">
  ⚠ SCENARIO ACTIVE — {scenario_route} overridden to CRITICAL · AVOID
</div>""", unsafe_allow_html=True)

        # Comparison table
        if len(shipping_df) > 0:
            st.markdown('<div class="tw-label">Route Comparison Matrix</div>', unsafe_allow_html=True)
            render_comparison_table(
                shipping_df,
                port_cong_df if len(port_cong_df) > 0 else pd.DataFrame(),
                best_route=best_route or "",
                scenario_overrides=scenario_overrides if scenario_overrides else None,
            )
        else:
            st.info("Computing route data…")

        # Regional risk table
        st.markdown('<div class="tw-label" style="margin-top:16px">Regional Risk Summary</div>', unsafe_allow_html=True)
        if len(risk_df) > 0:
            rows = ""
            for _, row in risk_df.iterrows():
                rc_ = {"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"}.get(row["Risk Level"],"#666")
                rows += f"""<tr>
<td style="padding:7px 8px;color:#e8e8e8;font-weight:500">{row['Region']}</td>
<td style="padding:7px 8px"><span class="tw-badge" style="background:{rc_}18;color:{rc_};border:1px solid {rc_}33">{row['Risk Level']}</span></td>
<td style="padding:7px 8px;color:#aaa;text-align:center">{row['Active Events']}</td>
<td style="padding:7px 8px;color:#aaa;text-align:center">{row['Affected Routes']}</td>
<td style="padding:7px 8px;color:#666;text-align:center">{row['Business Impact']}</td>
</tr>"""
            st.markdown(f"""
<table class="tw-table">
<thead><tr>
  <th>Region</th><th>Risk</th><th>Events</th><th>Routes</th><th>Impact</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>""", unsafe_allow_html=True)

        # Timeline chart
        st.markdown('<div class="tw-label" style="margin-top:16px">Event Activity — Last 30 Days</div>', unsafe_allow_html=True)
        if len(filtered_events) > 0:
            daily = (pd.DataFrame({"date": filtered_events["date"].dt.date, "n": 1})
                     .groupby("date").sum().reset_index())
            fig_tl = go.Figure()
            fig_tl.add_trace(go.Scatter(
                x=daily["date"], y=daily["n"],
                fill="tozeroy",
                fillcolor="rgba(239,68,68,0.08)",
                mode="lines",
                line=dict(color="#ef4444", width=1.5),
                name="Events",
            ))
            fig_tl.update_layout(
                paper_bgcolor="#0a0a0a", plot_bgcolor="#111111",
                font_color="#666", height=160,
                margin=dict(t=4, b=0, l=0, r=0),
                xaxis=dict(showgrid=False, tickfont_size=9, tickcolor="#444",
                           ticklen=3, linecolor="#2a2a2a"),
                yaxis=dict(showgrid=True, gridcolor="#1a1a1a", tickfont_size=9,
                           tickcolor="#444", ticklen=3),
                hovermode="x unified", showlegend=False,
            )
            st.plotly_chart(fig_tl, use_container_width=True,
                            config={"displayModeBar": False})

    with planner_right:
        # ── Voyage Cost Estimator ─────────────────────────────────────────────
        st.markdown('<div class="tw-label">Voyage Cost Estimator</div>', unsafe_allow_html=True)

        wti   = oil_price if oil_price else 78.45
        bunker = wti * 6.35
        st.markdown(f"""
<div style="background:var(--surface);border:1px solid var(--border);border-radius:3px;
            padding:8px 10px;margin-bottom:10px;font-size:11px;color:#aaa">
  WTI <b style="color:#e8e8e8">${wti:.2f}/bbl</b>
  &nbsp;→&nbsp; Bunker HFO <b style="color:#e8e8e8">${bunker:.0f}/ton</b>
</div>""", unsafe_allow_html=True)

        vessel_preset = st.selectbox("Vessel Type", [
            "Custom",
            "Small Feeder (600 TEU) — 18 t/day",
            "Medium Feeder (1,500 TEU) — 30 t/day",
            "Panamax (4,500 TEU) — 55 t/day",
            "Post-Panamax (8,000 TEU) — 80 t/day",
            "ULCS (20,000+ TEU) — 130 t/day",
            "Suezmax Tanker — 65 t/day",
            "VLCC Tanker — 90 t/day",
            "Capesize Bulk — 50 t/day",
        ], key="vessel_preset")
        preset_cons = {
            "Small Feeder (600 TEU) — 18 t/day": 18,
            "Medium Feeder (1,500 TEU) — 30 t/day": 30,
            "Panamax (4,500 TEU) — 55 t/day": 55,
            "Post-Panamax (8,000 TEU) — 80 t/day": 80,
            "ULCS (20,000+ TEU) — 130 t/day": 130,
            "Suezmax Tanker — 65 t/day": 65,
            "VLCC Tanker — 90 t/day": 90,
            "Capesize Bulk — 50 t/day": 50,
        }
        cons   = st.number_input("Fuel Consumption (t/day)", 1.0, 500.0,
                                  float(preset_cons.get(vessel_preset, 50)), 1.0, key="cons")
        vdays  = st.number_input("Voyage Duration (days)", 1, 120, 14, 1, key="vdays")

        # Route selector — pre-fill from selected card
        r_opts   = ["No specific route"] + route_names
        def_idx  = 0
        sel      = st.session_state.get("selected_route")
        if sel and sel in r_opts: def_idx = r_opts.index(sel)
        sel_route = st.selectbox("Shipping Route", r_opts, index=def_idx, key="calc_route")

        spd_red    = st.slider("Speed Reduction (%)", 0, 30, 0, 5, key="spd_red")
        cargo_val  = st.number_input("Cargo Value USD", 0, 500_000_000, 0, 100_000,
                                     format="%d", key="cargo_val")

        # Calculate
        surcharge  = 0.0
        route_lbl  = "N/A"
        if sel_route != "No specific route" and len(shipping_df) > 0:
            rr = shipping_df[shipping_df["Route"] == sel_route]
            if len(rr) > 0:
                route_lbl = rr.iloc[0]["Status"]
                try:    surcharge = float(rr.iloc[0]["Cost Impact"].replace("%","").replace("+","")) / 100
                except: surcharge = int(rr.iloc[0]["Risk Score"]) / 400

        eff_days   = vdays * (1 + spd_red / 100)
        fuel_tons  = cons * eff_days
        base_cost  = fuel_tons * bunker
        risk_cost  = base_cost * surcharge
        total_cost = base_cost + risk_cost
        insurance  = 0.0
        if cargo_val > 0:
            pct = 0.003 if surcharge > 0.15 else 0.0015 if surcharge > 0.05 else 0.001
            insurance = cargo_val * pct

        # Results
        st.markdown(f"""
<div style="background:var(--surface);border:1px solid var(--border);border-radius:4px;
            padding:12px 14px;margin-top:10px">
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
    <div>
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Base Fuel</div>
      <div style="font-size:18px;font-weight:700;color:#e8e8e8">${base_cost:,.0f}</div>
    </div>
    <div>
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Risk Surcharge</div>
      <div style="font-size:18px;font-weight:700;color:#f97316">${risk_cost:,.0f}</div>
    </div>
    <div style="grid-column:1/-1;border-top:1px solid var(--border);padding-top:8px;margin-top:4px">
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Total Voyage Cost</div>
      <div style="font-size:24px;font-weight:700;color:#22c55e">${total_cost:,.0f}</div>
    </div>
    {"" if cargo_val == 0 else f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Insurance Est.</div><div style="font-size:14px;font-weight:600;color:#eab308">${insurance:,.0f}</div></div>'}
  </div>
  <div style="margin-top:8px;font-size:9px;color:#444">
    {fuel_tons:,.0f}t fuel · {eff_days:.1f} days · +{surcharge*100:.0f}% surcharge
    {f" · {route_lbl}" if route_lbl != "N/A" else ""}
  </div>
</div>""", unsafe_allow_html=True)

        # Bar chart
        bd = {"Base Fuel": base_cost}
        if risk_cost > 0: bd["Risk Surcharge"] = risk_cost
        if insurance > 0: bd["Insurance"]      = insurance

        fig_br = go.Figure(go.Bar(
            x=list(bd.keys()), y=list(bd.values()),
            marker_color=["#3b82f6","#f97316","#eab308"][:len(bd)],
            text=[f"${v:,.0f}" for v in bd.values()],
            textposition="outside",
            textfont=dict(color="#666", size=9),
        ))
        fig_br.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#111111",
            font_color="#666", height=160,
            margin=dict(t=20, b=0, l=0, r=0), showlegend=False,
            xaxis=dict(tickfont_size=9, tickcolor="#444", linecolor="#2a2a2a"),
            yaxis=dict(showgrid=True, gridcolor="#1a1a1a", tickfont_size=9, showticklabels=False),
        )
        st.plotly_chart(fig_br, use_container_width=True, config={"displayModeBar": False})


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — Intel Feed
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    # Intelligence brief
    brief_lines = generate_intel_brief(filtered_events, news_feed_df, shipping_df)
    if brief_lines:
        brief_html = "".join(
            f'<div style="font-size:11px;color:#aaa;padding:3px 0;border-bottom:1px solid #1a1a1a">{ln}</div>'
            for ln in brief_lines
        )
        st.markdown(f'<div class="tw-brief"><div style="font-size:9px;font-weight:700;color:#3b82f6;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Intelligence Brief</div>{brief_html}</div>',
                    unsafe_allow_html=True)

    feed_left, feed_right = st.columns([1, 1], gap="large")

    with feed_left:
        # Regional risk with recommended actions
        st.markdown('<div class="tw-label">Regional Risk Assessment</div>', unsafe_allow_html=True)
        if len(risk_df) > 0:
            rows = ""
            for _, row in risk_df.iterrows():
                rc_ = {"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"}.get(row["Risk Level"],"#666")
                rows += f"""<tr>
<td style="padding:7px 8px;color:#e8e8e8">{row['Region']}</td>
<td style="padding:7px 8px"><span class="tw-badge" style="background:{rc_}18;color:{rc_};border:1px solid {rc_}33">{row['Risk Level']}</span></td>
<td style="padding:7px 8px;text-align:center;color:#888">{row['Active Events']}</td>
</tr>"""
            st.markdown(f"""
<table class="tw-table">
<thead><tr><th>Region</th><th>Risk</th><th>Events</th></tr></thead>
<tbody>{rows}</tbody>
</table>""", unsafe_allow_html=True)

        # Recommended actions
        alerts = RiskAnalytics.get_regional_alerts(filtered_events, threshold_hours=48)
        if alerts:
            st.markdown('<div class="tw-label" style="margin-top:12px">Recommended Actions</div>', unsafe_allow_html=True)
            for alert in alerts[:5]:
                act = alert.get("action","")
                loc = alert.get("location","")
                imp = alert.get("impact","")
                ac  = {"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"}.get(imp,"#666")
                if act:
                    st.markdown(f"""
<div style="border-left:2px solid {ac};padding:5px 10px;margin:3px 0;
            background:rgba(255,255,255,0.01);border-radius:0 3px 3px 0;font-size:11px">
  <span style="color:{ac};font-weight:600">{loc}</span>
  <span style="color:#888"> — {act}</span>
</div>""", unsafe_allow_html=True)

        # Event type charts
        st.markdown('<div class="tw-label" style="margin-top:14px">Event Breakdown</div>', unsafe_allow_html=True)
        if len(filtered_events) > 0:
            ec = filtered_events["type"].value_counts()
            fig_ec = px.bar(x=ec.index, y=ec.values,
                            color=ec.values, color_continuous_scale=["#222","#ef4444"])
            fig_ec.update_layout(
                paper_bgcolor="#0a0a0a", plot_bgcolor="#111",
                font_color="#666", height=160,
                margin=dict(t=4, b=0, l=0, r=0),
                xaxis=dict(tickangle=-30, tickfont_size=9, tickcolor="#444", linecolor="#2a2a2a"),
                yaxis=dict(gridcolor="#1a1a1a", tickfont_size=9),
                showlegend=False, coloraxis_showscale=False,
            )
            st.plotly_chart(fig_ec, use_container_width=True, config={"displayModeBar": False})

    with feed_right:
        st.markdown('<div class="tw-label">Live Intelligence Feed</div>', unsafe_allow_html=True)

        # Topic pills
        active_topic = st.session_state.get("news_topic_filter", "All")
        tp_cols = st.columns(6)
        for tc, t in zip(tp_cols, ["All","conflict","shipping","trade","weather","other"]):
            lbl = "ALL" if t == "All" else t[:4].upper()
            if tc.button(lbl, key=f"tp_{t}",
                         type="primary" if active_topic == t else "secondary",
                         use_container_width=True):
                st.session_state["news_topic_filter"] = t
                st.rerun()

        active_topic = st.session_state.get("news_topic_filter", "All")
        disp = news_feed_df if active_topic == "All" else news_feed_df[news_feed_df["topic"] == active_topic]
        st.markdown(f'<div style="font-size:9px;color:#555;margin-bottom:6px">{len(disp)} articles</div>', unsafe_allow_html=True)

        news_html = ""
        for _, art in disp.head(30).iterrows():
            topic  = art.get("topic","other")
            tc_    = TOPIC_COLOR.get(topic,"#666")
            icon   = TOPIC_ICON.get(topic,"📰")
            try:   ts = pd.Timestamp(art["date"]).strftime("%b %d %H:%M")
            except: ts = ""
            title  = str(art["title"])[:90] + ("…" if len(str(art["title"])) > 90 else "")
            source = str(art["source"])[:20]
            url    = str(art["url"])
            news_html += f"""
<div class="tw-news" style="border-left-color:{tc_}">
  <div style="color:#555;font-size:9px;margin-bottom:2px">{icon} {ts} · {source}</div>
  <a href="{url}" target="_blank"
     style="color:#ccc;text-decoration:none;font-size:11px;line-height:1.4">
    {title}
  </a>
</div>"""

        if news_html:
            st.markdown(
                f'<div style="height:560px;overflow-y:auto;padding-right:4px">{news_html}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info("No articles loaded.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — Market & Costs
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    mc1, mc2, mc3 = st.columns(3)

    # Financial impact
    cost_impact = RiskAnalytics.calculate_cost_impact(filtered_events, oil_price, {})
    mc1.metric("Daily Cost Impact",   f"${cost_impact['daily_cost_increase_usd']:,.0f}")
    mc2.metric("Monthly Projection",  f"${cost_impact['monthly_cost_increase_usd']:,.0f}")
    mc3.metric("Reference Fleet",     f"~{cost_impact['affected_vessels']} vessels/day")

    st.markdown('<div class="tw-label" style="margin-top:14px">Cost Impact Over Time</div>', unsafe_allow_html=True)
    cost_data = pd.DataFrame({
        "Period": ["Daily","Weekly","Monthly"],
        "USD":    [cost_impact["daily_cost_increase_usd"],
                   cost_impact["weekly_cost_increase_usd"],
                   cost_impact["monthly_cost_increase_usd"]],
    })
    fig_cost = go.Figure(go.Bar(
        x=cost_data["Period"], y=cost_data["USD"],
        marker_color=["#3b82f6","#f97316","#ef4444"],
        text=[f"${v:,.0f}" for v in cost_data["USD"]],
        textposition="outside",
        textfont=dict(color="#666", size=9),
    ))
    fig_cost.update_layout(
        paper_bgcolor="#0a0a0a", plot_bgcolor="#111",
        font_color="#666", height=200,
        margin=dict(t=20, b=0, l=0, r=0), showlegend=False,
        xaxis=dict(tickfont_size=10, tickcolor="#444", linecolor="#2a2a2a"),
        yaxis=dict(gridcolor="#1a1a1a", tickfont_size=9, showticklabels=False),
    )
    st.plotly_chart(fig_cost, use_container_width=True, config={"displayModeBar": False})

    st.markdown('<div class="tw-label" style="margin-top:14px">Chokepoint Delay & Cost Table</div>', unsafe_allow_html=True)
    if len(shipping_df) > 0:
        rows = ""
        for _, row in shipping_df.sort_values("Risk Score", ascending=False).iterrows():
            sc_  = SC.get(row["Status"],"#666")
            rs   = int(row["Risk Score"])
            rc_  = RISK_COL(rs)
            rows += f"""<tr>
<td style="padding:7px 8px;font-weight:500;color:#e8e8e8">{row['Route']}</td>
<td style="padding:7px 8px"><span style="color:{sc_};font-size:9px;font-weight:700">{row['Status']}</span></td>
<td style="padding:7px 8px;font-weight:700;color:{rc_}">{rs}</td>
<td style="padding:7px 8px;color:#aaa">{row['Average Delay']}</td>
<td style="padding:7px 8px;color:#aaa">{row['Cost Impact']}</td>
<td style="padding:7px 8px;color:#666;text-align:center">{row['Nearby Events']}</td>
</tr>"""
        st.markdown(f"""
<table class="tw-table">
<thead><tr>
  <th>Route</th><th>Status</th><th>Risk</th><th>Delay</th><th>Cost Δ</th><th>Events</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>""", unsafe_allow_html=True)

    # Port congestion detail
    st.markdown('<div class="tw-label" style="margin-top:16px">Port Congestion Detail</div>', unsafe_allow_html=True)
    if len(port_cong_df) > 0:
        fig_ports = px.bar(
            port_cong_df.sort_values("Score", ascending=False),
            x="Port", y="Score",
            color="Congestion",
            color_discrete_map={"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"},
        )
        fig_ports.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#111",
            font_color="#666", height=220,
            margin=dict(t=4, b=0, l=0, r=0),
            legend=dict(bgcolor="rgba(0,0,0,0.5)", font_color="#888", font_size=9, bordercolor="#2a2a2a", borderwidth=1),
            xaxis=dict(tickangle=-30, tickfont_size=9, tickcolor="#444", linecolor="#2a2a2a"),
            yaxis=dict(gridcolor="#1a1a1a", tickfont_size=9),
        )
        st.plotly_chart(fig_ports, use_container_width=True, config={"displayModeBar": False})

    # Multipliers
    m_l, m_r = st.columns(2)
    m_l.markdown(f'<div style="font-size:11px;color:#888;padding:8px">🛢 Oil multiplier <b style="color:#e8e8e8">{cost_impact["oil_multiplier"]}x</b> (baseline $90)</div>', unsafe_allow_html=True)
    m_r.markdown(f'<div style="font-size:11px;color:#888;padding:8px">⚠️ Event multiplier <b style="color:#e8e8e8">{cost_impact["event_risk_multiplier"]}x</b></div>', unsafe_allow_html=True)


# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="background:#0a0a0a;border-top:1px solid #1a1a1a;padding:8px 16px;
            display:flex;justify-content:space-between;margin-top:8px">
  <span style="font-size:9px;color:#444">TradeWatch v5.0 · Shipping Route Intelligence</span>
  <span style="font-size:9px;color:#444">ACLED · GDELT · NewsAPI · Guardian · FRED · OpenWeather</span>
  <span style="font-size:9px;color:#444">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</span>
</div>
""", unsafe_allow_html=True)

# ── Settings expander (bottom) ────────────────────────────────────────────────
with st.expander("⚙ Settings & Filters", expanded=False):
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.selectbox("Auto-refresh", [5,10,15,30], index=1,
                     format_func=lambda x: f"Every {x} min", key="refresh_interval")
        if st.button("Force Refresh"):
            st.cache_data.clear(); st.rerun()
    with s2:
        st.selectbox("Event Type", ["All Types"] + list(EVENT_TYPES.keys()), key="event_type")
    with s3:
        st.selectbox("Impact Level", ["All Levels","Critical","High","Medium","Low"], key="impact")
    with s4:
        st.text_input("Search", placeholder="location or keyword…", key="search")
        if st.button("Export CSV"):
            filtered_events = filter_events(events_df,
                                            st.session_state.get("event_type","All Types"),
                                            st.session_state.get("impact","All Levels"),
                                            st.session_state.get("search",""))
            st.download_button("⬇ Download",
                               data=filtered_events.to_csv(index=False),
                               file_name=f"events_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                               mime="text/csv")
