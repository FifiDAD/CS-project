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
    from api_integrations import APIClient
    from vessels import VESSELS
    from canal_tolls import estimate_toll_usd, can_transit

    # Live VLSFO at chosen bunkering port (default Singapore)
    bunker_df = APIClient.get_bunker_prices()

    st.markdown('<div class="tw-label">Voyage Cost Estimator</div>', unsafe_allow_html=True)

    # Vessel class + bunkering port selectors
    vc1, vc2 = st.columns(2)
    with vc1:
        vessel_class = st.selectbox("Vessel Class", list(VESSELS.keys()),
                                    index=0, key="vessel_class")
    bunker_ports = sorted(bunker_df["port"].unique()) if len(bunker_df) > 0 else ["Singapore"]
    with vc2:
        bunker_port = st.selectbox("Bunker port",
                                   bunker_ports,
                                   index=bunker_ports.index("Singapore") if "Singapore" in bunker_ports else 0,
                                   key="bunker_port")

    vessel = VESSELS[vessel_class]
    grade = vessel.fuel_grade
    bunker_price = None
    if len(bunker_df) > 0:
        match = bunker_df[(bunker_df["port"] == bunker_port) & (bunker_df["grade"] == grade)]
        if len(match) > 0:
            bunker_price = float(match.iloc[0]["price_usd_per_mt"])
    if bunker_price is None:
        bunker_price = 600  # only used if Ship & Bunker scrape failed

    # Service speed (knots) — drives cubic fuel curve
    speed_kn = st.slider("Service speed (kn)",
                         min_value=8.0, max_value=22.0,
                         value=float(vessel.design_speed_kn), step=0.5, key="speed_kn")
    cons = vessel.fuel_tpd(speed_kn)

    st.markdown(f"""
<div style="background:var(--surface);border:1px solid var(--border);border-radius:3px;
            padding:8px 10px;margin-bottom:10px;font-size:11px;color:#aaa">
  {vessel.name} · {grade} <b style="color:#e8e8e8">${bunker_price:.0f}/MT</b> @ {bunker_port}
  · burn <b style="color:#e8e8e8">{cons:.1f} t/day</b> @ {speed_kn:.1f} kn
</div>""", unsafe_allow_html=True)

    vdays = st.number_input("Voyage Duration (days)", 1, 120, 14, 1, key="vdays")

    r_opts  = ["No specific route"] + route_names
    def_idx = 0
    sel     = st.session_state.get("selected_route")
    if sel and sel in r_opts:
        def_idx = r_opts.index(sel)
    sel_route = st.selectbox("Shipping Route", r_opts, index=def_idx, key="calc_route")

    spd_red   = st.slider("Speed Reduction (%) — slow steaming", 0, 30, 0, 5, key="spd_red")
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

    # Slow steaming reduces speed → cubic fuel curve, big savings
    eff_speed = speed_kn * (1 - spd_red / 100)
    eff_cons = vessel.fuel_tpd(eff_speed)
    eff_days   = vdays * (1 + spd_red / 100)
    fuel_tons  = eff_cons * eff_days
    base_cost  = fuel_tons * bunker_price
    risk_cost  = base_cost * surcharge

    # Canal toll if the chosen route uses Suez or Panama
    toll_cost = 0
    toll_label = ""
    canal_key = None
    if "Suez" in sel_route:
        canal_key = "suez"
    elif "Panama" in sel_route:
        canal_key = "panama"
    if canal_key:
        toll = estimate_toll_usd(canal_key, vessel_class)
        if toll is None:
            toll_label = f"⚠ {vessel_class} cannot transit {canal_key.title()} canal"
        else:
            toll_cost = toll
            toll_label = f"{canal_key.title()} canal toll: ${toll:,.0f}"

    total_cost = base_cost + risk_cost + toll_cost
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
    {f"<br>{toll_label}" if toll_label else ""}
  </div>
</div>""", unsafe_allow_html=True)

    bd = {"Base Fuel": base_cost}
    if risk_cost > 0: bd["Risk Surcharge"] = risk_cost
    if toll_cost > 0: bd["Canal Toll"]     = toll_cost
    if insurance  > 0: bd["Insurance"]     = insurance

    fig_br = go.Figure(go.Bar(
        x=list(bd.keys()), y=list(bd.values()),
        marker_color=["#3b82f6", "#f97316", "#9b59b6", "#eab308"][:len(bd)],
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
