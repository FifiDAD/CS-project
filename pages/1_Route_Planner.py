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
    events_df, oil_price, shipping_index, exchange_rates = load_core_data()

events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()

with st.spinner(""):
    shipping_df  = compute_shipping_status(events_json)
    risk_df      = compute_risk_summary(events_json)
    port_cong_df = compute_port_congestion(events_json)

analytics       = RiskAnalytics.get_summary_metrics(events_df, oil_price, shipping_index)
filtered_events = filter_events(events_df)

def _parse_delay_h(s):
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
planner_left, planner_right = st.columns([3, 2], gap="large")

with planner_left:
    route_names = shipping_df["Route"].tolist() if len(shipping_df) > 0 else []

    sc_col1, sc_col2 = st.columns([3, 1])
    with sc_col1:
        scenario_route = st.selectbox(
            "SIMULATE ROUTE FAILURE →",
            ["None (live data)"] + route_names,
            key="scenario_route",
        )
    with sc_col2:
        st.selectbox("TYPE", ["All Types"] + list(EVENT_TYPES.keys()), key="event_type_tab")

    scenario_overrides = {}
    if scenario_route != "None (live data)":
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
    wti    = oil_price if oil_price else 78.45
    bunker = wti * 6.35

    st.markdown('<div class="tw-label">Voyage Cost Estimator</div>', unsafe_allow_html=True)
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
    cons  = st.number_input("Fuel Consumption (t/day)", 1.0, 500.0,
                             float(preset_cons.get(vessel_preset, 50)), 1.0, key="cons")
    vdays = st.number_input("Voyage Duration (days)", 1, 120, 14, 1, key="vdays")

    r_opts  = ["No specific route"] + route_names
    def_idx = 0
    sel     = st.session_state.get("selected_route")
    if sel and sel in r_opts:
        def_idx = r_opts.index(sel)
    sel_route = st.selectbox("Shipping Route", r_opts, index=def_idx, key="calc_route")

    spd_red   = st.slider("Speed Reduction (%)", 0, 30, 0, 5, key="spd_red")
    cargo_val = st.number_input("Cargo Value USD", 0, 500_000_000, 0, 100_000,
                                format="%d", key="cargo_val")

    surcharge = 0.0
    route_lbl = "N/A"
    if sel_route != "No specific route" and len(shipping_df) > 0:
        rr = shipping_df[shipping_df["Route"] == sel_route]
        if len(rr) > 0:
            route_lbl = rr.iloc[0]["Status"]
            try:    surcharge = float(rr.iloc[0]["Cost Impact"].replace("%", "").replace("+", "")) / 100
            except: surcharge = int(rr.iloc[0]["Risk Score"]) / 400

    eff_days   = vdays * (1 + spd_red / 100)
    fuel_tons  = cons * eff_days
    base_cost  = fuel_tons * bunker
    risk_cost  = base_cost * surcharge
    total_cost = base_cost + risk_cost
    insurance  = 0.0
    if cargo_val > 0:
        pct       = 0.003 if surcharge > 0.15 else 0.0015 if surcharge > 0.05 else 0.001
        insurance = cargo_val * pct

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

    bd = {"Base Fuel": base_cost}
    if risk_cost > 0: bd["Risk Surcharge"] = risk_cost
    if insurance  > 0: bd["Insurance"]     = insurance

    fig_br = go.Figure(go.Bar(
        x=list(bd.keys()), y=list(bd.values()),
        marker_color=["#3b82f6", "#f97316", "#eab308"][:len(bd)],
        text=[f"${v:,.0f}" for v in bd.values()],
        textposition="outside",
        textfont=dict(color="#666", size=9),
    ))
    fig_br.update_layout(
        paper_bgcolor="#0a0a0a", plot_bgcolor="#111111", font_color="#666", height=160,
        margin=dict(t=20, b=0, l=0, r=0), showlegend=False,
        xaxis=dict(tickfont_size=9, tickcolor="#444", linecolor="#2a2a2a"),
        yaxis=dict(showgrid=True, gridcolor="#1a1a1a", tickfont_size=9, showticklabels=False),
    )
    st.plotly_chart(fig_br, use_container_width=True, config={"displayModeBar": False})

render_footer()
