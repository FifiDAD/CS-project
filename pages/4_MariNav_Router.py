"""
TradeWatch — MariNav Route Calculator

Route optimizer powered by the methodology from:
  MariNav — https://github.com/Vaishnav2804/MariNav
  by Vaishnav2804 and contributors

This page builds a risk-weighted maritime routing graph (H3 + NetworkX,
as in MariNav) and finds the optimal path between any two major ports,
penalizing routes that pass through chokepoints currently flagged as
high-risk by TradeWatch's live data feeds.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from dynamic_status import compute_shipping_status
from data_loader import load_core_data
from ui_helpers import inject_css, render_header, render_nav, render_footer, SC, risk_col
from analytics import RiskAnalytics
from components import filter_events
from marinav_router import (
    build_shipping_graph,
    find_optimal_route,
    PORTS,
    CHOKEPOINT_ROUTES,
    H3_AVAILABLE,
)
from config import MAJOR_SHIPPING_ROUTES

st.set_page_config(
    page_title="TradeWatch — MariNav Router",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

if not H3_AVAILABLE:
    st.error("h3 library not installed. Run: pip install h3")
    st.stop()

# ── Data ──────────────────────────────────────────────────────────────────────
with st.spinner(""):
    events_df, oil_price, shipping_index, exchange_rates = load_core_data()

events_json  = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()
shipping_df  = compute_shipping_status(events_json)
analytics    = RiskAnalytics.get_summary_metrics(events_df, oil_price, shipping_index)
filtered_evs = filter_events(events_df)

if len(shipping_df) > 0:
    worst_status = shipping_df.sort_values("Risk Score", ascending=False).iloc[0]["Status"]
    # Build risk_scores dict for graph weighting: {route_name: score}
    risk_scores = dict(zip(shipping_df["Route"], shipping_df["Risk Score"].astype(int)))
else:
    worst_status = "Operational"
    risk_scores  = {}

crit  = analytics.get("critical_events", 0)
high  = analytics.get("high_events", 0)
total = analytics.get("total_events", 0)

render_header(crit, high, total, worst_status, 0)
render_nav()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE INTRO
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div style="padding:14px 16px;border-bottom:1px solid #1a1a1a;margin-bottom:8px">
  <div style="font-size:13px;font-weight:700;color:#e8e8e8;margin-bottom:4px">
    🧭 MariNav Route Calculator
  </div>
  <div style="font-size:11px;color:#666;line-height:1.5">
    Finds the lowest-risk maritime route between any two ports using an H3 hexagonal
    grid + NetworkX shortest-path algorithm — the same approach used by
    <a href="https://github.com/Vaishnav2804/MariNav" target="_blank"
       style="color:#3b82f6;text-decoration:none">MariNav (Vaishnav2804)</a>.
    Edge weights combine geographic distance and live TradeWatch risk scores,
    so the optimizer automatically avoids high-risk chokepoints.
  </div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# ROUTE SELECTOR
# ══════════════════════════════════════════════════════════════════════════════
port_list = sorted(PORTS.keys())

sel_col1, sel_col2, sel_col3, _ = st.columns([2, 2, 1, 3])

with sel_col1:
    origin = st.selectbox("Origin Port", port_list,
                          index=port_list.index("Rotterdam"), key="mnav_origin")
with sel_col2:
    dest_default = "Singapore"
    destination  = st.selectbox("Destination Port", port_list,
                                index=port_list.index(dest_default), key="mnav_dest")
with sel_col3:
    st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
    compute = st.button("Calculate Route", type="primary", use_container_width=True)

# ── Live risk warning banner ───────────────────────────────────────────────────
if len(shipping_df) > 0:
    high_risk_routes = shipping_df[shipping_df["Risk Score"] >= 40]
    if not high_risk_routes.empty:
        names = " · ".join(high_risk_routes["Route"].tolist())
        st.markdown(f"""
<div style="background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.2);
            border-left:3px solid #ef4444;border-radius:3px;padding:6px 12px;
            font-size:10px;color:#ef4444;margin-bottom:6px">
  ⚠ HIGH-RISK CHOKEPOINTS ACTIVE — optimizer will penalize routes through:
  <b>{names}</b>
</div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# COMPUTE + DISPLAY
# ══════════════════════════════════════════════════════════════════════════════
if compute or st.session_state.get("mnav_result"):

    if compute:
        with st.spinner("Building risk-weighted shipping graph…"):
            G = build_shipping_graph(MAJOR_SHIPPING_ROUTES, risk_scores)
        with st.spinner("Finding optimal route…"):
            result = find_optimal_route(origin, destination, G, risk_scores)
        st.session_state["mnav_result"] = result
        st.session_state["mnav_origin_last"] = origin
        st.session_state["mnav_dest_last"]   = destination
    else:
        result = st.session_state["mnav_result"]

    if "error" in result:
        st.error(f"Routing error: {result['error']}")
        st.stop()

    path_coords      = result["path_coords"]
    chokepoints_used = result["chokepoints_used"]
    route_segments   = result["route_segments"]
    orig_coords      = result["origin_coords"]
    dest_coords      = result["destination_coords"]
    total_dist_km    = result["total_dist_km"]
    origin_name      = result["origin"]
    dest_name        = result["destination"]

    # ── Build route risk profile ───────────────────────────────────────────────
    KNOTS_SPEED   = 16  # average container ship speed
    voyage_days   = round(total_dist_km / (KNOTS_SPEED * 1.852 * 24), 1)
    wti           = oil_price if oil_price else 78.45
    bunker        = wti * 6.35
    fuel_cons_day = 55.0  # t/day (Panamax default)
    base_fuel_usd = fuel_cons_day * voyage_days * bunker

    max_risk = 0
    for cp in chokepoints_used:
        max_risk = max(max_risk, risk_scores.get(cp, 0))
    surcharge_pct = max_risk / 400.0
    risk_usd      = base_fuel_usd * surcharge_pct

    # ══════════════════════════════════════════════════════════════════════════
    # LAYOUT: Globe (60%) │ Route Detail (40%)
    # ══════════════════════════════════════════════════════════════════════════
    map_col, info_col = st.columns([3, 2], gap="small")

    # ── Globe with route ───────────────────────────────────────────────────────
    with map_col:
        lats = [c[0] for c in path_coords]
        lons = [c[1] for c in path_coords]

        fig = go.Figure()

        # Route line
        fig.add_trace(go.Scattergeo(
            lat=lats, lon=lons,
            mode="lines",
            line=dict(width=3, color="#3b82f6"),
            name="Optimal Route",
            hoverinfo="skip",
        ))

        # Dotted alternative-route hint (Cape path if Suez is risky)
        if "Suez Canal" in chokepoints_used:
            suez_risk = risk_scores.get("Suez Canal", 0)
            if suez_risk >= 40:
                cape = MAJOR_SHIPPING_ROUTES.get("Cape of Good Hope", {}).get("coords", [])
                if cape:
                    fig.add_trace(go.Scattergeo(
                        lat=[c[0] for c in cape],
                        lon=[c[1] for c in cape],
                        mode="lines",
                        line=dict(width=1.5, color="#444444", dash="dot"),
                        name="Alt: Cape of Good Hope",
                        hoverinfo="skip",
                    ))

        # Waypoint markers
        if len(lats) > 2:
            fig.add_trace(go.Scattergeo(
                lat=lats[1:-1], lon=lons[1:-1],
                mode="markers",
                marker=dict(size=5, color="#3b82f6", opacity=0.5),
                hoverinfo="skip",
                showlegend=False,
            ))

        # Origin marker
        fig.add_trace(go.Scattergeo(
            lat=[orig_coords[0]], lon=[orig_coords[1]],
            mode="markers+text",
            marker=dict(size=12, color="#22c55e", symbol="circle"),
            text=[origin_name],
            textposition="top right",
            textfont=dict(size=10, color="#22c55e"),
            name=f"Origin: {origin_name}",
            hovertemplate=f"<b>{origin_name}</b><extra></extra>",
        ))

        # Destination marker
        fig.add_trace(go.Scattergeo(
            lat=[dest_coords[0]], lon=[dest_coords[1]],
            mode="markers+text",
            marker=dict(size=12, color="#f97316", symbol="circle"),
            text=[dest_name],
            textposition="top right",
            textfont=dict(size=10, color="#f97316"),
            name=f"Destination: {dest_name}",
            hovertemplate=f"<b>{dest_name}</b><extra></extra>",
        ))

        # Chokepoint risk markers
        CHOKEPOINT_COORDS = {
            "Suez Canal":        (30.7,   32.4),
            "Strait of Hormuz":  (26.2,   56.3),
            "Singapore Strait":  (1.2,   103.9),
            "Panama Canal":      (9.0,   -79.6),
            "English Channel":   (50.6,    0.0),
            "Cape of Good Hope": (-34.4,  18.5),
        }
        for cp in chokepoints_used:
            if cp in CHOKEPOINT_COORDS:
                c_lat, c_lon = CHOKEPOINT_COORDS[cp]
                cp_risk  = risk_scores.get(cp, 0)
                cp_color = risk_col(cp_risk)
                fig.add_trace(go.Scattergeo(
                    lat=[c_lat], lon=[c_lon],
                    mode="markers+text",
                    marker=dict(size=10, color=cp_color, symbol="diamond",
                                line=dict(width=1, color="#000")),
                    text=[f"{cp.split()[-1]} {cp_risk}"],
                    textposition="bottom right",
                    textfont=dict(size=9, color=cp_color),
                    name=cp,
                    hovertemplate=f"<b>{cp}</b><br>Risk: {cp_risk}/100<extra></extra>",
                ))

        # Center globe on midpoint of route
        mid_lat = (orig_coords[0] + dest_coords[0]) / 2
        mid_lon = (orig_coords[1] + dest_coords[1]) / 2

        fig.update_layout(
            geo=dict(
                projection_type="orthographic",
                projection_rotation=dict(lon=mid_lon, lat=mid_lat, roll=0),
                bgcolor="#0a0a0a",
                landcolor="#0a2018",
                oceancolor="#020a08",
                lakecolor="#020a08",
                showland=True,
                showocean=True,
                showlakes=True,
                showcountries=False,
                showcoastlines=True,
                coastlinecolor="#1a3a2a",
                coastlinewidth=0.5,
            ),
            paper_bgcolor="#0a0a0a",
            margin=dict(l=0, r=0, t=0, b=0),
            height=520,
            legend=dict(
                bgcolor="rgba(20,20,20,0.85)", font_color="#888", font_size=9,
                bordercolor="#2a2a2a", borderwidth=1,
                x=0.01, y=0.99, xanchor="left", yanchor="top",
            ),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False,
                                                                "scrollZoom": True})

    # ── Route detail panel ─────────────────────────────────────────────────────
    with info_col:

        # Summary card
        st.markdown(f"""
<div style="background:rgba(59,130,246,0.06);border:1px solid rgba(59,130,246,0.25);
            border-left:3px solid #3b82f6;border-radius:4px;padding:12px 14px;margin-bottom:8px">
  <div style="font-size:10px;color:#3b82f6;font-weight:700;text-transform:uppercase;
              letter-spacing:0.5px;margin-bottom:8px">Optimal Route Found</div>
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px">
    <span style="font-size:11px;color:#aaa">Route</span>
    <span style="font-size:12px;font-weight:700;color:#e8e8e8">
      {origin_name} → {dest_name}
    </span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="font-size:11px;color:#aaa">Distance</span>
    <span style="font-size:11px;font-weight:600;color:#e8e8e8">
      {total_dist_km:,} km
    </span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="font-size:11px;color:#aaa">Est. Voyage</span>
    <span style="font-size:11px;font-weight:600;color:#e8e8e8">
      ~{voyage_days} days @ {KNOTS_SPEED} kn
    </span>
  </div>
  <div style="display:flex;justify-content:space-between">
    <span style="font-size:11px;color:#aaa">Waypoints</span>
    <span style="font-size:11px;font-weight:600;color:#e8e8e8">
      {result["node_count"]} nodes
    </span>
  </div>
</div>
""", unsafe_allow_html=True)

        # Chokepoints panel
        st.markdown('<div class="tw-panel"><div class="tw-panel-title">Chokepoints on Route</div>',
                    unsafe_allow_html=True)

        if chokepoints_used:
            for cp in chokepoints_used:
                cp_risk = risk_scores.get(cp, 0)
                cp_col  = risk_col(cp_risk)
                # Find status from shipping_df
                cp_status = "Unknown"
                if len(shipping_df) > 0:
                    row = shipping_df[shipping_df["Route"] == cp]
                    if not row.empty:
                        cp_status = row.iloc[0]["Status"]
                        cp_delay  = row.iloc[0]["Average Delay"]
                        cp_cost   = row.iloc[0]["Cost Impact"]
                    else:
                        cp_delay, cp_cost = "—", "—"
                else:
                    cp_delay, cp_cost = "—", "—"

                sc_  = SC.get(cp_status, "#666")
                st.markdown(f"""
<div style="border-left:3px solid {cp_col};padding:7px 10px;margin:4px 0;
            border-radius:0 3px 3px 0;background:rgba(255,255,255,0.02)">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">
    <span style="font-size:11px;font-weight:700;color:#e8e8e8">{cp}</span>
    <span style="font-size:16px;font-weight:700;color:{cp_col}">{cp_risk}</span>
  </div>
  <div style="display:flex;gap:12px;font-size:9px;color:#666">
    <span style="color:{sc_}">{cp_status.replace("Operational - ","").replace("Critical - ","")}</span>
    <span>Delay: {cp_delay}</span>
    <span>Cost: {cp_cost}</span>
  </div>
  <div class="tw-risk-bar-bg" style="margin-top:4px">
    <div class="tw-risk-bar-fill" style="width:{cp_risk}%;background:{cp_col}"></div>
  </div>
</div>""", unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="color:#555;font-size:11px;padding:8px">No major chokepoints on this route</div>',
                unsafe_allow_html=True,
            )
        st.markdown('</div>', unsafe_allow_html=True)

        # Cost estimate
        st.markdown(f"""
<div class="tw-panel">
  <div class="tw-panel-title">Voyage Cost Estimate
    <span style="font-size:8px;color:#444">(Panamax, {fuel_cons_day:.0f}t/day)</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
    <div>
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">
        Base Fuel
      </div>
      <div style="font-size:18px;font-weight:700;color:#e8e8e8">
        ${base_fuel_usd:,.0f}
      </div>
    </div>
    <div>
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">
        Risk Surcharge
      </div>
      <div style="font-size:18px;font-weight:700;color:#f97316">
        ${risk_usd:,.0f}
      </div>
    </div>
    <div style="grid-column:1/-1;border-top:1px solid var(--border);padding-top:8px;margin-top:4px">
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">
        Total Estimate
      </div>
      <div style="font-size:22px;font-weight:700;color:#22c55e">
        ${(base_fuel_usd + risk_usd):,.0f}
      </div>
    </div>
  </div>
  <div style="margin-top:6px;font-size:9px;color:#444">
    WTI ${wti:.2f}/bbl → Bunker HFO ${bunker:.0f}/ton · +{surcharge_pct*100:.0f}% risk surcharge
  </div>
</div>
""", unsafe_allow_html=True)

        # Route segments breakdown
        non_junction = {k: v for k, v in route_segments.items() if k != "junction"}
        if non_junction:
            st.markdown('<div class="tw-label">Shipping Lanes Used</div>', unsafe_allow_html=True)
            seg_html = ""
            total_nodes = sum(non_junction.values()) or 1
            for lane, count in non_junction.items():
                pct = count / total_nodes * 100
                lc  = "#3b82f6" if lane not in CHOKEPOINT_ROUTES else risk_col(
                    risk_scores.get(lane, 0)
                )
                seg_html += f"""
<div style="margin:3px 0">
  <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:2px">
    <span style="color:#aaa">{lane}</span>
    <span style="color:{lc}">{pct:.0f}%</span>
  </div>
  <div style="background:#111;border-radius:1px;height:3px">
    <div style="background:{lc};width:{pct}%;height:3px;border-radius:1px"></div>
  </div>
</div>"""
            st.markdown(seg_html, unsafe_allow_html=True)

        # MariNav credit
        st.markdown("""
<div style="margin-top:16px;padding:8px 10px;border:1px solid #1e1e1e;
            border-radius:3px;font-size:9px;color:#444;line-height:1.5">
  Routing algorithm inspired by
  <a href="https://github.com/Vaishnav2804/MariNav" target="_blank"
     style="color:#3b82f6;text-decoration:none">MariNav</a>
  by Vaishnav2804 — H3 hexagonal grid + NetworkX shortest path,
  adapted with live TradeWatch risk weights.
</div>
""", unsafe_allow_html=True)

else:
    # Empty state
    st.markdown("""
<div style="height:320px;display:flex;align-items:center;justify-content:center;
            border:1px solid #1e1e1e;border-radius:4px;margin:16px">
  <div style="text-align:center;color:#444">
    <div style="font-size:32px;margin-bottom:8px">🧭</div>
    <div style="font-size:12px">Select origin and destination ports, then click <b style="color:#666">Calculate Route</b></div>
  </div>
</div>
""", unsafe_allow_html=True)

render_footer()
