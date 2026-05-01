"""TradeWatch — Market & Costs"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from analytics import RiskAnalytics
from components import filter_events
from dynamic_status import compute_shipping_status, compute_port_congestion
from data_loader import load_core_data
from ui_helpers import inject_css, render_header, render_nav, render_footer, SC, risk_col, CONG_COL

st.set_page_config(
    page_title="TradeWatch — Market & Costs",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

# ── Data ──────────────────────────────────────────────────────────────────────
with st.spinner(""):
    events_df, oil_price, shipping_index, exchange_rates = load_core_data()

events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()

with st.spinner(""):
    shipping_df  = compute_shipping_status(events_json)
    port_cong_df = compute_port_congestion(events_json)

analytics       = RiskAnalytics.get_summary_metrics(events_df, oil_price, shipping_index)
filtered_events = filter_events(events_df)

if len(shipping_df) > 0:
    worst_status = shipping_df.sort_values("Risk Score", ascending=False).iloc[0]["Status"]
else:
    worst_status = "Operational"

crit  = analytics.get("critical_events", 0)
high  = analytics.get("high_events", 0)
total = analytics.get("total_events", 0)

# ── Header + Nav ──────────────────────────────────────────────────────────────
render_header(crit, high, total, worst_status, 0)
render_nav()

# ══════════════════════════════════════════════════════════════════════════════
# MARKET PULSE + PORT CONGESTION
# ══════════════════════════════════════════════════════════════════════════════
top_left, top_right = st.columns([1, 1], gap="large")

with top_left:
    # Market Pulse
    market_html = '<div class="tw-panel"><div class="tw-panel-title">Market Pulse</div>'
    if oil_price:
        pct       = (oil_price - 90) / 90 * 100
        delta_col = "#22c55e" if pct < 0 else "#ef4444"
        delta_sym = "▲" if pct >= 0 else "▼"
        market_html += f"""
<div class="tw-market-row">
  <span style="color:#aaa">🛢 WTI Crude</span>
  <span style="font-weight:600">${oil_price:.2f}
    <span style="color:{delta_col};font-size:9px;margin-left:6px">{delta_sym}{abs(pct):.1f}%</span>
  </span>
</div>"""

    if shipping_index:
        trend_sym = "▲" if shipping_index > 3500 else "▼" if shipping_index < 2500 else "─"
        trend_col = "#ef4444" if shipping_index > 3500 else "#22c55e" if shipping_index < 2500 else "#666"
        market_html += f"""
<div class="tw-market-row">
  <span style="color:#aaa">⚓ Freight Idx</span>
  <span style="font-weight:600">{shipping_index:,.0f}
    <span style="color:{trend_col};font-size:9px;margin-left:6px">{trend_sym}</span>
  </span>
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

with top_right:
    # Port Congestion
    ports_html = '<div class="tw-panel"><div class="tw-panel-title">Port Congestion</div>'
    if len(port_cong_df) > 0:
        for _, p in port_cong_df.sort_values("Score", ascending=False).iterrows():
            cc    = CONG_COL.get(p["Congestion"], "#666")
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
  <span class="tw-badge" style="background:{cc}18;color:{cc};border:1px solid {cc}33">
    {p['Congestion']}
  </span>
  <span style="font-size:9px;color:#555;margin-left:8px;min-width:20px">{score}</span>
</div>"""
    else:
        ports_html += '<div style="color:#555;font-size:11px;padding:8px">Loading port data…</div>'
    ports_html += "</div>"
    st.markdown(ports_html, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# FINANCIAL IMPACT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<hr style="margin:16px 0">', unsafe_allow_html=True)

cost_impact = RiskAnalytics.calculate_cost_impact(filtered_events, oil_price, {})
mc1, mc2, mc3 = st.columns(3)
mc1.metric("Daily Cost Impact",  f"${cost_impact['daily_cost_increase_usd']:,.0f}")
mc2.metric("Monthly Projection", f"${cost_impact['monthly_cost_increase_usd']:,.0f}")
mc3.metric("Reference Fleet",    f"~{cost_impact['affected_vessels']} vessels/day")

st.markdown('<div class="tw-label" style="margin-top:14px">Cost Impact Over Time</div>',
            unsafe_allow_html=True)
cost_data = pd.DataFrame({
    "Period": ["Daily", "Weekly", "Monthly"],
    "USD":    [cost_impact["daily_cost_increase_usd"],
               cost_impact["weekly_cost_increase_usd"],
               cost_impact["monthly_cost_increase_usd"]],
})
fig_cost = go.Figure(go.Bar(
    x=cost_data["Period"], y=cost_data["USD"],
    marker_color=["#3b82f6", "#f97316", "#ef4444"],
    text=[f"${v:,.0f}" for v in cost_data["USD"]],
    textposition="outside",
    textfont=dict(color="#666", size=9),
))
fig_cost.update_layout(
    paper_bgcolor="#0a0a0a", plot_bgcolor="#111", font_color="#666", height=200,
    margin=dict(t=20, b=0, l=0, r=0), showlegend=False,
    xaxis=dict(tickfont_size=10, tickcolor="#444", linecolor="#2a2a2a"),
    yaxis=dict(gridcolor="#1a1a1a", tickfont_size=9, showticklabels=False),
)
st.plotly_chart(fig_cost, use_container_width=True, config={"displayModeBar": False})

st.markdown('<div class="tw-label" style="margin-top:14px">Chokepoint Delay & Cost Table</div>',
            unsafe_allow_html=True)
if len(shipping_df) > 0:
    rows = ""
    for _, row in shipping_df.sort_values("Risk Score", ascending=False).iterrows():
        sc_  = SC.get(row["Status"], "#666")
        rs   = int(row["Risk Score"])
        rc_  = risk_col(rs)
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

st.markdown('<div class="tw-label" style="margin-top:16px">Port Congestion Detail</div>',
            unsafe_allow_html=True)
if len(port_cong_df) > 0:
    fig_ports = px.bar(
        port_cong_df.sort_values("Score", ascending=False),
        x="Port", y="Score", color="Congestion",
        color_discrete_map={"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"},
    )
    fig_ports.update_layout(
        paper_bgcolor="#0a0a0a", plot_bgcolor="#111", font_color="#666", height=220,
        margin=dict(t=4, b=0, l=0, r=0),
        legend=dict(bgcolor="rgba(0,0,0,0.5)", font_color="#888", font_size=9,
                    bordercolor="#2a2a2a", borderwidth=1),
        xaxis=dict(tickangle=-30, tickfont_size=9, tickcolor="#444", linecolor="#2a2a2a"),
        yaxis=dict(gridcolor="#1a1a1a", tickfont_size=9),
    )
    st.plotly_chart(fig_ports, use_container_width=True, config={"displayModeBar": False})

m_l, m_r = st.columns(2)
m_l.markdown(
    f'<div style="font-size:11px;color:#888;padding:8px">🛢 Oil multiplier '
    f'<b style="color:#e8e8e8">{cost_impact["oil_multiplier"]}x</b> (baseline $90)</div>',
    unsafe_allow_html=True,
)
m_r.markdown(
    f'<div style="font-size:11px;color:#888;padding:8px">⚠️ Event multiplier '
    f'<b style="color:#e8e8e8">{cost_impact["event_risk_multiplier"]}x</b></div>',
    unsafe_allow_html=True,
)

render_footer()
