# =============================================================================
# 3_Market_Costs.py — THE "MARKET & COSTS" PAGE (the money page)
# =============================================================================
# This is the page that answers the question "how much does today's
# situation actually COST a shipping company?". It shows:
#
#   1. A row of 7 "market overview" cards: WTI crude oil price, the IMF
#      freight index, 4 currency pairs (EUR/GBP/JPY/CNY vs USD), and the
#      Singapore VLSFO marine fuel price. Each card shows green/red arrows
#      based on whether the number is up or down vs a baseline.
#
#   2. A live bunker (marine fuel) price table — we scrape this from the
#      public Ship & Bunker website (see api_integrations.APIClient.
#      get_bunker_prices). It updates roughly every 30 minutes.
#
#   3. A "Financial Impact Fleet" panel that estimates the daily and
#      monthly extra cost a typical fleet is paying RIGHT NOW because of
#      higher oil prices and active events. The maths is in
#      analytics.RiskAnalytics.calculate_cost_impact().
#
#   4. A delays-and-costs table grouped by chokepoint (Suez, Hormuz, …)
#      sorted with the most expensive/risky one at the top.
#
# Where the data comes from:
#   - WTI oil & freight index : FRED API (St. Louis Fed, free)
#   - Exchange rates          : ExchangeRate-API (free, no key)
#   - Bunker prices           : Ship & Bunker website (live scrape)
#   - Event-driven multipliers: our own analytics on the events data
# =============================================================================

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
# Load the shared core dataset: geopolitical events, live WTI oil price, the IMF
# freight shipping index, and USD exchange rates. Results are cached for 15–30
# minutes so repeated page visits don't trigger redundant API calls.
with st.spinner(""):
    events_df, oil_price, shipping_index, exchange_rates = load_core_data()

# Convert the events DataFrame to a JSON string before passing to dynamic status
# functions. Streamlit's cache cannot hash DataFrames directly, so these functions
# accept a JSON string as the cache key instead.
events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()

with st.spinner(""):
    # Compute live risk scores for each shipping chokepoint and each major port,
    # combining GDELT news volume, geocoded events, and live weather alerts.
    shipping_df  = compute_shipping_status(events_json)
    port_cong_df = compute_port_congestion(events_json)

# Aggregate KPI counts (critical / high / total events) used in the page header.
analytics       = RiskAnalytics.get_summary_metrics(events_df, oil_price, shipping_index)
# Apply any active sidebar filters so cost calculations reflect the filtered view.
filtered_events = filter_events(events_df)

# Derive the single worst route status to display in the header alert banner.
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
# Extract the Singapore VLSFO row specifically for use in the 7th market card.
# Singapore is the world's largest bunkering hub, making it the most representative
# single price point for benchmarking fleet fuel costs.
sg_vlsfo = None
if len(bunker_df) > 0:
    _sg = bunker_df[(bunker_df["port"] == "Singapore") & (bunker_df["grade"] == "VLSFO")]
    if len(_sg) > 0:
        sg_vlsfo = _sg.iloc[0]

# Generates a single colored metric card as an HTML string. The card's background
# and border shift green for upward moves (▲), red for downward (▼), and neutral
# dark-blue when no directional signal applies (e.g. FX rates).
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

# Build the list of (label, value, direction_symbol, change_text) tuples that
# will be rendered as 7 equal-width market overview cards.
cards_data = []

# WTI Crude: percentage deviation from the $90/bbl fleet cost baseline used
# throughout the financial impact calculations on this page.
if oil_price:
    pct = (oil_price - 90) / 90 * 100
    sym = "▲" if pct >= 0 else "▼"
    cards_data.append(("🛢 WTI Crude", f"${oil_price:.2f}", sym, f"{abs(pct):.1f}%"))
else:
    cards_data.append(("🛢 WTI Crude", "N/A", "─", "—"))

# IMF Freight Index: thresholds at 150 (elevated) and 120 (soft) reflect the
# historical band used by the analytics module to flag supply-chain pressure.
if shipping_index:
    sym = "▲" if shipping_index > 150 else "▼" if shipping_index < 120 else "─"
    chg_label = "elevated" if shipping_index > 150 else "soft" if shipping_index < 120 else "neutral"
    cards_data.append(("⚓ IMF Freight Idx (monthly)", f"{shipping_index:,.1f}", sym, chg_label))
else:
    cards_data.append(("⚓ IMF Freight Idx (monthly)", "N/A", "─", "—"))

# Four major currency pairs vs USD. Shown without a directional symbol because
# FX moves are not inherently positive or negative for a global shipping operator.
for ccy in ["EUR", "GBP", "JPY", "CNY"]:
    rate = exchange_rates.get(ccy) if exchange_rates else None
    cards_data.append((f"💱 USD/{ccy}", f"{rate:.4f}" if rate else "N/A", "", ""))

# Singapore VLSFO as the 7th card — the reference marine fuel price for the
# IMO 2020-compliant Very Low Sulphur Fuel Oil grade most vessels now burn.
if sg_vlsfo is not None:
    chg = sg_vlsfo["change_usd"]
    sym = "▲" if chg >= 0 else "▼"
    cards_data.append(("⛽ Singapore VLSFO", f"${sg_vlsfo['price_usd_per_mt']:.0f}/MT", sym, f"${abs(chg):.0f}"))
else:
    cards_data.append(("⛽ Singapore VLSFO", "N/A", "─", "—"))

# Render all 7 cards in equal-width columns. zip() stops at the shorter iterable,
# so adding or removing a card from cards_data automatically adjusts the layout.
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
    # Reshape the flat bunker DataFrame into a port × grade price table so each
    # row represents one port and each column a fuel grade (VLSFO, IFO380, MGO).
    pivot = bunker_df.pivot_table(
        index="port", columns="grade",
        values="price_usd_per_mt", aggfunc="first",
    ).reset_index()
    # Separate pivot for day-on-day price changes, looked up per cell when
    # building the ▲/▼ indicators inside the table.
    chg_pivot = bunker_df.pivot_table(
        index="port", columns="grade",
        values="change_usd", aggfunc="first",
    ).reset_index()

    rows = ""
    for row_idx, (_, r) in enumerate(pivot.iterrows()):
        port = r["port"]
        # Alternate row background colours to improve readability in long tables.
        row_bg = "#0d1117" if row_idx % 2 == 0 else "#111827"
        cells = ""
        for grade in ("VLSFO", "IFO380", "MGO"):
            price = r.get(grade)
            if pd.notna(price):
                # Look up the change value for this specific port + grade combination.
                chg_row = chg_pivot[chg_pivot["port"] == port]
                chg = chg_row[grade].iloc[0] if grade in chg_row.columns and len(chg_row) > 0 else 0
                # Green for price rises, red for drops. !important is required because
                # ui_helpers.py applies a global "color: var(--text) !important" rule
                # to all <span> elements, which would otherwise override inline colours.
                col = "#22c55e" if chg > 0 else "#ef4444" if chg < 0 else "#666"
                sym = "▲" if chg > 0 else "▼" if chg < 0 else "─"
                cells += (
                    f'<td style="padding:6px 10px;font-weight:600">${price:.0f}'
                    f'<span style="color:{col} !important;font-size:9px;margin-left:6px">{sym}${abs(chg):.0f}</span>'
                    f'</td>'
                )
            else:
                # Some ports don't quote every grade — show a dash rather than a zero.
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

# Calculate how much the current oil price and active geopolitical events are
# adding to daily fleet operating costs relative to a baseline scenario.
# The empty dict means no per-vessel overrides — fleet-wide defaults are used.
cost_impact = RiskAnalytics.calculate_cost_impact(filtered_events, oil_price, {})

oil_mult   = cost_impact["oil_multiplier"]
ev_mult    = cost_impact["event_risk_multiplier"]
# Express the oil multiplier as a percentage above or below the $90/bbl baseline.
oil_vs_base = (oil_mult - 1) * 100
# Green when oil is below the baseline (lower fuel costs), red when above.
oil_col    = "#22c55e" if oil_vs_base < 0 else "#ef4444"
oil_sym    = "▼" if oil_vs_base < 0 else "▲"
# Event risk colour: green = no added risk, orange = moderate uplift, red = high.
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
# Table of every monitored chokepoint sorted highest-risk first, showing each
# route's operational status, estimated average delay, cost premium, and the
# number of nearby geopolitical events driving the score. SC maps status strings
# to their colour codes; risk_col maps a 0–100 numeric score to a traffic-light
# colour for quick visual scanning.
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
