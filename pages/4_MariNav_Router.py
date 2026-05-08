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
    find_route_alternatives,
    ROUTE_OBJECTIVES,
    PORTS,
    CHOKEPOINT_ROUTES,
    H3_AVAILABLE,
)
from config import MAJOR_SHIPPING_ROUTES
from api_integrations import APIClient
from canal_tolls import estimate_toll_usd
from vessel_physics import (
    VESSEL_PROFILES,
    voyage_totals as physics_voyage_totals,
    fuel_for_edge,
    monte_carlo_voyage,
    co2_tonnes,
)
from marinav_router import _haversine_km
import math

# Default daily OPEX (excluding fuel) per vessel class — drives the
# slow-steaming break-even on the Speed vs Cost chart. Indicative values
# from public charter / TCE references; user can override via sidebar.
_DEFAULT_OPEX_PER_DAY: dict[str, int] = {
    "Panamax bulker":     12_000,
    "Suezmax tanker":     25_000,
    "VLCC tanker":        28_000,
    "ULCV container":     50_000,
    "MR product tanker":  10_000,
}

# Lat/lon for each Ship & Bunker port (matches keys returned by
# APIClient.get_bunker_prices). Reuses port_baselines where possible.
_BUNKER_PORT_COORDS: dict[str, tuple[float, float]] = {
    "Singapore":       (1.265, 103.820),
    "Rotterdam":       (51.900, 4.143),
    "Fujairah":        (25.166, 56.336),
    "Hong Kong":       (22.305, 114.193),
    "Houston":         (29.730, -95.262),
    "Santos":          (-23.953, -46.330),
    "LA / Long Beach": (33.745, -118.240),
    "New York":        (40.650, -74.035),
}

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
# SIDEBAR — voyage parameters (always rendered so alternatives can use them)
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("**Voyage parameters**")
    vessel_name = st.selectbox(
        "Vessel", list(VESSEL_PROFILES.keys()), index=0, key="mn_vessel",
        help="Drives weather-aware fuel, Monte Carlo P10/P50/P90, "
             "and canal-transit toll lookup.",
    )
    vessel = VESSEL_PROFILES[vessel_name]
    speed_kn = st.slider("Service speed (kn)", 8.0, 24.0,
                          float(vessel.design_speed_kn), 0.5,
                          key="mn_speed")
    st.checkbox("Weather-aware routing", value=True, key="mn_use_weather",
                help="Sample Open-Meteo wind + wave at each backbone edge "
                     "midpoint and weight Dijkstra accordingly.")
    opex_per_day = st.number_input(
        "Daily OPEX excl. fuel ($/day)",
        min_value=0, max_value=200_000,
        value=_DEFAULT_OPEX_PER_DAY.get(vessel_name, 15_000),
        step=1_000, key="mn_opex",
        help="Charter hire + crew + insurance. Drives the slow-steaming "
             "break-even on the Speed vs Cost chart.",
    )
    bunker_df = APIClient.get_bunker_prices()
    bunker_ports = sorted(bunker_df["port"].unique()) if len(bunker_df) > 0 else ["Singapore"]
    bunker_port = st.selectbox("Bunker port", bunker_ports,
                                index=bunker_ports.index("Singapore") if "Singapore" in bunker_ports else 0,
                                key="mn_bunker_port")

# Aliases used by downstream code
vessel_class = vessel_name
physics_profile = vessel
physics_profile_name = vessel_name

# Live VLSFO from Ship & Bunker; fall back if scrape failed
bunker = 600.0
if len(bunker_df) > 0:
    match = bunker_df[(bunker_df["port"] == bunker_port) & (bunker_df["grade"] == vessel.fuel_grade)]
    if len(match) > 0:
        bunker = float(match.iloc[0]["price_usd_per_mt"])

# ══════════════════════════════════════════════════════════════════════════════
# COMPUTE + DISPLAY
# ══════════════════════════════════════════════════════════════════════════════
if compute or st.session_state.get("mnav_alternatives"):

    if compute:
        # Weather provider — toggleable. When enabled, samples wind+wave at
        # each backbone-edge midpoint via Open-Meteo (cached). Adds ~2-3s on
        # first run for ~50 edges; cached afterwards for 1h (wind) / event-TTL
        # (waves), so subsequent re-routes are instant.
        use_weather = st.session_state.get("mn_use_weather", True)

        @st.cache_data(ttl=3600, show_spinner=False)
        def _wx_at(lat: float, lon: float) -> dict:
            wind = APIClient.get_wind_at(lat, lon) or {}
            marine = APIClient.get_marine_weather(lat, lon) or {}
            return {
                "wind_speed_ms": wind.get("wind_speed_ms") or 0.0,
                "wind_dir_deg":  wind.get("wind_dir_deg") or 0.0,
                "wave_h_m":      marine.get("wave_height_m") or 0.0,
            }

        wx_provider = _wx_at if use_weather else None

        spinner_msg = "Sampling weather along backbone + building graph…" if use_weather \
                      else "Building risk-weighted shipping graph…"
        with st.spinner(spinner_msg):
            G = build_shipping_graph(MAJOR_SHIPPING_ROUTES, risk_scores,
                                     weather_provider=wx_provider)
        with st.spinner("Computing 4 route alternatives…"):
            alternatives = find_route_alternatives(
                origin, destination, G, risk_scores,
                vessel, speed_kn, bunker, float(opex_per_day),
            )
        # Filter out error responses
        alternatives = [a for a in alternatives if "error" not in a]
        if not alternatives:
            st.error("Routing error: no path found between these ports.")
            st.stop()
        st.session_state["mnav_alternatives"] = alternatives
        st.session_state["mnav_origin_last"]  = origin
        st.session_state["mnav_dest_last"]    = destination
        st.session_state["mnav_used_weather"] = bool(use_weather)
        # Default pick = Recommended (balanced); fall back to first alt
        st.session_state["mn_picked_route"] = next(
            (a["objective"] for a in alternatives if a["objective"] == "balanced"),
            alternatives[0]["objective"],
        )

    alternatives = st.session_state["mnav_alternatives"]
    picked_key = st.session_state.get("mn_picked_route", "balanced")
    # The "result" used by the existing Detail panel below is whichever
    # alternative the planner has currently picked.
    result = next(
        (a for a in alternatives if a["objective"] == picked_key),
        alternatives[0],
    )

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

    # ══════════════════════════════════════════════════════════════════════════
    # ROUTE ALTERNATIVES — comparison cards (the heart of the new UI)
    # ══════════════════════════════════════════════════════════════════════════
    # The "Recommended" alternative is the reference point for all deltas.
    rec_alt = next((a for a in alternatives if a["objective"] == "balanced"),
                   alternatives[0])
    rec_econ = rec_alt["economics"]

    st.markdown(
        '<div class="tw-label" style="margin:6px 0 4px 0">'
        'Route alternatives — pick the one that fits your priorities</div>',
        unsafe_allow_html=True,
    )

    alt_cols = st.columns(len(alternatives))
    for col, alt in zip(alt_cols, alternatives):
        e = alt["economics"]
        is_picked = alt["objective"] == picked_key
        is_rec    = alt["objective"] == "balanced"
        delta_days_vs_rec = e["voyage_days"] - rec_econ["voyage_days"]
        delta_usd_vs_rec  = e["total_usd"]   - rec_econ["total_usd"]

        # Card colour intensity reflects whether it's currently picked.
        accent      = alt["color"]
        border      = f"2px solid {accent}" if is_picked else f"1px solid {accent}55"
        ring_glow   = f"box-shadow:0 0 0 2px {accent}33;" if is_picked else ""
        risk_color  = "#ef4444" if e["max_chokepoint_risk"] >= 70 else \
                      "#f97316" if e["max_chokepoint_risk"] >= 40 else \
                      "#eab308" if e["max_chokepoint_risk"] >= 15 else "#22c55e"

        cps_text = " · ".join(alt["chokepoints_used"]) if alt["chokepoints_used"] else "Open ocean only"
        if alt.get("duplicate_of"):
            dup_label = next((a["label"] for a in alternatives
                              if a["objective"] == alt["duplicate_of"]), "")
            cps_text = f"Same path as {dup_label}"

        if is_rec:
            delta_html = '<span style="color:#888">— reference</span>'
        else:
            d_days_sign = "+" if delta_days_vs_rec >= 0 else ""
            d_usd_sign  = "+" if delta_usd_vs_rec >= 0 else "−"
            d_usd_color = "#ef4444" if delta_usd_vs_rec > 0 else "#22c55e" if delta_usd_vs_rec < 0 else "#888"
            d_days_color = "#ef4444" if delta_days_vs_rec > 0 else "#22c55e" if delta_days_vs_rec < 0 else "#888"
            delta_html = (
                f'<span style="color:{d_days_color}">{d_days_sign}{delta_days_vs_rec:.1f}d</span>'
                f' <span style="color:#444">·</span> '
                f'<span style="color:{d_usd_color}">{d_usd_sign}${abs(delta_usd_vs_rec)/1000:,.0f}k</span>'
            )

        with col:
            st.markdown(f"""
<div style="background:#0a0a0a;border:{border};{ring_glow}
            border-top:3px solid {accent};border-radius:4px;
            padding:10px 12px 8px 12px;min-height:172px">
  <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
    <span style="font-size:14px">{alt["icon"]}</span>
    <span style="font-size:11px;font-weight:700;color:{accent};text-transform:uppercase;letter-spacing:0.05em">
      {alt["label"]}
    </span>
  </div>
  <div style="font-size:9px;color:#666;margin-bottom:8px;line-height:1.3">{alt["tagline"]}</div>
  <div style="font-size:18px;font-weight:700;color:#e8e8e8;line-height:1.1">
    ${e["total_usd"]/1000:,.0f}<span style="font-size:10px;color:#666">k total</span>
  </div>
  <div style="font-size:10px;color:#888;margin-top:2px">
    {alt["total_dist_km"]:,} km · {e["voyage_days"]:.1f} days
  </div>
  <div style="font-size:10px;margin-top:4px">
    Max chokepoint risk: <span style="color:{risk_color};font-weight:700">{int(e["max_chokepoint_risk"])}/100</span>
  </div>
  <div style="font-size:10px;color:#888;margin-top:3px;line-height:1.4">
    {cps_text}
  </div>
  <div style="font-size:10px;margin-top:6px;border-top:1px solid #1a1a1a;padding-top:5px">
    Δ vs Recommended: {delta_html}
  </div>
</div>""", unsafe_allow_html=True)

            btn_label = "✓ Picked" if is_picked else "Pick this route"
            if st.button(btn_label, key=f"pick_{alt['objective']}",
                          use_container_width=True,
                          disabled=is_picked, type="primary" if is_picked else "secondary"):
                st.session_state["mn_picked_route"] = alt["objective"]
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # WHY THIS ROUTE — auto-generated narrative for the picked alternative
    # ══════════════════════════════════════════════════════════════════════════
    picked_econ = result["economics"]
    why_lines: list[str] = []

    # 1. Headline summary of the picked route
    cps_picked = result["chokepoints_used"]
    cps_phrase = " and ".join(cps_picked) if cps_picked else "open ocean only (no monitored chokepoints)"
    why_lines.append(
        f"<b>{result['label']}</b> routes via <b>{cps_phrase}</b> — "
        f"{result['total_dist_km']:,} km, {picked_econ['voyage_days']:.1f} days, "
        f"<b>${picked_econ['total_usd']/1000:,.0f}k</b> total estimated cost."
    )

    # 2. Live risk callout for any high-risk chokepoint actually used
    risky_cps_used = [(cp, risk_scores.get(cp, 0)) for cp in cps_picked
                      if risk_scores.get(cp, 0) >= 40]
    if risky_cps_used:
        bullet = "; ".join(f"<b>{cp}</b> rated <b>{r}/100</b>" for cp, r in risky_cps_used)
        why_lines.append(f"⚠ Live risk on this path: {bullet}.")

    # 3. Tradeoff vs the alternative-of-interest (cheapest alternative not picked)
    other_alts = [a for a in alternatives if a["objective"] != result["objective"]
                  and not a.get("duplicate_of")]
    if other_alts:
        # Find the alternative most different from the picked one (largest delta)
        most_different = max(other_alts,
                              key=lambda a: abs(a["economics"]["total_usd"] - picked_econ["total_usd"]))
        diff_econ = most_different["economics"]
        ddays = picked_econ["voyage_days"] - diff_econ["voyage_days"]
        dusd  = picked_econ["total_usd"]   - diff_econ["total_usd"]
        if abs(dusd) > 1000 or abs(ddays) > 0.1:
            time_word = "saves" if ddays < 0 else "costs"
            cost_word = "saves" if dusd < 0 else "costs"
            why_lines.append(
                f"vs <b>{most_different['label']}</b> "
                f"({most_different['total_dist_km']:,} km via {' / '.join(most_different['chokepoints_used']) or 'open ocean'}): "
                f"this route {time_word} <b>{abs(ddays):.1f} days</b> and "
                f"{cost_word} <b>${abs(dusd)/1000:,.0f}k</b>."
            )

    # 4. Cost driver breakdown
    fuel_pct = picked_econ["fuel_usd"] / max(1, picked_econ["total_usd"]) * 100
    toll_pct = picked_econ["toll_usd"] / max(1, picked_econ["total_usd"]) * 100
    risk_pct = picked_econ["risk_surcharge_usd"] / max(1, picked_econ["total_usd"]) * 100
    opex_pct = picked_econ["opex_usd"] / max(1, picked_econ["total_usd"]) * 100
    drivers = []
    if fuel_pct >= 5: drivers.append(f"fuel <b>{fuel_pct:.0f}%</b>")
    if opex_pct >= 5: drivers.append(f"opex <b>{opex_pct:.0f}%</b>")
    if toll_pct >= 1: drivers.append(f"canal toll <b>{toll_pct:.0f}%</b>")
    if risk_pct >= 1: drivers.append(f"war-risk surcharge <b>{risk_pct:.0f}%</b>")
    if drivers:
        why_lines.append(f"Cost split: {' · '.join(drivers)}.")

    # 5. Toll cannot-transit warning
    for cp in cps_picked:
        canal = "suez" if "Suez" in cp else "panama" if "Panama" in cp else None
        if canal and estimate_toll_usd(canal, vessel_class) is None:
            why_lines.append(
                f"⛔ Note: <b>{vessel_class}</b> cannot physically transit "
                f"<b>{canal.title()} Canal</b> (vessel exceeds beam/draught limits)."
            )

    why_html = "".join(f'<div style="margin:4px 0;line-height:1.55">{ln}</div>' for ln in why_lines)
    st.markdown(f"""
<div style="background:rgba(59,130,246,0.05);border:1px solid rgba(59,130,246,0.2);
            border-left:3px solid {result['color']};border-radius:3px;
            padding:10px 14px;margin:10px 0 12px 0;font-size:11px;color:#cfe1ff">
  <div style="font-size:9px;font-weight:700;color:{result['color']};text-transform:uppercase;
              letter-spacing:0.5px;margin-bottom:4px">
    {result['icon']} Why we{("'re recommending") if picked_key == "balanced" else "'ve picked"} this route
  </div>
  {why_html}
</div>""", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # Legacy single-route variables (used by the existing Detail panel below)
    # ══════════════════════════════════════════════════════════════════════════
    # ── Physics-based voyage fuel & ETA ──────────────────────────────────────
    path_edges = [e for e in result.get("path_edges", []) or [] if e is not None]
    physics_used = bool(path_edges)
    if physics_used:
        det = physics_voyage_totals(vessel, path_edges, speed_kn)
        voyage_days   = round(det["days"], 1)
        fuel_total_t  = det["fuel_t"]
        fuel_cons_day = fuel_total_t / max(0.01, det["days"])
        mc = monte_carlo_voyage(vessel, path_edges, speed_kn, n=200)
    else:
        # Fallback: calm-water cubic burn (no per-edge metadata available).
        voyage_days   = round(total_dist_km / (speed_kn * 1.852 * 24), 1)
        fuel_cons_day = vessel.fuel_tpd(speed_kn)
        fuel_total_t  = fuel_cons_day * voyage_days
        mc = None

    base_fuel_usd = picked_econ["fuel_usd"]
    risk_usd      = picked_econ["risk_surcharge_usd"]
    toll_usd      = picked_econ["toll_usd"]
    max_risk      = picked_econ["max_chokepoint_risk"]
    surcharge_pct = picked_econ["surcharge_pct"]

    # Toll lines for the existing Detail panel
    toll_lines = []
    for cp in chokepoints_used:
        canal = None
        if "Suez" in cp:   canal = "suez"
        elif "Panama" in cp: canal = "panama"
        if canal:
            t = estimate_toll_usd(canal, vessel_class)
            if t is None:
                toll_lines.append(f"⚠ {vessel_class} cannot transit {canal.title()}")
            else:
                toll_lines.append(f"{canal.title()} toll: ${t:,.0f}")

    # ══════════════════════════════════════════════════════════════════════════
    # LAYOUT: Globe (60%) │ Route Detail (40%)
    # ══════════════════════════════════════════════════════════════════════════
    map_col, info_col = st.columns([3, 2], gap="small")

    # ── Great-circle interpolation helper ──────────────────────────────────────
    # Plotly's Scattergeo draws straight lon/lat segments between consecutive
    # points, which can visibly cut over land on a long edge. Subdividing each
    # edge with great-circle (Slerp) interpolation makes the line follow the
    # curvature of the earth and stay over water.
    def _gc_subdivide(coords: list[tuple[float, float]], steps_per_edge: int = 30
                      ) -> tuple[list[float], list[float]]:
        if not coords:
            return [], []
        out_lat: list[float] = [coords[0][0]]
        out_lon: list[float] = [coords[0][1]]
        for (lat1, lon1), (lat2, lon2) in zip(coords, coords[1:]):
            phi1, phi2 = math.radians(lat1), math.radians(lat2)
            lam1, lam2 = math.radians(lon1), math.radians(lon2)
            # Cartesian unit-sphere endpoints
            x1, y1, z1 = (math.cos(phi1)*math.cos(lam1),
                          math.cos(phi1)*math.sin(lam1), math.sin(phi1))
            x2, y2, z2 = (math.cos(phi2)*math.cos(lam2),
                          math.cos(phi2)*math.sin(lam2), math.sin(phi2))
            cos_d = max(-1.0, min(1.0, x1*x2 + y1*y2 + z1*z2))
            d = math.acos(cos_d)
            if d < 1e-9:
                out_lat.append(lat2); out_lon.append(lon2); continue
            sin_d = math.sin(d)
            for i in range(1, steps_per_edge + 1):
                f = i / steps_per_edge
                a = math.sin((1 - f)*d) / sin_d
                b = math.sin(f*d) / sin_d
                x = a*x1 + b*x2
                y = a*y1 + b*y2
                z = a*z1 + b*z2
                lat_i = math.degrees(math.atan2(z, math.sqrt(x*x + y*y)))
                lon_i = math.degrees(math.atan2(y, x))
                out_lat.append(lat_i); out_lon.append(lon_i)
        return out_lat, out_lon

    # ── Globe with all alternatives ───────────────────────────────────────────
    with map_col:
        fig = go.Figure()

        # Draw non-picked alternatives first (faded dotted) so the picked
        # primary route renders on top.
        for alt in alternatives:
            if alt["objective"] == picked_key:
                continue
            if alt.get("duplicate_of"):
                # Same path as a higher-priority alt — skip rather than draw
                # the same line twice.
                continue
            a_lat, a_lon = _gc_subdivide(alt["path_coords"])
            fig.add_trace(go.Scattergeo(
                lat=a_lat, lon=a_lon, mode="lines",
                line=dict(width=1.5, color=alt["color"], dash="dot"),
                opacity=0.45,
                name=f"{alt['icon']} {alt['label']}",
                hovertemplate=(f"<b>{alt['label']}</b><br>"
                                f"{alt['total_dist_km']:,} km · "
                                f"{alt['economics']['voyage_days']:.1f} d · "
                                f"${alt['economics']['total_usd']/1000:,.0f}k"
                                "<extra></extra>"),
            ))

        # Picked route — bright + thick on top
        p_lat, p_lon = _gc_subdivide(result["path_coords"])
        fig.add_trace(go.Scattergeo(
            lat=p_lat, lon=p_lon, mode="lines",
            line=dict(width=4, color=result["color"]),
            name=f"{result['icon']} {result['label']} (picked)",
            hovertemplate=(f"<b>{result['label']}</b><br>"
                            f"{result['total_dist_km']:,} km · "
                            f"{picked_econ['voyage_days']:.1f} d · "
                            f"${picked_econ['total_usd']/1000:,.0f}k"
                            "<extra></extra>"),
        ))

        # Waypoint markers along the picked route (small dots at junctions)
        picked_lats = [c[0] for c in result["path_coords"]]
        picked_lons = [c[1] for c in result["path_coords"]]
        if len(picked_lats) > 2:
            fig.add_trace(go.Scattergeo(
                lat=picked_lats[1:-1], lon=picked_lons[1:-1],
                mode="markers",
                marker=dict(size=5, color=result["color"], opacity=0.5),
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
      ~{voyage_days} days @ {speed_kn:.0f} kn
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

        # ── Per-leg breakdown (segment-by-segment for the picked route) ──────
        if path_edges:
            path_nodes = result["path"]
            leg_rows: list[str] = []
            cumulative_hours = 0.0
            for idx, edge in enumerate(path_edges, start=1):
                leg = fuel_for_edge(vessel, edge, speed_kn)
                cumulative_hours += leg["duration_h"]
                a_node = path_nodes[idx - 1] if idx - 1 < len(path_nodes) else "?"
                b_node = path_nodes[idx]     if idx < len(path_nodes) else "?"
                # Pretty labels: strip "_port_" prefix or leading underscore
                def _pretty(n: str) -> str:
                    if n.startswith("_port_"):
                        return n[len("_port_"):]
                    return n.lstrip("_").replace("_", " ").title()
                a_label, b_label = _pretty(a_node), _pretty(b_node)

                # Headwind: project wind onto course
                course = edge.bearing_deg
                rel = math.radians((edge.wind_dir_deg - course + 540.0) % 360.0 - 180.0)
                head_ms = (edge.wind_speed_ms or 0.0) * math.cos(rel)
                wind_label = (f"{abs(head_ms):.0f} m/s "
                              + ("head" if head_ms > 1.0 else "tail" if head_ms < -1.0 else "calm"))
                wave_h = edge.wave_h_m or 0.0
                sea_label = (f"{wave_h:.1f}m" if wave_h > 0.05 else "calm")
                # Highlight rough seas / strong headwinds
                rough = wave_h > 3.0 or head_ms > 8.0
                row_bg = "background:rgba(239,68,68,0.04);" if rough else ""

                leg_rows.append(f"""<tr style="{row_bg}border-bottom:1px solid #1a1a1a">
<td style="padding:5px 6px;color:#666;font-size:9px">{idx}</td>
<td style="padding:5px 6px;color:#e8e8e8;font-size:10px">{a_label} → {b_label}</td>
<td style="padding:5px 6px;text-align:right;color:#cfe1ff;font-size:10px">{edge.dist_km:,.0f}</td>
<td style="padding:5px 6px;text-align:right;color:#aaa;font-size:10px">{leg["duration_h"]:.1f}</td>
<td style="padding:5px 6px;text-align:right;color:#aaa;font-size:10px">{leg["fuel_t"]:.1f}</td>
<td style="padding:5px 6px;color:#888;font-size:10px">{wind_label}</td>
<td style="padding:5px 6px;color:#888;font-size:10px">{sea_label}</td>
</tr>""")

            st.markdown(f"""
<div class="tw-panel" style="margin-top:8px">
  <div class="tw-panel-title">Per-leg breakdown
    <span class="tw-panel-badge"
          style="background:rgba(168,85,247,0.12);color:#a855f7;border:1px solid rgba(168,85,247,0.3)">
      {len(path_edges)} legs · {cumulative_hours:.0f} h
    </span>
  </div>
  <div style="overflow-x:auto;max-height:300px;overflow-y:auto">
    <table class="tw-table" style="font-size:10px">
      <thead><tr>
        <th style="text-align:left">#</th>
        <th style="text-align:left">From → To</th>
        <th style="text-align:right">Dist (km)</th>
        <th style="text-align:right">Hours</th>
        <th style="text-align:right">Fuel (t)</th>
        <th style="text-align:left">Wind</th>
        <th style="text-align:left">Sea</th>
      </tr></thead>
      <tbody>{''.join(leg_rows)}</tbody>
    </table>
  </div>
  <div style="font-size:9px;color:#555;padding:4px 8px 0 8px">
    Rows highlighted red have head-wind ≥ 8 m/s or seas above 3 m. Sums:
    <b>{sum(e.dist_km for e in path_edges):,.0f}</b> km ·
    <b>{sum(fuel_for_edge(vessel, e, speed_kn)["fuel_t"] for e in path_edges):.1f}</b> t fuel.
  </div>
</div>""", unsafe_allow_html=True)

        # ── Monte Carlo fuel/ETA/CO2 confidence (only when physics was used) ─
        if mc is not None:
            spread_t = mc["fuel_p90"] - mc["fuel_p10"]
            spread_d = mc["days_p90"] - mc["days_p10"]
            wx_label = "Weather-aware" if st.session_state.get("mnav_used_weather") else "Calm-water"
            grade = physics_profile.fuel_grade
            co2_p10 = co2_tonnes(mc["fuel_p10"], grade)
            co2_p50 = co2_tonnes(mc["fuel_p50"], grade)
            co2_p90 = co2_tonnes(mc["fuel_p90"], grade)
            # CO2 intensity: g per nautical mile (industry-standard EEOI denom-
            # inator without cargo mass; useful per-voyage benchmark).
            nm = total_dist_km / 1.852
            co2_per_nm = (co2_p50 * 1_000_000.0) / max(1.0, nm)  # g/nm
            st.markdown(
                f'<div class="tw-panel">'
                f'<div class="tw-panel-title">{wx_label} Voyage Confidence '
                f'<span style="font-size:8px;color:#444">'
                f'({physics_profile.name}, {fuel_cons_day:.1f} t/day @ {speed_kn:.0f} kn)</span></div>'
                f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">'
                f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Fuel P10</div>'
                f'<div style="font-size:14px;font-weight:700;color:#22c55e">{mc["fuel_p10"]:,.0f} t</div></div>'
                f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Fuel P50</div>'
                f'<div style="font-size:14px;font-weight:700;color:#e8e8e8">{mc["fuel_p50"]:,.0f} t</div></div>'
                f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Fuel P90</div>'
                f'<div style="font-size:14px;font-weight:700;color:#f97316">{mc["fuel_p90"]:,.0f} t</div></div>'
                f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">ETA P10</div>'
                f'<div style="font-size:14px;font-weight:700;color:#22c55e">{mc["days_p10"]:.1f} d</div></div>'
                f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">ETA P50</div>'
                f'<div style="font-size:14px;font-weight:700;color:#e8e8e8">{mc["days_p50"]:.1f} d</div></div>'
                f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">ETA P90</div>'
                f'<div style="font-size:14px;font-weight:700;color:#f97316">{mc["days_p90"]:.1f} d</div></div>'
                f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">CO₂ P10</div>'
                f'<div style="font-size:14px;font-weight:700;color:#22c55e">{co2_p10:,.0f} t</div></div>'
                f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">CO₂ P50</div>'
                f'<div style="font-size:14px;font-weight:700;color:#e8e8e8">{co2_p50:,.0f} t</div></div>'
                f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">CO₂ P90</div>'
                f'<div style="font-size:14px;font-weight:700;color:#f97316">{co2_p90:,.0f} t</div></div>'
                f'</div>'
                f'<div style="margin-top:6px;font-size:9px;color:#444">'
                f'200 Monte Carlo trials · forecast σ = 30% (wind) / 30% log (wave) · '
                f'fuel spread {spread_t:,.0f} t · ETA spread {spread_d:.2f} d · '
                f'intensity ≈ {co2_per_nm/1000:.1f} kg CO₂/nm'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        # Cost estimate
        toll_html = ""
        if toll_usd > 0:
            toll_html = (
                f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Canal Toll</div>'
                f'<div style="font-size:18px;font-weight:700;color:#9b59b6">${toll_usd:,.0f}</div></div>'
            )
        toll_warning = "<br>".join(toll_lines) if toll_lines else ""
        total_estimate = base_fuel_usd + risk_usd + toll_usd
        st.markdown(
            f'<div class="tw-panel">'
            f'<div class="tw-panel-title">Voyage Cost Estimate '
            f'<span style="font-size:8px;color:#444">({vessel.name}, {fuel_cons_day:.1f}t/day @ {speed_kn:.0f} kn)</span></div>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">'
            f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Base Fuel</div>'
            f'<div style="font-size:18px;font-weight:700;color:#e8e8e8">${base_fuel_usd:,.0f}</div></div>'
            f'<div><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Risk Surcharge</div>'
            f'<div style="font-size:18px;font-weight:700;color:#f97316">${risk_usd:,.0f}</div></div>'
            f'{toll_html}'
            f'<div style="grid-column:1/-1;border-top:1px solid var(--border);padding-top:8px;margin-top:4px">'
            f'<div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.4px">Total Estimate</div>'
            f'<div style="font-size:22px;font-weight:700;color:#22c55e">${total_estimate:,.0f}</div></div>'
            f'</div>'
            f'<div style="margin-top:6px;font-size:9px;color:#444">'
            f'{vessel.fuel_grade} ${bunker:.0f}/MT @ {bunker_port} · +{surcharge_pct*100:.0f}% risk surcharge'
            f'{"<br>" + toll_warning if toll_warning else ""}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        # ── Bunker Stops Along Route ────────────────────────────────────────
        # For each known bunker port, compute min distance to any path
        # waypoint. Filter ports within 400 km of the route, rank by VLSFO
        # ascending. Only renders when bunker_df is populated.
        if len(bunker_df) > 0 and len(path_coords) > 0:
            bunker_pivot = bunker_df.pivot_table(
                index="port", columns="grade",
                values="price_usd_per_mt", aggfunc="first",
            )
            stops = []
            for bport, (blat, blon) in _BUNKER_PORT_COORDS.items():
                if bport not in bunker_pivot.index:
                    continue
                d_km = min(_haversine_km(blat, blon, plat, plon)
                           for plat, plon in path_coords)
                if d_km > 400:
                    continue
                row = bunker_pivot.loc[bport]
                stops.append({
                    "port":    bport,
                    "dist_km": d_km,
                    "VLSFO":   float(row.get("VLSFO")) if pd.notna(row.get("VLSFO")) else None,
                    "MGO":     float(row.get("MGO"))   if pd.notna(row.get("MGO"))   else None,
                })
            stops = [s for s in stops if s["VLSFO"] is not None]
            stops.sort(key=lambda s: s["VLSFO"])

            if stops:
                cheapest = stops[0]
                # Savings vs current bunker_port (if it's in the priced set)
                cur_price = (float(bunker_pivot.loc[bunker_port, "VLSFO"])
                             if bunker_port in bunker_pivot.index
                             and pd.notna(bunker_pivot.loc[bunker_port].get("VLSFO"))
                             else None)
                rec_html = ""
                if cur_price and cheapest["VLSFO"] < cur_price - 5:
                    saved = (cur_price - cheapest["VLSFO"]) * fuel_total_t
                    if saved >= 5_000:
                        rec_html = (f' <span class="tw-badge" '
                                    f'style="background:#22c55e22;color:#22c55e;'
                                    f'border:1px solid #22c55e44;font-size:9px">'
                                    f'✓ saves ~${saved:,.0f}</span>')
                rows_html = ""
                for s in stops[:6]:
                    is_best = s is cheapest
                    name_color = "#22c55e" if is_best else "#e8e8e8"
                    delta_html = ""
                    if cur_price:
                        delta = s["VLSFO"] - cur_price
                        dcol = "#22c55e" if delta < 0 else "#888" if abs(delta) < 1 else "#f97316"
                        sign = "−" if delta < 0 else "+"
                        delta_html = (f' <span style="color:{dcol};font-size:9px">'
                                      f'({sign}${abs(delta):.0f})</span>')
                    mgo_html = (f'<span style="color:#888">·  MGO ${s["MGO"]:.0f}</span>'
                                if s["MGO"] is not None else "")
                    rows_html += f"""
<div style="display:flex;justify-content:space-between;align-items:center;
            padding:5px 8px;margin:2px 0;border-radius:3px;
            border-left:3px solid {'#22c55e' if is_best else '#333'};
            background:rgba(255,255,255,0.01)">
  <span style="font-size:11px;font-weight:600;color:{name_color}">{s['port']}
    {('<span style="font-size:9px;color:#666;font-weight:400"> · ' + str(round(s['dist_km'])) + ' km off route</span>') if s['dist_km'] > 50 else '<span style="font-size:9px;color:#666;font-weight:400"> · on route</span>'}
  </span>
  <span style="font-size:11px;font-weight:700;color:#e8e8e8">
    ${s['VLSFO']:.0f}/MT{delta_html} {mgo_html}
  </span>
</div>"""
                st.markdown(
                    f'<div class="tw-panel">'
                    f'<div class="tw-panel-title">Bunker Stops Along Route{rec_html}</div>'
                    f'{rows_html}'
                    f'<div style="margin-top:6px;font-size:9px;color:#444">'
                    f'Δ relative to {bunker_port} · ports within 400 km of route'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

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

    # ── Speed vs Cost (full-width below the columns) ─────────────────────────
    if physics_used and len(path_edges) > 0:
        speeds = list(range(8, 23))
        fuel_costs, time_costs, total_costs = [], [], []
        for s in speeds:
            tot = physics_voyage_totals(physics_profile, path_edges, float(s))
            fc = tot["fuel_t"] * bunker
            tc = tot["days"] * float(opex_per_day)
            fuel_costs.append(fc)
            time_costs.append(tc)
            total_costs.append(fc + tc + toll_usd)
        # Find optimal
        opt_idx = total_costs.index(min(total_costs))
        opt_speed = speeds[opt_idx]
        opt_total = total_costs[opt_idx]
        # Cost at the user-selected speed for delta context
        cur_idx = min(range(len(speeds)),
                      key=lambda i: abs(speeds[i] - speed_kn))
        cur_total = total_costs[cur_idx]
        savings = cur_total - opt_total

        st.markdown('<div class="tw-label" style="margin-top:18px">Speed vs Cost</div>',
                    unsafe_allow_html=True)
        fig_sc = go.Figure()
        fig_sc.add_trace(go.Scatter(
            x=speeds, y=fuel_costs, mode="lines", name="Fuel cost",
            line=dict(color="#f97316", width=2),
        ))
        fig_sc.add_trace(go.Scatter(
            x=speeds, y=time_costs, mode="lines", name=f"Time cost (${opex_per_day:,}/d)",
            line=dict(color="#3b82f6", width=2),
        ))
        fig_sc.add_trace(go.Scatter(
            x=speeds, y=total_costs, mode="lines+markers", name="Total",
            line=dict(color="#22c55e", width=3),
            marker=dict(size=6, color="#22c55e"),
        ))
        fig_sc.add_vline(x=speed_kn, line_dash="dot", line_color="#888",
                         annotation_text=f"Now {speed_kn:.0f} kn",
                         annotation_position="top",
                         annotation_font_color="#888", annotation_font_size=9)
        fig_sc.add_vline(x=opt_speed, line_dash="dash", line_color="#22c55e",
                         annotation_text=f"Optimal {opt_speed} kn",
                         annotation_position="bottom",
                         annotation_font_color="#22c55e", annotation_font_size=9)
        fig_sc.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#0a0a0a",
            font_color="#888", height=300,
            margin=dict(t=10, b=30, l=40, r=10),
            xaxis=dict(title="Service speed (kn)", gridcolor="#1a1a1a",
                       tickfont_size=10),
            yaxis=dict(title="Cost (USD)", gridcolor="#1a1a1a",
                       tickfont_size=10, tickformat=",.0f"),
            legend=dict(bgcolor="rgba(20,20,20,0.85)", font_size=9,
                        bordercolor="#2a2a2a", borderwidth=1,
                        x=0.99, y=0.99, xanchor="right", yanchor="top"),
        )
        st.plotly_chart(fig_sc, use_container_width=True,
                        config={"displayModeBar": False})
        savings_html = ""
        if savings > 1_000:
            savings_html = (f' · saves <span style="color:#22c55e;font-weight:700">'
                            f'${savings:,.0f}</span> vs current {speed_kn:.0f} kn')
        elif savings < -1_000:
            savings_html = (f' · current {speed_kn:.0f} kn already cheaper '
                            f'than optimal sweep by ${-savings:,.0f}')
        st.markdown(
            f'<div style="font-size:10px;color:#888;margin-top:-8px">'
            f'Cost-minimising speed: <b style="color:#22c55e">{opt_speed} kn</b> '
            f'(${opt_total:,.0f} total){savings_html}. '
            f'Fuel ${bunker:.0f}/MT · OPEX ${opex_per_day:,}/d.'
            f'</div>',
            unsafe_allow_html=True,
        )

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
