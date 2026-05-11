"""TradeWatch — Market & Costs"""

import streamlit as st
import pandas as pd
from analytics import RiskAnalytics
from components import filter_events
from dynamic_status import compute_shipping_status, compute_port_congestion
from data_loader import load_core_data
from api_integrations import APIClient
from ui_helpers import inject_css, render_header, render_nav, render_footer, SC, risk_col

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

# Fetch bunker data here so it is also available for the Bunker Prices section below
bunker_df = APIClient.get_bunker_prices()
sg_vlsfo = None
if len(bunker_df) > 0:
    _sg = bunker_df[(bunker_df["port"] == "Singapore") & (bunker_df["grade"] == "VLSFO")]
    if len(_sg) > 0:
        sg_vlsfo = _sg.iloc[0]

def _card(label, value, sym, change_text):
    if sym == "▲":
        bg, bdr, cc = "#1a3a1a", "#00cc44", "#00cc44"
    elif sym == "▼":
        bg, bdr, cc = "#3a1a1a", "#cc0000", "#cc0000"
    else:
        bg, bdr, cc = "#1a1a2e", "#333366", "#555577"
    return f"""
<div style="background:{bg};border:1px solid {bdr};border-radius:8px;padding:12px;
            text-align:center;min-height:110px;display:flex;flex-direction:column;
            justify-content:center;gap:4px">
  <div style="font-size:9px;color:#aaa;line-height:1.3">{label}</div>
  <div style="font-size:15px;font-weight:700;color:#e8e8e8;margin:4px 0">{value}</div>
  <div style="font-size:10px;color:{cc}">{sym} {change_text}</div>
</div>"""

cards_data = []

if oil_price:
    pct = (oil_price - 90) / 90 * 100
    sym = "▲" if pct >= 0 else "▼"
    cards_data.append(("🛢 WTI Crude", f"${oil_price:.2f}", sym, f"{abs(pct):.1f}%"))
else:
    cards_data.append(("🛢 WTI Crude", "N/A", "─", "—"))

if shipping_index:
    sym = "▲" if shipping_index > 150 else "▼" if shipping_index < 120 else "─"
    chg_label = "elevated" if shipping_index > 150 else "soft" if shipping_index < 120 else "neutral"
    cards_data.append(("⚓ IMF Freight Idx (monthly)", f"{shipping_index:,.1f}", sym, chg_label))
else:
    cards_data.append(("⚓ IMF Freight Idx (monthly)", "N/A", "─", "—"))

for ccy in ["EUR", "GBP", "JPY", "CNY"]:
    rate = exchange_rates.get(ccy) if exchange_rates else None
    cards_data.append((f"💱 USD/{ccy}", f"{rate:.4f}" if rate else "N/A", "", ""))

if sg_vlsfo is not None:
    chg = sg_vlsfo["change_usd"]
    sym = "▲" if chg >= 0 else "▼"
    cards_data.append(("⛽ Singapore VLSFO", f"${sg_vlsfo['price_usd_per_mt']:.0f}/MT", sym, f"${abs(chg):.0f}"))
else:
    cards_data.append(("⛽ Singapore VLSFO", "N/A", "─", "—"))

cols = st.columns(7)
for col, (label, value, sym, change_text) in zip(cols, cards_data):
    with col:
        st.markdown(_card(label, value, sym, change_text), unsafe_allow_html=True)


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
    for row_idx, (_, r) in enumerate(pivot.iterrows()):
        port = r["port"]
        row_bg = "#0d1117" if row_idx % 2 == 0 else "#111827"
        cells = ""
        for grade in ("VLSFO", "IFO380", "MGO"):
            price = r.get(grade)
            if pd.notna(price):
                chg_row = chg_pivot[chg_pivot["port"] == port]
                chg = chg_row[grade].iloc[0] if grade in chg_row.columns and len(chg_row) > 0 else 0
                col = "#22c55e" if chg > 0 else "#ef4444" if chg < 0 else "#666"
                sym = "▲" if chg > 0 else "▼" if chg < 0 else "─"
                cells += (
                    f'<td style="padding:6px 10px;font-weight:600">${price:.0f}'
                    f'<span style="color:{col} !important;font-size:9px;margin-left:6px">{sym}${abs(chg):.0f}</span>'
                    f'</td>'
                )
            else:
                cells += '<td style="padding:6px 10px;color:#444">—</td>'
        rows += f'<tr style="background:{row_bg}"><td style="padding:6px 10px;color:#cfe1ff">{port}</td>{cells}</tr>'
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
