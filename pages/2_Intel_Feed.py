# =============================================================================
# 2_Intel_Feed.py — THE "INTEL FEED" PAGE (news + warnings + threat watch)
# =============================================================================
# This page is the "news desk" of our project. It pulls together everything
# that is happening RIGHT NOW around the world that could affect shipping —
# from official maritime warnings, to recent conflict events, to general
# news articles — and presents it as one scannable feed.
#
# Where the data on this page comes from:
#   - load_core_data()           -> our cached loader; returns events + market data.
#   - compute_shipping_status()  -> 0-100 risk score for each shipping route.
#   - compute_risk_summary()     -> risk grade per region of the world.
#   - get_news_feed()            -> live news (Guardian API + NewsAPI),
#                                   tagged by topic (conflict / shipping /
#                                   trade / weather / other).
#   - fetch_nga_warnings()       -> official US National Geospatial-Intelligence
#                                   Agency maritime safety warnings.
#   - cluster_news_by_region()   -> groups news articles by maritime region
#                                   (Suez / Hormuz / Malacca / etc.) so the
#                                   feed is organised, not a flat list.
#
# Layout: left column = regional risk table + NGA warnings + recommended
# actions + multi-source threat watch + event-type chart. Right column =
# the live news feed with topic filter buttons.
# =============================================================================

# Streamlit = our web app framework.
import streamlit as st
# pandas = tables / data manipulation.
import pandas as pd
# plotly.express = quick charting library used here for the event-type bar chart.
import plotly.express as px

# Our own project modules:
#   - RiskAnalytics              : KPI numbers (critical / high / total events)
#                                  and regional alerts.
#   - filter_events              : drops irrelevant / old events.
#   - generate_intel_brief       : turns the day's data into the short
#                                  bulleted "Intelligence Brief" at the top.
#   - compute_shipping_status,   : live risk-scoring functions (see CLAUDE.md
#     compute_risk_summary,        for the exact formulas).
#     get_news_feed,
#     cluster_news_by_region.
#   - fetch_nga_warnings         : downloads the official NGA maritime
#                                  warnings RSS feed.
#   - load_core_data             : cached events + market data loader.
#   - ui_helpers                 : shared header / nav / footer + topic
#                                  colours + the cute "lottie" loading spinner.
from analytics import RiskAnalytics
from components import filter_events, generate_intel_brief
from dynamic_status import (
    compute_shipping_status, compute_risk_summary, get_news_feed,
    cluster_news_by_region,
)
from nga_warnings import fetch_warnings as fetch_nga_warnings
from data_loader import load_core_data
from ui_helpers import (
    inject_css, render_header, render_nav, render_footer,
    TOPIC_COLOR, TOPIC_ICON, lottie_loader,
)

st.set_page_config(
    page_title="TradeWatch — Intel Feed",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

# ── Data ──────────────────────────────────────────────────────────────────────
# lottie_loader() is a context manager that shows a nice animated loading
# spinner while the slow data-loading inside the `with` block is running.
with lottie_loader():
    # Get the shared core data (events + oil + freight index + currencies).
    events_df, oil_price, shipping_index, exchange_rates = load_core_data()
    # Convert the events table to a JSON string — required for cache keys
    # because Streamlit's @st.cache_data can't hash DataFrames directly.
    events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()
    # Compute the route risk table (5 rows, one per shipping route).
    shipping_df  = compute_shipping_status(events_json)
    # Compute the regional risk table (rows per region of the world).
    risk_df      = compute_risk_summary(events_json)
    # Fetch the live news feed (Guardian + NewsAPI, tagged by topic).
    news_feed_df = get_news_feed()

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
# INTEL FEED
# ══════════════════════════════════════════════════════════════════════════════

# ── Intelligence Brief ───────────────────────────────────────────────────────
# generate_intel_brief() looks at the current data and writes a short list
# of bullet points like "Suez at HIGH risk · 12 articles in last 24h" —
# essentially an auto-generated executive summary of the day. The block
# below splits each bullet into a label and a detail and styles them.
brief_lines = generate_intel_brief(filtered_events, news_feed_df, shipping_df)
if brief_lines:
    brief_html = ""
    for ln in brief_lines:
        clean_ln = ln.replace("**", "")
        if ":" in clean_ln:
            label, detail = clean_ln.split(":", 1)
            brief_html += (
                f'<div class="tw-brief-line">'
                f'<span class="tw-brief-label">{label}:</span>'
                f'<span class="tw-brief-detail">{detail}</span>'
                f'</div>'
            )
        else:
            brief_html += f'<div class="tw-brief-line tw-brief-detail">{clean_ln}</div>'
    st.markdown(
        f'<div class="tw-brief">'
        f'<div style="font-size:9px;font-weight:700;color:#3b82f6;text-transform:uppercase;'
        f'letter-spacing:0.5px;margin-bottom:6px">Intelligence Brief</div>'
        f'{brief_html}</div>',
        unsafe_allow_html=True,
    )

# Split the body of the page into two equal columns:
#   left  = risk tables, NGA warnings, recommended actions, threat watch, charts
#   right = the live news feed grouped by region
feed_left, feed_right = st.columns([1, 1], gap="large")

with feed_left:
    # ── Regional Risk Assessment table ─────────────────────────────────
    # Same regional risk data shown on the Route Planner page, repeated
    # here because intel analysts usually want it next to the news.
    st.markdown('<div class="tw-label">Regional Risk Assessment</div>', unsafe_allow_html=True)
    if len(risk_df) > 0:
        rows = ""
        for _, row in risk_df.iterrows():
            rc_ = {"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"}.get(row["Risk Level"], "#666")
            rows += f"""<tr>
<td style="padding:7px 8px;color:#e8e8e8">{row['Region']}</td>
<td style="padding:7px 8px"><span class="tw-badge" style="background:{rc_}18;color:{rc_};border:1px solid {rc_}33">{row['Risk Level']}</span></td>
<td style="padding:7px 8px;text-align:center;color:#888">{row['Active Events']}</td>
</tr>"""
        st.markdown(f"""
<table class="tw-table">
<thead><tr><th>Region</th><th>Risk</th><th>Events</th></tr></thead>
<tbody>{rows}</tbody>
</table>""", unsafe_allow_html=True)

    # ── NGA Maritime Safety Warnings ──────────────────────────────────────────
    # The NGA (US National Geospatial-Intelligence Agency) publishes
    # official maritime hazard warnings — piracy zones, ongoing naval
    # exercises, missile danger areas, drifting hulks, etc. We fetch them
    # live from the NGA feed (see nga_warnings.py). The try/except is a
    # safety net so the page still renders if NGA's server is down.
    try:
        nga_df = fetch_nga_warnings()
    except Exception:  # noqa: BLE001
        nga_df = pd.DataFrame()
    if len(nga_df) > 0:
        # Only show warnings with a severity score of at least 0.55 (i.e.
        # the genuinely important ones), sorted with the worst first.
        active = nga_df[nga_df["severity"] >= 0.55].sort_values("severity", ascending=False)
        if len(active) > 0:
            st.markdown('<div class="tw-label" style="margin-top:12px">Maritime Safety Warnings (NGA)</div>',
                        unsafe_allow_html=True)
            for _, w in active.head(6).iterrows():
                sev = float(w.get("severity", 0.0) or 0.0)
                color = ("#ef4444" if sev >= 0.85 else
                         "#f97316" if sev >= 0.70 else
                         "#eab308")
                text = (w.get("text") or "").strip().replace("\n", " ")
                snippet = (text[:140] + "…") if len(text) > 140 else text
                navarea = w.get("navArea", "") or "—"
                year = w.get("msgYear", "") or ""
                st.markdown(f"""
<div style="border-left:3px solid {color};padding:6px 10px;margin:4px 0;
            background:rgba(255,255,255,0.02);border-radius:0 3px 3px 0">
  <div style="display:flex;justify-content:space-between;font-size:9px;color:#666;margin-bottom:2px">
    <span>NAVAREA {navarea} · {year}</span>
    <span style="color:{color};font-weight:700">SEV {sev:.2f}</span>
  </div>
  <div style="font-size:11px;color:#ccc;line-height:1.4">{snippet}</div>
</div>""", unsafe_allow_html=True)

    # ── Recommended Actions ───────────────────────────────────────────
    # Looks at the events from the last 48 hours and suggests concrete
    # actions like "consider diverting traffic from Bab-el-Mandeb" — these
    # are simple rule-based recommendations, not AI-generated, so they're
    # predictable and defensible to a non-technical audience.
    alerts = RiskAnalytics.get_regional_alerts(filtered_events, threshold_hours=48)
    if alerts:
        st.markdown('<div class="tw-label" style="margin-top:12px">Recommended Actions</div>',
                    unsafe_allow_html=True)
        for alert in alerts[:5]:
            act = alert.get("action", "")
            loc = alert.get("location", "")
            imp = alert.get("impact", "")
            ac  = {"Critical":"#ef4444","High":"#f97316","Medium":"#eab308","Low":"#22c55e"}.get(imp, "#666")
            if act:
                st.markdown(f"""
<div style="border-left:2px solid {ac};padding:5px 10px;margin:3px 0;
            background:rgba(255,255,255,0.01);border-radius:0 3px 3px 0;font-size:11px">
  <span style="color:{ac};font-weight:600">{loc}</span>
  <span style="color:#888"> — {act}</span>
</div>""", unsafe_allow_html=True)

    # ── Multi-source Threat Watch ────────────────────────────────────────────
    # This section is our "trust filter" for events. We only show events
    # that have been reported by at least 2 different news websites
    # (the "on_map" flag is set elsewhere when n_sources >= 2). This way
    # we avoid alerting on a single rumour. Each row links out to the
    # actual article so a user can click through and read the source.
    if "on_map" in filtered_events.columns:
        on_map_events = (
            filtered_events[filtered_events["on_map"].fillna(False)]
            .sort_values("date", ascending=False)
        )
    else:
        on_map_events = filtered_events.iloc[0:0]
    if len(on_map_events) > 0:
        st.markdown(
            '<div class="tw-label" style="margin-top:12px">🗺 Multi-source Threat Watch</div>',
            unsafe_allow_html=True,
        )
        for _, ev in on_map_events.head(8).iterrows():
            ev_imp = ev.get("impact", "")
            ev_col = {"Critical": "#ef4444", "High": "#f97316",
                      "Medium":   "#eab308", "Low":  "#22c55e"}.get(ev_imp, "#666")
            ev_loc = ev.get("location", "—")
            ev_n   = int(ev.get("n_sources", 0) or 0)
            ev_url = (ev.get("url") or "").strip()
            ev_desc = str(ev.get("description") or "")[:120]
            try:
                ev_ts = pd.Timestamp(ev["date"]).strftime("%b %d %H:%M")
            except Exception:  # noqa: BLE001
                ev_ts = ""
            link_html = (
                f'<a href="{ev_url}" target="_blank" '
                f'style="color:#7cd1ff;text-decoration:none">read article →</a>'
                if ev_url else ""
            )
            st.markdown(f"""
<div style="border-left:3px solid {ev_col};padding:6px 10px;margin:4px 0;
            background:rgba(255,255,255,0.02);border-radius:0 3px 3px 0">
  <div style="display:flex;justify-content:space-between;
              font-size:9px;color:#888;margin-bottom:2px">
    <span><b style="color:{ev_col}">{ev_imp}</b> · 📍 {ev_loc} · {ev_ts}</span>
    <span style="background:rgba(124,209,255,0.10);color:#7cd1ff;
                 padding:1px 6px;border-radius:3px">🗺 {ev_n} sources</span>
  </div>
  <div style="font-size:11px;color:#ccc;line-height:1.4">{ev_desc}</div>
  <div style="font-size:10px;margin-top:3px">{link_html}</div>
</div>""", unsafe_allow_html=True)

    # ── Event Breakdown chart ─────────────────────────────────────────
    # A small bar chart at the bottom of the left column counting events
    # by category (Conflict, Shipping, Weather, …). Helps the user see
    # at a glance what kind of disruptions dominate right now.
    st.markdown('<div class="tw-label" style="margin-top:14px">Event Breakdown</div>',
                unsafe_allow_html=True)
    if len(filtered_events) > 0:
        # value_counts() = pandas built-in that tallies how many rows
        # fall into each unique value of the "type" column.
        ec = filtered_events["type"].value_counts()
        fig_ec = px.bar(x=ec.index, y=ec.values,
                        color=ec.values, color_continuous_scale=["#222", "#ef4444"])
        fig_ec.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#111", font_color="#666", height=160,
            margin=dict(t=4, b=0, l=0, r=0),
            xaxis=dict(tickangle=-30, tickfont_size=9, tickcolor="#444", linecolor="#2a2a2a"),
            yaxis=dict(gridcolor="#1a1a1a", tickfont_size=9),
            showlegend=False, coloraxis_showscale=False,
        )
        st.plotly_chart(fig_ec, use_container_width=True, config={"displayModeBar": False})

with feed_right:
    # ── Live news feed (right column) ──────────────────────────────────
    # The right half of the page is a scrolling list of every article we
    # have pulled in from Guardian + NewsAPI, grouped by maritime region.
    st.markdown('<div class="tw-label">Live Intelligence Feed</div>', unsafe_allow_html=True)

    # st.session_state is Streamlit's per-user, per-tab memory. We use it
    # to remember which topic filter (All / conflict / shipping / ...) the
    # user currently has selected, even when the page reruns.
    active_topic = st.session_state.get("news_topic_filter", "All")
    # Row of 6 little filter buttons spanning the column.
    tp_cols = st.columns(6)
    for tc, t in zip(tp_cols, ["All", "conflict", "shipping", "trade", "weather", "other"]):
        # Each button changes the saved filter and triggers a page rerun.
        lbl = "OTHER" if t == "other" else ("ALL" if t == "All" else t[:4].upper())
        if tc.button(lbl, key=f"tp_{t}",
                     type="primary" if active_topic == t else "secondary",
                     use_container_width=True):
            st.session_state["news_topic_filter"] = t
            st.rerun()

    active_topic = st.session_state.get("news_topic_filter", "All")
    disp = news_feed_df if active_topic == "All" else news_feed_df[news_feed_df["topic"] == active_topic]
    sources_n = disp["source"].nunique() if len(disp) > 0 else 0
    st.markdown(
        f'<div style="font-size:9px;color:#555;margin-bottom:6px">'
        f'{len(disp)} articles · {sources_n} sources</div>',
        unsafe_allow_html=True,
    )

    # Helper that turns one row of the news DataFrame (one article) into
    # the HTML we want to show: topic icon, timestamp, source, title link.
    def _render_article(art) -> str:
        topic  = art.get("topic", "other")
        tc_    = TOPIC_COLOR.get(topic, "#666")
        icon   = TOPIC_ICON.get(topic, "📰")
        try:   ts = pd.Timestamp(art["date"]).strftime("%b %d %H:%M")
        except: ts = ""
        title_full = str(art.get("title", ""))
        title  = title_full[:90] + ("…" if len(title_full) > 90 else "")
        source = str(art.get("source", ""))[:20]
        url    = str(art.get("url", "#"))
        return (
            f'<div class="tw-news" style="border-left-color:{tc_}">'
            f'<div style="color:#555;font-size:9px;margin-bottom:2px">'
            f'{icon} {ts} · {source}</div>'
            f'<a href="{url}" target="_blank" '
            f'style="color:#ccc;text-decoration:none;font-size:11px;line-height:1.4">'
            f'{title}</a></div>'
        )

    if len(disp) > 0:
        # cluster_news_by_region looks at each article's text and figures
        # out which maritime region it belongs to (Suez / Hormuz / Malacca
        # / Panama / Bosphorus / English Channel / Other). The result is
        # a dict { region_name: dataframe_of_articles }.
        regions = cluster_news_by_region(disp)
        # Build the HTML as one big string: each region becomes a <details>
        # element (a native HTML expand/collapse panel) with the article
        # cards inside. Regions with ≥3 articles open automatically.
        sections_html = ""
        for region, region_df in regions.items():
            count = len(region_df)
            mode_topic = region_df["topic"].mode() if count else None
            top_topic = mode_topic.iat[0] if mode_topic is not None and len(mode_topic) else "other"
            top_color = TOPIC_COLOR.get(top_topic, "#666")
            articles_html = "".join(_render_article(r) for _, r in region_df.head(20).iterrows())
            sections_html += (
                f'<details {"open" if count >= 3 else ""} '
                f'style="margin-bottom:8px;border:1px solid #1a1a1a;border-radius:3px;'
                f'background:rgba(255,255,255,0.01)">'
                f'<summary style="cursor:pointer;padding:6px 10px;font-size:11px;'
                f'font-weight:700;color:#e8e8e8;display:flex;justify-content:space-between;'
                f'align-items:center;list-style:none">'
                f'<span>{region}</span>'
                f'<span style="display:flex;gap:6px;align-items:center">'
                f'<span class="tw-badge" style="background:{top_color}18;color:{top_color};'
                f'border:1px solid {top_color}33;font-size:9px">{top_topic}</span>'
                f'<span style="color:#666;font-size:9px">{count}</span>'
                f'</span></summary>'
                f'<div style="padding:4px 6px 8px 6px">{articles_html}</div>'
                f'</details>'
            )
        st.markdown(
            f'<div style="height:600px;overflow-y:auto;padding-right:4px">{sections_html}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No articles loaded.")

# Shared footer (copyright + disclaimer) — same on every page.
render_footer()
