"""TradeWatch — Route Planner"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from config import EVENT_TYPES
from analytics import RiskAnalytics
from components import filter_events, render_comparison_table
from dynamic_status import compute_shipping_status, compute_risk_summary, compute_port_congestion
from data_loader import load_core_data
from ui_helpers import inject_css, render_header, render_nav, render_footer, SC, risk_col

st.set_page_config(
    page_title="TradeWatch — Route Planner",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

# ── Data ──────────────────────────────────────────────────────────────────────
with st.spinner(""):
    # Load shared events and market data used by the planner.
    events_df, oil_price, shipping_index, exchange_rates = load_core_data()

events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()

with st.spinner(""):
    # Compute route risk, regional risk, and port congestion tables.
    shipping_df  = compute_shipping_status(events_json)
    risk_df      = compute_risk_summary(events_json)
    port_cong_df = compute_port_congestion(events_json)

analytics       = RiskAnalytics.get_summary_metrics(events_df, oil_price, shipping_index)
filtered_events = filter_events(events_df)

def _parse_delay_h(s):
    # Turn display text like "6 hours" into a number for scoring.
    try:    return float(str(s).replace(" hours", "").replace("+", "").strip())
    except: return 0.0

if len(shipping_df) > 0:
    shipping_df["_delay_h"]   = shipping_df["Average Delay"].apply(_parse_delay_h)
    shipping_df["_composite"] = shipping_df["Risk Score"] / 100 + shipping_df["_delay_h"] / 48
    best_route   = shipping_df.loc[shipping_df["_composite"].idxmin(), "Route"]
    worst_status = shipping_df.sort_values("Risk Score", ascending=False).iloc[0]["Status"]
else:
    best_route, worst_status = "N/A", "Operational"

crit  = analytics.get("critical_events", 0)
high  = analytics.get("high_events", 0)
total = analytics.get("total_events", 0)

# ── Header + Nav ──────────────────────────────────────────────────────────────
render_header(crit, high, total, worst_status, 0)
render_nav()

# ══════════════════════════════════════════════════════════════════════════════
# ROUTE PLANNER
# ══════════════════════════════════════════════════════════════════════════════
planner_left, planner_right = st.columns([3, 1], gap="large")

with planner_left:
    route_names = shipping_df["Route"].tolist() if len(shipping_df) > 0 else []

    sc_col1, sc_col2 = st.columns([3, 1])
    with sc_col1:
        # Let users test how the planner reacts if one route fails.
        scenario_route = st.selectbox(
            "SIMULATE ROUTE FAILURE →",
            ["None (live data)"] + route_names,
            key="scenario_route",
        )
    with sc_col2:
        st.selectbox("TYPE", ["All Types"] + list(EVENT_TYPES.keys()), key="event_type_tab")

    scenario_overrides = {}
    if scenario_route != "None (live data)":
        # Force the selected route into a critical scenario for comparison.
        scenario_overrides[scenario_route] = "Critical - Avoid"
        st.markdown(f"""
<div style="background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.2);
            border-left:3px solid #ef4444;border-radius:3px;padding:6px 10px;margin-bottom:8px;
            font-size:11px;color:#ef4444">
  ⚠ SCENARIO ACTIVE — {scenario_route} overridden to CRITICAL · AVOID
</div>""", unsafe_allow_html=True)

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

    st.markdown('<div class="tw-label" style="margin-top:16px">Regional Risk Summary</div>',
                unsafe_allow_html=True)
    if len(risk_df) > 0:
        rows = ""
        for _, row in risk_df.iterrows():
            rc_ = {"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"}.get(row["Risk Level"], "#666")
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

    st.markdown('<div class="tw-label" style="margin-top:16px">Event Activity — Last 30 Days</div>',
                unsafe_allow_html=True)
    if len(filtered_events) > 0:
        # Count events by day for the activity timeline.
        daily = (pd.DataFrame({"date": filtered_events["date"].dt.date, "n": 1})
                 .groupby("date").sum().reset_index())
        fig_tl = go.Figure()
        fig_tl.add_trace(go.Scatter(
            x=daily["date"], y=daily["n"],
            fill="tozeroy", fillcolor="rgba(239,68,68,0.08)",
            mode="lines", line=dict(color="#ef4444", width=1.5), name="Events",
        ))
        fig_tl.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#111111", font_color="#666", height=160,
            margin=dict(t=4, b=0, l=0, r=0),
            xaxis=dict(showgrid=False, tickfont_size=9, tickcolor="#444", ticklen=3, linecolor="#2a2a2a"),
            yaxis=dict(showgrid=True, gridcolor="#1a1a1a", tickfont_size=9, tickcolor="#444", ticklen=3),
            hovermode="x unified", showlegend=False,
        )
        st.plotly_chart(fig_tl, use_container_width=True, config={"displayModeBar": False})

with planner_right:
    # The Voyage Cost Estimator that used to live here is now superseded by
    # MariNav Router (full weather routing + vessel physics + Monte Carlo +
    # CO₂ + bunker arbitrage). This page focuses on chokepoint comparison —
    # link out for actual voyage planning.
    st.markdown("""
<div style="background:rgba(59,130,246,0.06);border:1px solid rgba(59,130,246,0.25);
            border-left:3px solid #3b82f6;border-radius:4px;padding:14px;margin-top:6px">
  <div style="font-size:11px;font-weight:700;color:#3b82f6;text-transform:uppercase;
              letter-spacing:0.5px;margin-bottom:8px">🧭 Plan a Voyage</div>
  <div style="font-size:12px;color:#cfe1ff;line-height:1.5;margin-bottom:10px">
    For weather-routed origin → destination optimization with vessel physics,
    Monte Carlo P10/P50/P90 fuel & ETA, CO₂ emissions, speed-vs-cost curves
    and bunker arbitrage, open the dedicated router page.
  </div>
  <a href="/MariNav_Router" target="_self"
     style="display:inline-block;background:#3b82f6;color:#fff;padding:6px 14px;
            border-radius:3px;font-size:11px;font-weight:700;text-decoration:none">
    Open MariNav Router →
  </a>
</div>
""", unsafe_allow_html=True)

render_footer()
