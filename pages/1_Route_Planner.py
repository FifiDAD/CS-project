# =============================================================================
# 1_Route_Planner.py — THE "ROUTE PLANNER" PAGE (chokepoint comparison view)
# =============================================================================
# This page is a comparison dashboard. Its job is to show the user, side by
# side, how the 5 major shipping routes of the world are currently doing
# (Suez, Hormuz, Malacca, Panama, English Channel) and let them ask
# "what if" questions like "what if Suez goes down?".
#
# Where the data comes from:
#   - load_core_data()       -> fetches live events + oil price + freight
#                               index + currency rates from our APIs.
#   - compute_shipping_status() / compute_risk_summary() / compute_port_congestion()
#     -> our own functions (in dynamic_status.py) that turn the raw events
#        into 0-100 risk scores per route, per region, and per port.
#
# This page does NOT do the actual route-finding maths — that lives on the
# MariNav Router page. This one is purely "look at the world right now and
# decide which lane you trust today".
# =============================================================================

# Streamlit = the web-app framework that paints the whole page.
import streamlit as st
# pandas = the "Excel in Python" library for tables of data.
import pandas as pd
# plotly.graph_objects = the charting library we use for the timeline chart.
import plotly.graph_objects as go

# Our own project modules (all live in the main CS-project folder):
#   - EVENT_TYPES: a constant dictionary of event categories (Conflict /
#                  Shipping / Weather / etc.) — used to populate a dropdown.
#   - RiskAnalytics: turns event data into KPIs (critical event counts etc.)
#   - filter_events: drops events older than 30 days or outside scope.
#   - render_comparison_table: draws the big route-vs-route HTML table.
#   - compute_shipping_status / _risk_summary / _port_congestion: live risk
#     scoring functions (see CLAUDE.md for the exact formulas).
#   - load_core_data: cached loader that pulls events + market data.
#   - inject_css + render_header + render_nav + render_footer: our shared
#     UI building blocks so every page has the same look.
from config import EVENT_TYPES
from analytics import RiskAnalytics
from components import filter_events, render_comparison_table
from dynamic_status import compute_shipping_status, compute_risk_summary, compute_port_congestion
from data_loader import load_core_data
from ui_helpers import inject_css, render_header, render_nav, render_footer, SC, risk_col

# Configure the browser tab — title, icon, wide layout, no sidebar by default.
st.set_page_config(
    page_title="TradeWatch — Route Planner",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Apply our shared site-wide styling (defined in ui_helpers.py).
inject_css()

# ── Data ──────────────────────────────────────────────────────────────────────
# load_core_data() does the heavy lifting: it calls our APIs (or hits the
# cache if the data is still fresh) and returns four things back:
#   1. events_df       — a pandas table of every recent event in the world
#                        (conflict, weather, shipping incidents, etc.)
#   2. oil_price       — current WTI crude oil price (USD/barrel) from FRED
#   3. shipping_index  — IMF maritime shipping index value
#   4. exchange_rates  — current FX rates dictionary
# We wrap the call in st.spinner so the user sees a small loading hint
# while it's running.
with st.spinner(""):
    events_df, oil_price, shipping_index, exchange_rates = load_core_data()

# Several of our downstream functions need the events data as a JSON STRING,
# not as a DataFrame. That's because Streamlit's @st.cache_data needs a
# "hashable" cache key — DataFrames aren't hashable but strings are. So we
# convert here once, and pass the string forward. (See CLAUDE.md for details.)
events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()

# Compute three live tables from the events data:
#   shipping_df  — risk score + delay + status for each of the 5 main routes
#   risk_df      — risk grade per region (Middle East / SE Asia / Europe …)
#   port_cong_df — congestion score for each major port
# These are the same numbers shown all over the dashboard.
with st.spinner(""):
    shipping_df  = compute_shipping_status(events_json)
    risk_df      = compute_risk_summary(events_json)
    port_cong_df = compute_port_congestion(events_json)

# analytics is a small dict of summary stats (critical events count, etc.)
# used by the top header bar of the page.
analytics       = RiskAnalytics.get_summary_metrics(events_df, oil_price, shipping_index)
# filtered_events drops events older than 30 days / off-topic, so the
# timeline chart further down only shows the recent stuff.
filtered_events = filter_events(events_df)

# Helper: the "Average Delay" column comes back as text like "6 hours" or
# "12+ hours" because it was built for display. To use it in maths we have
# to strip the words off and convert to a plain number.
def _parse_delay_h(s):
    try:    return float(str(s).replace(" hours", "").replace("+", "").strip())
    except: return 0.0

# Pick the "best route right now" and the "worst route status" so we can
# show them in the page header.
if len(shipping_df) > 0:
    # Convert delay text -> hours, then build a composite score that
    # weighs risk (0-100, normalised to 0-1) plus delay (hours / 48 so a
    # 2-day delay roughly equals max risk). Lowest score = best route.
    shipping_df["_delay_h"]   = shipping_df["Average Delay"].apply(_parse_delay_h)
    shipping_df["_composite"] = shipping_df["Risk Score"] / 100 + shipping_df["_delay_h"] / 48
    best_route   = shipping_df.loc[shipping_df["_composite"].idxmin(), "Route"]
    # Worst status = the status label of whichever route has the highest risk.
    worst_status = shipping_df.sort_values("Risk Score", ascending=False).iloc[0]["Status"]
else:
    # Defensive fallback if the data didn't load for some reason.
    best_route, worst_status = "N/A", "Operational"

# Pull the three KPI numbers out of the analytics dict so we can pass them
# into the header bar (critical / high / total events).
crit  = analytics.get("critical_events", 0)
high  = analytics.get("high_events", 0)
total = analytics.get("total_events", 0)

# ── Header + Nav ──────────────────────────────────────────────────────────────
# render_header draws the dark bar at the top of the page with the project
# logo and the three KPI numbers (critical / high / total events) plus the
# worst-route status indicator. render_nav draws the page navigation row
# just below it. Both are defined in ui_helpers.py and shared across pages.
render_header(crit, high, total, worst_status, 0)
render_nav()

# ══════════════════════════════════════════════════════════════════════════════
# ROUTE PLANNER LAYOUT
# ══════════════════════════════════════════════════════════════════════════════
# Split the page into a wide left column (75%) for the main content and a
# narrow right column (25%) for the "Plan a Voyage" sidebar callout box.
planner_left, planner_right = st.columns([3, 1], gap="large")

with planner_left:
    # Build the list of route names that will appear in the "simulate failure"
    # dropdown. If the data didn't load, fall back to an empty list.
    route_names = shipping_df["Route"].tolist() if len(shipping_df) > 0 else []

    # Top row: a wide dropdown for the "what-if" scenario picker on the left,
    # and a narrow event-type filter dropdown on the right.
    sc_col1, sc_col2 = st.columns([3, 1])
    with sc_col1:
        # The "simulate route failure" dropdown. The user picks a route here
        # and we then pretend it has failed, so they can see how the
        # comparison table looks under that scenario (great for what-ifs).
        scenario_route = st.selectbox(
            "SIMULATE ROUTE FAILURE →",
            ["None (live data)"] + route_names,
            key="scenario_route",
        )
    with sc_col2:
        # Event-type filter (Conflict / Shipping / Weather / etc.) — comes
        # from the EVENT_TYPES constant we imported above.
        st.selectbox("TYPE", ["All Types"] + list(EVENT_TYPES.keys()), key="event_type_tab")

    # scenario_overrides is the dictionary we'll pass into the table renderer
    # to force any route into a specific status for the simulation. Empty by
    # default — only filled in when the user picks a route to "fail".
    scenario_overrides = {}
    if scenario_route != "None (live data)":
        # Pretend the selected route is in a Critical status so the user can
        # see how the comparison table reacts.
        scenario_overrides[scenario_route] = "Critical - Avoid"
        st.markdown(f"""
<div style="background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.2);
            border-left:3px solid #ef4444;border-radius:3px;padding:6px 10px;margin-bottom:8px;
            font-size:11px;color:#ef4444">
  ⚠ SCENARIO ACTIVE — {scenario_route} overridden to CRITICAL · AVOID
</div>""", unsafe_allow_html=True)

    # Draw the big "Route Comparison Matrix" table — one row per major
    # shipping route, with risk score, status, delay, affected ports, etc.
    # This is the centrepiece of the page.
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

    # ── Regional Risk Summary table ────────────────────────────────────
    # A second smaller table grouped by world region (Middle East, SE Asia,
    # etc.) showing the overall risk grade, active event count, and the
    # number of shipping routes that are affected by what's happening there.
    st.markdown('<div class="tw-label" style="margin-top:16px">Regional Risk Summary</div>',
                unsafe_allow_html=True)
    if len(risk_df) > 0:
        # We build the table rows as a single HTML string for speed,
        # then drop it into Streamlit in one st.markdown call.
        rows = ""
        for _, row in risk_df.iterrows():
            # Pick the colour for the "risk level" badge based on its label.
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

    # ── Event Activity timeline chart ──────────────────────────────────
    # A small red area chart at the bottom of the page showing how many
    # events happened on each day in the last 30 days. Lets the user
    # spot spikes ("oh, there was a big day on May 3rd").
    st.markdown('<div class="tw-label" style="margin-top:16px">Event Activity — Last 30 Days</div>',
                unsafe_allow_html=True)
    if len(filtered_events) > 0:
        # Group all events by calendar date and count how many fell on each
        # day. The result is a 2-column table: date | n (count).
        daily = (pd.DataFrame({"date": filtered_events["date"].dt.date, "n": 1})
                 .groupby("date").sum().reset_index())
        # Build the Plotly chart: a line plus the area underneath shaded red.
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
    # ── Right column: "Plan a Voyage" callout ──────────────────────────
    # This is just a blue info box that tells the user "if you want the
    # real voyage planner with all the bells and whistles (vessel
    # physics, weather routing, Monte Carlo confidence intervals, CO2
    # emissions, bunker arbitrage), click here to jump to the MariNav
    # Router page". We moved all that heavy logic to its own page; this
    # page stays simple and focused on the chokepoint comparison.
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

# Draws the shared dark footer (copyright + small disclaimer) at the
# very bottom of every page. Defined once in ui_helpers.py.
render_footer()
