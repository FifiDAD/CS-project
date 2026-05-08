"""TradeWatch — Market & Costs"""

import streamlit as st
import pandas as pd
from analytics import RiskAnalytics
from components import filter_events
from dynamic_status import compute_shipping_status, compute_port_congestion
from data_loader import load_core_data
from api_integrations import APIClient
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
st.markdown('<div class="tw-label" style="margin-bottom:6px">Market Overview</div>', unsafe_allow_html=True)
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
        # IMF Global Freight Cost Index (TSIFRGHT, monthly, base=100). Typical
        # range ~110-160 in recent years; >150 = elevated, <120 = soft.
        trend_sym = "▲" if shipping_index > 150 else "▼" if shipping_index < 120 else "─"
        trend_col = "#ef4444" if shipping_index > 150 else "#22c55e" if shipping_index < 120 else "#666"
        market_html += f"""
<div class="tw-market-row">
  <span style="color:#aaa">⚓ IMF Freight Idx <span style="color:#666;font-size:9px">(monthly)</span></span>
  <span style="font-weight:600">{shipping_index:,.1f}
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

    # Real Singapore VLSFO from Ship & Bunker (live)
    bunker_df = APIClient.get_bunker_prices()
    sg_vlsfo = None
    if len(bunker_df) > 0:
        sg = bunker_df[(bunker_df["port"] == "Singapore") & (bunker_df["grade"] == "VLSFO")]
        if len(sg) > 0:
            sg_vlsfo = sg.iloc[0]
    if sg_vlsfo is not None:
        chg = sg_vlsfo["change_usd"]
        chg_col = "#22c55e" if chg < 0 else "#ef4444"
        chg_sym = "▲" if chg >= 0 else "▼"
        market_html += f"""
<div class="tw-market-row">
  <span style="color:#aaa">⛽ Singapore VLSFO</span>
  <span style="font-weight:600">${sg_vlsfo['price_usd_per_mt']:.0f}/MT
    <span style="color:{chg_col};font-size:9px;margin-left:6px">{chg_sym}${abs(chg):.0f}</span>
  </span>
</div>"""

    market_html += "</div>"
    st.markdown(market_html, unsafe_allow_html=True)

with top_right:
    # Port Congestion
    ports_html = '<div class="tw-panel"><div class="tw-panel-title">Port Congestion</div>'
    ports_html += '<div style="color:#666;font-size:10px;padding:0 8px 6px">Showing only ports with active congestion</div>'
    active_ports_df = port_cong_df[port_cong_df["Score"] > 0] if len(port_cong_df) > 0 else port_cong_df
    if len(active_ports_df) > 0:
        for _, p in active_ports_df.sort_values("Score", ascending=False).iterrows():
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
    elif len(port_cong_df) > 0:
        ports_html += '<div style="color:#555;font-size:11px;padding:8px">All ports operational — no congestion detected</div>'
    else:
        ports_html += '<div style="color:#555;font-size:11px;padding:8px">Loading port data…</div>'
    ports_html += "</div>"
    st.markdown(ports_html, unsafe_allow_html=True)

    if len(port_cong_df) > 0:
        with st.expander("View All Ports", expanded=False):
            full_ports_html = ""
            for _, p in port_cong_df.sort_values("Score", ascending=False).iterrows():
                cc    = CONG_COL.get(p["Congestion"], "#666")
                score = int(p["Score"])
                full_ports_html += f"""
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
            st.markdown(full_ports_html, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# BUNKER PRICES (live, from Ship & Bunker)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<hr style="margin:16px 0;border-color:#1e1e1e">', unsafe_allow_html=True)
st.markdown('<div class="tw-label" style="margin-bottom:6px">⛽ Bunker Prices <span style="font-weight:400;color:#444;font-size:9px">· live from shipandbunker.com · updated every 30 min</span></div>',
            unsafe_allow_html=True)
if len(bunker_df) > 0:
    pivot = bunker_df.pivot_table(
        index="port", columns="grade",
        values="price_usd_per_mt", aggfunc="first",
    ).reset_index()
    chg_pivot = bunker_df.pivot_table(
        index="port", columns="grade",
        values="change_usd", aggfunc="first",
    ).reset_index()

    rows = ""
    for _, r in pivot.iterrows():
        port = r["port"]
        cells = ""
        for grade in ("VLSFO", "IFO380", "MGO"):
            price = r.get(grade)
            if pd.notna(price):
                chg_row = chg_pivot[chg_pivot["port"] == port]
                chg = chg_row[grade].iloc[0] if grade in chg_row.columns and len(chg_row) > 0 else 0
                col = "#22c55e" if chg < 0 else "#ef4444" if chg > 0 else "#666"
                sym = "▲" if chg > 0 else "▼" if chg < 0 else "─"
                cells += (
                    f'<td style="padding:6px 10px;font-weight:600">${price:.0f}'
                    f'<span style="color:{col};font-size:9px;margin-left:6px">{sym}${abs(chg):.0f}</span>'
                    f'</td>'
                )
            else:
                cells += '<td style="padding:6px 10px;color:#444">—</td>'
        rows += f'<tr><td style="padding:6px 10px;color:#cfe1ff">{port}</td>{cells}</tr>'
    st.markdown(f"""
<table class="tw-table" style="font-size:11px">
<thead><tr><th>Port</th><th>VLSFO</th><th>IFO380</th><th>MGO</th></tr></thead>
<tbody>{rows}</tbody>
</table>""", unsafe_allow_html=True)
else:
    st.markdown('<div style="color:#555;font-size:11px;padding:8px">Loading bunker prices…</div>',
                unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# FINANCIAL IMPACT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<hr style="margin:16px 0;border-color:#1e1e1e">', unsafe_allow_html=True)
st.markdown('<div class="tw-label" style="margin-bottom:6px">Financial Impact Fleet</div>', unsafe_allow_html=True)

cost_impact = RiskAnalytics.calculate_cost_impact(filtered_events, oil_price, {})

oil_mult   = cost_impact["oil_multiplier"]
ev_mult    = cost_impact["event_risk_multiplier"]
oil_vs_base = (oil_mult - 1) * 100
oil_col    = "#22c55e" if oil_vs_base < 0 else "#ef4444"
oil_sym    = "▼" if oil_vs_base < 0 else "▲"
ev_col     = "#22c55e" if ev_mult <= 1.0 else "#f97316" if ev_mult < 1.3 else "#ef4444"

st.markdown(
    f'<div style="display:flex;gap:12px;margin-bottom:12px">'
    f'<div class="tw-panel" style="flex:1;padding:10px 14px">'
    f'<div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px">Daily Cost Impact</div>'
    f'<div style="font-size:22px;font-weight:700;color:#e8e8e8">${cost_impact["daily_cost_increase_usd"]:,.0f}</div>'
    f'<div style="font-size:9px;color:#555;margin-top:2px">reference fleet estimate</div>'
    f'</div>'
    f'<div class="tw-panel" style="flex:1;padding:10px 14px">'
    f'<div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px">Monthly Projection</div>'
    f'<div style="font-size:22px;font-weight:700;color:#e8e8e8">${cost_impact["monthly_cost_increase_usd"]:,.0f}</div>'
    f'<div style="font-size:9px;color:#555;margin-top:2px">~{cost_impact["affected_vessels"]} vessels/day</div>'
    f'</div>'
    f'<div class="tw-panel" style="flex:1;padding:10px 14px">'
    f'<div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:6px">Active multipliers</div>'
    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'
    f'<span style="font-size:10px;color:#888">🛢 Oil (vs $90/bbl)</span>'
    f'<span style="font-size:11px;font-weight:700;color:{oil_col}">{oil_sym}{abs(oil_vs_base):.1f}%&nbsp;<span style="color:#555;font-size:9px">{oil_mult}x</span></span>'
    f'</div>'
    f'<div style="font-size:9px;color:#444;margin-bottom:8px">WTI at ${oil_price:.0f}/bbl — fleet fuel cost scales proportionally to oil price vs the $90 baseline.</div>'
    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'
    f'<span style="font-size:10px;color:#888">⚠️ Event risk</span>'
    f'<span style="font-size:11px;font-weight:700;color:{ev_col}">{ev_mult}x</span>'
    f'</div>'
    f'<div style="font-size:9px;color:#444">Based on active critical/high events on monitored routes.</div>'
    f'</div>'
    f'</div>',
    unsafe_allow_html=True,
)

st.markdown('<hr style="margin:16px 0;border-color:#1e1e1e">', unsafe_allow_html=True)
st.markdown('<div class="tw-label" style="margin-bottom:6px">Chokepoint — Delays & Costs</div>',
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


render_footer()
