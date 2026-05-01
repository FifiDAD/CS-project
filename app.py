"""TradeWatch — Shipping Route Intelligence · Overview"""

import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh

from analytics import RiskAnalytics
from maps import create_dashboard_map
from components import filter_events
from dynamic_status import compute_shipping_status, compute_port_congestion
from data_loader import load_core_data
from ui_helpers import (
    inject_css, render_header, render_nav, render_footer,
    SC, SBG, risk_col, IMPACT_COL, IMPACT_ICON,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TradeWatch",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

# ── Data loading ──────────────────────────────────────────────────────────────
with st.spinner(""):
    events_df, oil_price, shipping_index, exchange_rates = load_core_data()

events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()

with st.spinner(""):
    shipping_df  = compute_shipping_status(events_json)
    port_cong_df = compute_port_congestion(events_json)

analytics       = RiskAnalytics.get_summary_metrics(events_df, oil_price, shipping_index)
filtered_events = filter_events(events_df)

auto_interval = st.session_state.get("refresh_interval", 10)
count         = st_autorefresh(interval=auto_interval * 60 * 1000, limit=None, key="tw_refresh")

# ── Derived values ────────────────────────────────────────────────────────────
def _parse_delay_h(s):
    try:    return float(str(s).replace(" hours", "").replace("+", "").strip())
    except: return 0.0

if len(shipping_df) > 0:
    shipping_df["_delay_h"]   = shipping_df["Average Delay"].apply(_parse_delay_h)
    shipping_df["_composite"] = shipping_df["Risk Score"] / 100 + shipping_df["_delay_h"] / 48
    best_route   = shipping_df.loc[shipping_df["_composite"].idxmin(), "Route"]
    best_score   = int(shipping_df.loc[shipping_df["_composite"].idxmin(), "Risk Score"])
    worst_status = shipping_df.sort_values("Risk Score", ascending=False).iloc[0]["Status"]
else:
    best_route, best_score, worst_status = "N/A", 0, "Operational"

crit  = analytics.get("critical_events", 0)
high  = analytics.get("high_events", 0)
total = analytics.get("total_events", 0)

# ── Header + Nav ──────────────────────────────────────────────────────────────
render_header(crit, high, total, worst_status, count)
render_nav()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN LAYOUT — Globe (65%) │ Panels (35%)
# ══════════════════════════════════════════════════════════════════════════════
map_col, panels_col = st.columns([13, 9], gap="small")

# ─────────────────────────────────────────────────────────────────────────────
# LEFT — Globe
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
    globe_fig.update_layout(
        paper_bgcolor="#0a0a0a",
        margin=dict(l=0, r=0, t=0, b=0),
        height=560,
    )
    globe_fig.update_geos(bgcolor="#0a0a0a", landcolor="#0a2018", oceancolor="#020a08")
    st.plotly_chart(globe_fig, use_container_width=True,
                    config={"scrollZoom": True, "displayModeBar": False})

    # Recommended route bar
    if best_route != "N/A":
        rc = risk_col(best_score)
        st.markdown(f"""
<div style="background:rgba(34,197,94,0.05);border:1px solid rgba(34,197,94,0.2);
            border-left:3px solid #22c55e;border-radius:3px;padding:8px 12px;
            display:flex;justify-content:space-between;align-items:center">
  <span style="font-size:11px;color:#22c55e;font-weight:600">✓ RECOMMENDED ROUTE</span>
  <span style="font-size:13px;font-weight:700;color:#e8e8e8">{best_route}</span>
  <span style="font-size:11px;color:{rc}">Risk {best_score}/100</span>
  <span style="font-size:10px;color:#666">lowest risk + delay composite</span>
</div>""", unsafe_allow_html=True)

    # Chokepoints strip
    if len(shipping_df) > 0:
        st.markdown('<div class="tw-label" style="margin-top:10px">Chokepoints</div>',
                    unsafe_allow_html=True)
        strip_cols = st.columns(len(shipping_df))
        for col, (_, row) in zip(strip_cols, shipping_df.iterrows()):
            with col:
                sc      = SC.get(row["Status"], "#666")
                score   = int(row["Risk Score"])
                rc_fill = risk_col(score)
                name    = (row["Route"]
                           .replace("Canal", "C.").replace("Strait of", "Str.")
                           .replace("Strait", "Str.").replace("English Channel", "Eng.Ch."))
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
# RIGHT — Route Status + Live Events
# ─────────────────────────────────────────────────────────────────────────────
with panels_col:

    # ── Route Status ──────────────────────────────────────────────────────────
    if len(shipping_df) > 0:
        st.markdown(f"""
<div class="tw-panel">
  <div class="tw-panel-title">
    Route Status
    <span class="tw-panel-badge"
          style="background:rgba(59,130,246,0.12);color:#3b82f6;border:1px solid rgba(59,130,246,0.3)">
      {len(shipping_df)} routes
    </span>
  </div>""", unsafe_allow_html=True)

        route_rows_html = ""
        for _, row in shipping_df.sort_values("Risk Score", ascending=False).iterrows():
            sc     = SC.get(row["Status"], "#666")
            sbg    = SBG.get(row["Status"], "transparent")
            score  = int(row["Risk Score"])
            rc     = risk_col(score)
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
    <div style="font-size:9px;color:#666;margin-top:2px;text-align:right">
      {row['Cost Impact']} · {row['Average Delay']}
    </div>
  </div>
</div>"""

        st.markdown(route_rows_html + "</div>", unsafe_allow_html=True)

        sel_cols = st.columns(len(shipping_df))
        for col, (_, row) in zip(sel_cols, shipping_df.iterrows()):
            with col:
                if st.button("▸", key=f"sel_{row['Route']}", use_container_width=True,
                             help=f"Select {row['Route']}"):
                    st.session_state["selected_route"] = row["Route"]
                    st.rerun()

    # ── Live Events (top 5) ───────────────────────────────────────────────────
    events_html = f"""
<div class="tw-panel">
  <div class="tw-panel-title">
    Live Events
    <span class="tw-panel-badge"
          style="background:rgba(239,68,68,0.1);color:#ef4444;border:1px solid rgba(239,68,68,0.3)">
      {len(filtered_events)} active
    </span>
  </div>"""

    if not filtered_events.empty:
        recent = filtered_events.sort_values("date", ascending=False).head(5)
        for _, ev in recent.iterrows():
            ic  = IMPACT_COL.get(ev["impact"], "#666")
            ico = IMPACT_ICON.get(ev["impact"], "⚪")
            try:
                ts = pd.Timestamp(ev["date"]).strftime("%b %d %H:%M")
            except:
                ts = ""
            desc = str(ev.get("description", ""))[:60]
            events_html += f"""
<div class="tw-alert" style="border-left-color:{ic}">
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="color:{ic};font-size:9px;font-weight:700;text-transform:uppercase">
      {ico} {ev['impact']} · {ev['type']}
    </span>
    <span style="color:#555;font-size:9px">{ts}</span>
  </div>
  <div style="font-size:10px;color:#aaa">{ev['location']} — {desc}</div>
</div>"""
    else:
        events_html += '<div style="color:#555;font-size:11px;padding:8px">No active events</div>'

    events_html += "</div>"
    st.markdown(events_html, unsafe_allow_html=True)

    st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
    st.page_link("pages/2_Intel_Feed.py", label="View full Intel Feed →", icon="📡")

# ── Footer ────────────────────────────────────────────────────────────────────
render_footer()

# ── Settings (collapsed) ──────────────────────────────────────────────────────
from config import EVENT_TYPES
with st.expander("⚙ Settings & Filters", expanded=False):
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.selectbox("Auto-refresh", [5, 10, 15, 30], index=1,
                     format_func=lambda x: f"Every {x} min", key="refresh_interval")
        if st.button("Force Refresh"):
            st.cache_data.clear()
            st.rerun()
    with s2:
        st.selectbox("Event Type", ["All Types"] + list(EVENT_TYPES.keys()), key="event_type")
    with s3:
        st.selectbox("Impact Level", ["All Levels", "Critical", "High", "Medium", "Low"], key="impact")
    with s4:
        st.text_input("Search", placeholder="location or keyword…", key="search")
        if st.button("Export CSV"):
            fe = filter_events(events_df,
                               st.session_state.get("event_type", "All Types"),
                               st.session_state.get("impact", "All Levels"),
                               st.session_state.get("search", ""))
            st.download_button("⬇ Download",
                               data=fe.to_csv(index=False),
                               file_name=f"events_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv",
                               mime="text/csv")
