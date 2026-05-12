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
    SC, SBG, risk_col, IMPACT_COL, IMPACT_ICON, lottie_loader, CONG_COL,
)
import ais_consumer
import eta_scheduler

# Start the AIS WebSocket once per process (idempotent — no-op on rerun).
ais_consumer.start_consumer()
# Start the ETA-model retraining scheduler (idempotent; no-op until enough
# real AIS data accumulates and the 24h cooldown elapses).
eta_scheduler.start_eta_scheduler()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TradeWatch",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

# ── First-load redirect to Welcome page ───────────────────────────────────────
# On the very first visit (session_state is fresh), send the user to the Landing
# page. Setting the flag before switching prevents an infinite redirect loop when
# the user navigates back here from the landing page.
if "has_seen_welcome" not in st.session_state:
    st.session_state["has_seen_welcome"] = True
    st.switch_page("pages/0_Landing.py")

# ── Data loading ──────────────────────────────────────────────────────────────
# All heavy API calls happen inside the loading screen context manager so the
# animated ship plays while the user waits. load_core_data() is cached for
# 15–30 min; compute_shipping_status / compute_port_congestion are cached
# separately and accept a JSON string (not a DataFrame) as the cache key.
with lottie_loader():
    events_df, oil_price, shipping_index, exchange_rates = load_core_data()
    events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()
    shipping_df  = compute_shipping_status(events_json)
    port_cong_df = compute_port_congestion(events_json)

# Surface live-feed health rather than silently substituting defaults.
if events_df is None or len(events_df) == 0:
    st.warning(
        "⚠ Live event feed returned no rows — chokepoint status will read "
        "**Unavailable** rather than default to Operational. "
        "Check GDELT connectivity in test_apis.py."
    )

# Aggregate KPI counts (critical / high / total) used in the header alert banner.
analytics       = RiskAnalytics.get_summary_metrics(events_df, oil_price, shipping_index)
# Apply sidebar filter state (event type, impact level, keyword search) so all
# panels on this page reflect the same filtered view.
filtered_events = filter_events(events_df)

# Auto-refresh: converts the user-selected interval (minutes) to milliseconds and
# triggers a full Streamlit rerun, re-fetching data that has passed its cache TTL.
auto_interval = st.session_state.get("refresh_interval", 10)
count         = st_autorefresh(interval=auto_interval * 60 * 1000, limit=None, key="tw_refresh")

# ── Derived values ────────────────────────────────────────────────────────────
# Parses the "Average Delay" strings like "4+ hours" into a plain float so they
# can be used in arithmetic. Returns 0 if the field is missing or malformed.
def _parse_delay_h(s):
    try:    return float(str(s).replace(" hours", "").replace("+", "").strip())
    except: return 0.0

if len(shipping_df) > 0:
    shipping_df["_delay_h"]   = shipping_df["Average Delay"].apply(_parse_delay_h)
    # Composite score blends risk (0–100) and expected delay (normalised to 48h)
    # so the "best route" recommendation accounts for both danger and transit time.
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
    # Build a {route_name: status_string} dict so maps.py can colour each route
    # line by its live computed status rather than the static traffic level.
    route_statuses = {}
    if len(shipping_df) > 0:
        route_statuses = dict(zip(shipping_df["Route"], shipping_df["Status"]))

    # ── Layer toggles ─────────────────────────────────────────────────────────
    # Fetch AIS positions (max 10 minutes old) and piracy incidents for the
    # optional map layers. These are fetched here rather than in the loading block
    # because they are only needed when this page is rendered.
    from api_integrations import APIClient
    ais_df = ais_consumer.latest_positions(max_age_sec=600)
    ais_count = len(ais_df) if ais_df is not None else 0
    piracy_df = APIClient.get_piracy_incidents(days=90)
    pir_count = len(piracy_df)
    # Seven toggle buttons let the user show/hide individual map layers in-place
    # without reloading the page. The Vessels toggle is pre-enabled only when
    # live AIS data is actually available; Piracy defaults to off to reduce clutter.
    tcols = st.columns(7)
    with tcols[0]:
        show_routes = st.toggle("Routes",  value=True,  key="lay_routes")
    with tcols[1]:
        show_ports  = st.toggle("Ports",   value=True,  key="lay_ports")
    with tcols[2]:
        show_events = st.toggle("Events",  value=True,  key="lay_events")
    with tcols[3]:
        show_ves    = st.toggle(f"Vessels ({ais_count})",
                                value=ais_count > 0, key="lay_vessels")
    with tcols[4]:
        show_pir    = st.toggle(f"Piracy ({pir_count})",
                                value=False, key="lay_piracy")
    with tcols[5]:
        show_dn     = st.toggle("Day/Night", value=True, key="lay_daynight")
    with tcols[6]:
        if st.button("↻", help="Force refresh data caches"):
            st.cache_data.clear()
            st.rerun()

    # Header chip — surface event count + AIS status. We show the multi-source
    # count separately so the user sees what made it onto the map vs. the full
    # intel feed.
    n_events = len(filtered_events)
    # on_map is True only for events confirmed by ≥2 distinct news sources.
    # Single-source events are excluded from the map to reduce false positives.
    n_on_map = (
        int(filtered_events["on_map"].fillna(False).sum())
        if "on_map" in filtered_events.columns else n_events
    )
    map_chip = (
        f"⚠ {n_on_map}/{n_events} multi-source events on map "
        f"({n_events - n_on_map} single-source in Intel Feed)"
    )
    chip_text = (
        f"{map_chip} · ⛴ {ais_count} live vessels"
        if ais_count > 0
        else f"{map_chip} · ⛴ AIS connecting…"
    )
    st.markdown(f"""
<div style="background:rgba(59,130,246,0.05);border:1px solid rgba(59,130,246,0.2);
            border-radius:3px;padding:6px 10px;margin-bottom:6px;
            font-size:11px;color:#cfe1ff">
  {chip_text}
</div>""", unsafe_allow_html=True)

    # Map shows only events corroborated by ≥2 distinct news sources
    # (set by api_integrations.get_shipping_events). Single-source rumours
    # stay off the map and live only in the Intel Feed page.
    if "on_map" in filtered_events.columns:
        map_events = filtered_events[filtered_events["on_map"].fillna(False)]
    else:
        map_events = filtered_events
    globe_fig = create_dashboard_map(
        map_events,
        show_routes=show_routes,
        show_ports=show_ports,
        show_events=show_events,
        show_vessels=show_ves,
        show_daynight=show_dn,
        show_piracy=show_pir,
        route_statuses=route_statuses,
        port_congestion_df=port_cong_df if len(port_cong_df) > 0 else None,
        ais_df=ais_df,
        piracy_df=piracy_df,
    )
    # Trim margins so the map fills the column edge-to-edge with no padding.
    globe_fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=560,
    )
    # Note: don't call update_geos here — maps.py applies the Naval Command
    # palette (graphite land + near-black ocean + cyan coastlines + gold
    # borders + 15° graticule). Overriding bgcolor/landcolor/oceancolor here
    # silently undid that and surfaced the bright orange Disruption halos.
    # Show the standard Plotly toolbar (Pan / Zoom in / Zoom out / Reset)
    # so the user has familiar map controls. dragmode="pan" is set in
    # maps.py so click-drag pans rather than draws a zoom-box.
    st.plotly_chart(
        globe_fig,
        use_container_width=True,
        config={
            "scrollZoom": True,
            "displayModeBar": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": [
                "select2d", "lasso2d", "autoScale2d", "toImage",
                "hoverClosestGeo",
            ],
        },
    )

    # Port Congestion panel — rendered below the map inside the same left column.
    # Only ports with Score > 0 are shown in the main list; the expander below
    # holds the fully operational (Score == 0) ports for reference.
    ports_html = '<div class="tw-panel"><div class="tw-panel-title">Port Congestion</div>'
    ports_html += '<div style="color:#666;font-size:10px;padding:0 8px 6px">Showing only ports with active congestion</div>'
    active_ports_df = port_cong_df[port_cong_df["Score"] > 0] if len(port_cong_df) > 0 else port_cong_df
    if len(active_ports_df) > 0:
        for _, p in active_ports_df.sort_values("Score", ascending=False).iterrows():
            cc    = CONG_COL.get(p["Congestion"], "#666")
            score = int(p["Score"])
            conf  = p.get("Confidence", "Live AIS")
            # "News-only" means the score is derived from GDELT/ACLED signals alone;
            # no live AIS queue data has confirmed it yet, so we flag it visually.
            low_conf = conf == "News-only"
            name_color = "#888" if low_conf else "#e8e8e8"
            conf_badge = (
                '<span title="No live AIS yet — score from news/events only" '
                'style="font-size:9px;color:#888;margin-left:6px;'
                'border:1px solid #333;border-radius:2px;padding:0 4px">news</span>'
                if low_conf else ""
            )
            ports_html += f"""
<div style="display:flex;align-items:center;justify-content:space-between;
            padding:5px 8px;margin:2px 0;border-radius:3px;border-left:3px solid {cc};
            background:rgba(255,255,255,0.01)">
  <span style="font-size:11px;font-weight:600;color:{name_color}">{p['Port']}{conf_badge}</span>
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

    # Collapsed expander for fully operational ports (Score == 0) — kept separate
    # so they don't dilute the at-a-glance congestion list above.
    if len(port_cong_df) > 0:
        with st.expander("View All Ports", expanded=False):
            full_ports_html = ""
            for _, p in port_cong_df[port_cong_df["Score"] == 0].sort_values("Score", ascending=False).iterrows():
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

        # Maps a route status string to a plain-English one-line action recommendation
        # shown in the expanded detail card for each route row.
        def _brief_recommendation(s):
            if s == "Critical - Avoid":
                return "Avoid or compare alternative routing before dispatch."
            if s == "Operational - High Risk":
                return "Proceed only with monitoring and contingency planning."
            if s == "Operational - Alert":
                return "Monitor before final route confirmation."
            if s == "Unavailable":
                return "Data unavailable — manual review required."
            return "Proceed normally under current conditions."

        st.markdown("</div>", unsafe_allow_html=True)

        # Each route is rendered as a compact row with a toggle button (▼/▲) that
        # expands an inline detail card. State is stored in session_state keyed by
        # both index and route name to avoid conflicts when routes are reordered.
        for i, (_, row) in enumerate(shipping_df.sort_values("Risk Score", ascending=False).iterrows()):
            sc        = SC.get(row["Status"], "#666")
            sbg       = SBG.get(row["Status"], "transparent")
            score     = int(row["Risk Score"])
            rc        = risk_col(score)
            status    = row["Status"]
            # Strip the "Operational - " / "Critical - " prefix for the compact badge.
            label     = row["Status"].replace("Operational - ", "").replace("Critical - ", "")
            rec       = _brief_recommendation(status)
            route_key = f"route_toggle_{i}_{row['Route'].replace(' ', '_')}"
            is_open   = st.session_state.get(route_key, False)

            # Left border colour gives a quick traffic-light read of risk severity
            # without needing to read the numeric score.
            if score >= 75:
                border_col = "#ef4444"
            elif score >= 40:
                border_col = "#f97316"
            elif score >= 1:
                border_col = "#eab308"
            else:
                border_col = "#22c55e"

            info_col, btn_col = st.columns([11, 1])
            with info_col:
                st.markdown(f"""
<div style="border-left:3px solid {border_col};padding:6px 10px;margin:2px 0;
            background:rgba(255,255,255,0.02);border-radius:0 3px 3px 0;
            display:flex;align-items:center;gap:8px">
  <span style="font-size:11px;font-weight:600;color:#e8e8e8;flex:2;min-width:0;
               overflow:hidden;white-space:nowrap;text-overflow:ellipsis">{row['Route']}</span>
  <span style="font-size:9px;color:{rc};font-weight:700;white-space:nowrap">{score}/100</span>
  <span class="tw-badge" style="background:{sbg};color:{sc};border:1px solid {sc}44;
        font-size:9px;white-space:nowrap">{label}</span>
  <span style="font-size:9px;color:#555;white-space:nowrap">{row['Nearby Events']} ev · {row['News Signals']} sig</span>
</div>""", unsafe_allow_html=True)
            with btn_col:
                if st.button("▲" if is_open else "▼", key=f"btn_{i}_{row['Route'].replace(' ', '_')}",
                             use_container_width=True):
                    st.session_state[route_key] = not is_open

            if is_open:
                st.markdown(f"""
<div style="background:rgba(15,15,25,0.8);border:1px solid #1e1e2e;border-radius:3px;
            padding:10px 12px;margin-bottom:6px">
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;margin-bottom:10px">
    <div>
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.3px">Operational Risk</div>
      <div style="font-size:16px;font-weight:700;color:{rc}">{score}<span style="font-size:10px;color:#555">/100</span></div>
    </div>
    <div>
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.3px">Expected Delay</div>
      <div style="font-size:13px;font-weight:600;color:#c8d6e5">{row['Average Delay']}</div>
    </div>
    <div>
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.3px">Estimated Cost Impact</div>
      <div style="font-size:13px;font-weight:600;color:#c8d6e5">{row['Cost Impact']}</div>
    </div>
    <div>
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.3px">Nearby Incidents</div>
      <div style="font-size:13px;font-weight:600;color:#c8d6e5">{row['Nearby Events']}</div>
    </div>
    <div style="grid-column:1/-1">
      <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.3px">Disruption Signals</div>
      <div style="font-size:13px;font-weight:600;color:#c8d6e5">{row['News Signals']} news signals</div>
    </div>
  </div>
  <div style="background:rgba(59,130,246,0.06);border:1px solid rgba(59,130,246,0.2);
              border-radius:3px;padding:8px 10px;">
    <div style="font-size:9px;color:#3b82f6;font-weight:700;text-transform:uppercase;
                letter-spacing:0.3px;margin-bottom:3px">Recommendation</div>
    <div style="font-size:11px;color:#c8d6e5;line-height:1.5">{rec}</div>
  </div>
</div>""", unsafe_allow_html=True)

    # ── Live Events (top 5) ───────────────────────────────────────────────────
    # Shows the 5 most recent events from the filtered set as compact alert cards.
    # The full event list is on the Intel Feed page; this panel is a quick-glance
    # summary of what's happening right now. IMPACT_COL and IMPACT_ICON map the
    # severity string to a colour and emoji for the badge on each card.
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
            # Truncate description to 60 characters to keep cards compact.
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

# ── Data freshness strip ──────────────────────────────────────────────────────
# Renders a single horizontal bar at the bottom of the page showing the
# real-time health of every data source: AIS stream age, latest event date,
# NGA warnings recency, and the current oil/freight index values. Each source
# gets a green/amber/red dot so operators can immediately spot a stale feed.
def _freshness_strip():
    import sqlite3, time
    from datetime import datetime, timezone
    from pathlib import Path

    parts = []

    # AIS: query the local SQLite positions database to find how long ago the
    # last vessel sighting arrived. Green = <5 min, amber = <30 min, red = stale.
    try:
        db = Path(__file__).resolve().parent / ".ais_positions.db"
        if db.exists():
            with sqlite3.connect(db) as con:
                last = con.execute("SELECT MAX(ts) FROM positions").fetchone()[0] or 0
            age = time.time() - last if last else None
            if age is not None and age < 300:
                parts.append(f"<span style='color:#22c55e'>● AIS streaming ({int(age)}s ago)</span>")
            elif age is not None and age < 1800:
                parts.append(f"<span style='color:#eab308'>● AIS lagging ({int(age/60)}m ago)</span>")
            else:
                parts.append("<span style='color:#ef4444'>● AIS stale/offline</span>")
        else:
            parts.append("<span style='color:#ef4444'>● AIS not yet started</span>")
    except Exception:
        parts.append("<span style='color:#ef4444'>● AIS check failed</span>")

    # Events: surface the most recent event date from the loaded DataFrame.
    if len(events_df) > 0 and "date" in events_df.columns:
        try:
            latest = pd.to_datetime(events_df["date"], errors="coerce").max()
            parts.append(f"<span style='color:#22c55e'>● Events {latest.strftime('%Y-%m-%d')}</span>")
        except Exception:
            parts.append("<span style='color:#eab308'>● Events: date parse failed</span>")
    else:
        parts.append("<span style='color:#ef4444'>● Events feed empty</span>")

    # NGA freshness — show latest msgYear
    # The NGA (National Geospatial-Intelligence Agency) publishes maritime warnings;
    # if the latest year is behind the current year the feed may be cached or broken.
    try:
        from nga_warnings import fetch_warnings
        nga = fetch_warnings()
        if len(nga) > 0 and "msgYear" in nga.columns:
            latest_y = int(pd.to_numeric(nga["msgYear"], errors="coerce").max())
            this_y = datetime.utcnow().year
            if latest_y >= this_y:
                parts.append(f"<span style='color:#22c55e'>● NGA current ({latest_y})</span>")
            elif latest_y >= this_y - 1:
                parts.append(f"<span style='color:#eab308'>● NGA latest {latest_y} (stale)</span>")
            else:
                parts.append(f"<span style='color:#ef4444'>● NGA archive only (latest {latest_y})</span>")
        else:
            parts.append("<span style='color:#ef4444'>● NGA empty</span>")
    except Exception:
        parts.append("<span style='color:#ef4444'>● NGA check failed</span>")

    # Oil + freight publish dates (FRED is weekday)
    # Shown as plain grey text because these are point-in-time values, not live streams.
    parts.append(f"<span style='color:#aaa'>WTI ${oil_price}</span>")
    parts.append(f"<span style='color:#aaa'>Freight Idx {shipping_index:.0f} (monthly)</span>")

    st.markdown(
        "<div style='padding:6px 10px;background:rgba(255,255,255,0.02);"
        "border:1px solid rgba(255,255,255,0.05);border-radius:3px;"
        "font-size:10px;display:flex;gap:14px;flex-wrap:wrap;margin-bottom:6px'>"
        "<span style='color:#666'>DATA FRESHNESS:</span> "
        + " · ".join(parts) +
        "</div>",
        unsafe_allow_html=True,
    )

_freshness_strip()

# ── Footer ────────────────────────────────────────────────────────────────────
render_footer()

# ── Settings (collapsed) ──────────────────────────────────────────────────────
# Collapsed by default so it doesn't distract from the map. Contains the
# auto-refresh interval picker (writes to session_state, picked up by
# st_autorefresh above on the next rerun), event filtering controls that feed
# into filter_events(), and a CSV export of the currently filtered event set.
from config import EVENT_TYPES
with st.expander("⚙ Settings & Filters", expanded=False):
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.selectbox("Auto-refresh", [5, 10, 15, 30], index=1,
                     format_func=lambda x: f"Every {x} min", key="refresh_interval")
        # Force Refresh clears all cached data so the next rerun hits the APIs
        # fresh, regardless of whether the cache TTL has elapsed.
        if st.button("Force Refresh"):
            st.cache_data.clear()
            st.rerun()
    with s2:
        st.selectbox("Event Type", ["All Types"] + list(EVENT_TYPES.keys()), key="event_type")
    with s3:
        st.selectbox("Impact Level", ["All Levels", "Critical", "High", "Medium", "Low"], key="impact")
    with s4:
        st.text_input("Search", placeholder="location or keyword…", key="search")
        # Export applies the current filter state so the downloaded CSV matches
        # exactly what the user sees on screen.
        if st.button("Export CSV"):
            fe = filter_events(events_df,
                               st.session_state.get("event_type", "All Types"),
                               st.session_state.get("impact", "All Levels"),
                               st.session_state.get("search", ""))
            st.download_button("⬇ Download",
                               data=fe.to_csv(index=False),
                               file_name=f"events_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv",
                               mime="text/csv")
