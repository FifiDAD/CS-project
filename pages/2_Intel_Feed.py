"""TradeWatch — Intel Feed"""

import streamlit as st
import pandas as pd
import plotly.express as px

from analytics import RiskAnalytics
from components import filter_events, generate_intel_brief
from dynamic_status import compute_shipping_status, compute_risk_summary, get_news_feed
from data_loader import load_core_data
from ui_helpers import (
    inject_css, render_header, render_nav, render_footer,
    TOPIC_COLOR, TOPIC_ICON,
)

st.set_page_config(
    page_title="TradeWatch — Intel Feed",
    page_icon="📡",
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

# Intelligence brief
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

feed_left, feed_right = st.columns([1, 1], gap="large")

with feed_left:
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

    # Recommended actions
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

    st.markdown('<div class="tw-label" style="margin-top:14px">Event Breakdown</div>',
                unsafe_allow_html=True)
    if len(filtered_events) > 0:
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
    st.markdown('<div class="tw-label">Live Intelligence Feed</div>', unsafe_allow_html=True)

    active_topic = st.session_state.get("news_topic_filter", "All")
    tp_cols = st.columns(6)
    for tc, t in zip(tp_cols, ["All", "conflict", "shipping", "trade", "weather", "other"]):
        lbl = "ALL" if t == "All" else t[:4].upper()
        if tc.button(lbl, key=f"tp_{t}",
                     type="primary" if active_topic == t else "secondary",
                     use_container_width=True):
            st.session_state["news_topic_filter"] = t
            st.rerun()

    active_topic = st.session_state.get("news_topic_filter", "All")
    disp = news_feed_df if active_topic == "All" else news_feed_df[news_feed_df["topic"] == active_topic]
    st.markdown(f'<div style="font-size:9px;color:#555;margin-bottom:6px">{len(disp)} articles</div>',
                unsafe_allow_html=True)

    news_html = ""
    for _, art in disp.head(30).iterrows():
        topic  = art.get("topic", "other")
        tc_    = TOPIC_COLOR.get(topic, "#666")
        icon   = TOPIC_ICON.get(topic, "📰")
        try:   ts = pd.Timestamp(art["date"]).strftime("%b %d %H:%M")
        except: ts = ""
        title  = str(art["title"])[:90] + ("…" if len(str(art["title"])) > 90 else "")
        source = str(art["source"])[:20]
        url    = str(art["url"])
        news_html += f"""
<div class="tw-news" style="border-left-color:{tc_}">
  <div style="color:#555;font-size:9px;margin-bottom:2px">{icon} {ts} · {source}</div>
  <a href="{url}" target="_blank"
     style="color:#ccc;text-decoration:none;font-size:11px;line-height:1.4">
    {title}
  </a>
</div>"""

    if news_html:
        st.markdown(
            f'<div style="height:560px;overflow-y:auto;padding-right:4px">{news_html}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No articles loaded.")

render_footer()
