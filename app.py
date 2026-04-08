"""Global Events Dashboard — War Room Edition"""

import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

from config import EVENT_TYPES
from sample_data import get_events_data
from api_integrations import APIClient
from analytics import RiskAnalytics
from maps import create_dashboard_map
from components import render_event_list, filter_events
from dynamic_status import (
    compute_shipping_status,
    compute_risk_summary,
    compute_port_congestion,
    get_news_feed,
)
from api_config import CACHE_TTL_EVENTS

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Global Logistics War Room",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS — dark war room aesthetic ─────────────────────────────────────────────
st.markdown("""
<style>
/* Dark background throughout */
.stApp { background-color: #000510; }
section[data-testid="stSidebar"] { background-color: #020d1f; }
.stTabs [data-baseweb="tab-panel"] { background-color: #000510; }

/* Text */
.stMarkdown, .stText, p, h1, h2, h3, label { color: #d0e8ff !important; }

/* Metric cards */
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, #0a1a3a 0%, #0d2244 100%);
    border: 1px solid #1a3a6c;
    border-radius: 8px;
    padding: 12px;
}

/* News feed container */
.news-card {
    border-radius: 6px;
    padding: 8px 10px;
    margin: 3px 0;
    border-left: 3px solid rgba(255,255,255,0.25);
}
.news-card a { text-decoration: none; }
.news-card a:hover { text-decoration: underline; }

/* Tab styling */
.stTabs [data-baseweb="tab"] {
    background-color: #020d1f;
    color: #7ab0e0;
    border-bottom: 2px solid #1a3a6c;
}
.stTabs [aria-selected="true"] {
    border-bottom: 2px solid #4a9eff !important;
    color: #ffffff !important;
}

/* Expander */
div[data-testid="stExpander"] {
    background-color: #040e22;
    border: 1px solid #1a3a6c;
    border-radius: 6px;
}

/* Dataframe */
.stDataFrame { background-color: #040e22; }

/* Divider */
hr { border-color: #1a3a6c; }

/* Alert / status banners */
div[data-testid="stAlert"] { border-radius: 6px; }
</style>
""", unsafe_allow_html=True)


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=CACHE_TTL_EVENTS)
def _load_core_data():
    """Load base data: events, commodity prices, raw news."""
    events        = get_events_data()
    oil_price     = APIClient.get_oil_price()
    shipping_idx  = APIClient.get_shipping_index()
    exchange_rates = APIClient.get_exchange_rates()
    return events, oil_price, shipping_idx, exchange_rates


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.title("🔍 War Room Controls")
st.sidebar.write("---")

# Auto-refresh
st.sidebar.subheader("⏱ Auto-Refresh")
auto_interval = st.sidebar.selectbox(
    "Interval",
    options=[5, 10, 15, 30],
    index=1,
    format_func=lambda x: f"{x} minutes",
    key="refresh_interval",
)
count = st_autorefresh(interval=auto_interval * 60 * 1000, limit=None, key="war_room_refresh")
st.sidebar.caption(f"Refresh #{count} · every {auto_interval} min")

st.sidebar.write("---")

if st.sidebar.button("🔄 Force Refresh Now", key="refresh"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.write("---")

# ── Load all data ─────────────────────────────────────────────────────────────
with st.spinner("Loading intelligence feeds..."):
    events_df, oil_price, shipping_index, exchange_rates = _load_core_data()

# Serialize events_df once — used as cache key for compute functions
events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()

with st.spinner("Computing threat assessments..."):
    shipping_df  = compute_shipping_status(events_json)
    risk_df      = compute_risk_summary(events_json)
    port_cong_df = compute_port_congestion(events_json)
    news_feed_df = get_news_feed()

# ── Sidebar continued: API status & market data ───────────────────────────────
st.sidebar.subheader("📡 Data Sources")
if len(events_df) > 0:
    st.sidebar.success(f"✅ Events: {len(events_df)} loaded")
else:
    st.sidebar.warning("⚠️ Events: Using sample data")

if len(news_feed_df) > 0:
    st.sidebar.success(f"✅ News: {len(news_feed_df)} articles")
else:
    st.sidebar.info("📰 News APIs not returning data")

st.sidebar.write("---")
st.sidebar.subheader("📊 Market Indicators")
if oil_price:
    st.sidebar.metric("🛢 WTI Crude", f"${oil_price:.2f}/bbl")
if shipping_index:
    st.sidebar.metric("⚓ Freight Index", f"{shipping_index:.0f}")
if exchange_rates:
    for ccy, rate in list(exchange_rates.items())[:3]:
        st.sidebar.metric(f"💱 USD/{ccy}", f"{rate:.4f}")

st.sidebar.write("---")

# ── Sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.subheader("🔎 Event Filters")
event_type_filter = st.sidebar.selectbox(
    "Event Type", ["All Types"] + list(EVENT_TYPES.keys()), key="event_type"
)
impact_filter = st.sidebar.selectbox(
    "Impact Level", ["All Levels", "Critical", "High", "Medium", "Low"], key="impact"
)
search_text = st.sidebar.text_input(
    "Search", placeholder="Location or description...", key="search"
)

filtered_events = filter_events(events_df, event_type_filter, impact_filter, search_text)

if st.sidebar.button("📥 Export Events (CSV)"):
    csv = filtered_events.to_csv(index=False)
    st.sidebar.download_button(
        label="Download CSV",
        data=csv,
        file_name=f"events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )


# ── Header ────────────────────────────────────────────────────────────────────
st.title("🌍 Global Logistics War Room")
st.caption(
    f"Real-time tracking · ACLED · GDELT · NewsAPI · Guardian · FRED · OpenWeather"
    f" · Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC"
)

# ── Analytics & alert banner ──────────────────────────────────────────────────
analytics = RiskAnalytics.get_summary_metrics(filtered_events, oil_price, shipping_index)

if "CRITICAL" in analytics["recommendation"]:
    st.error(f"🚨 {analytics['recommendation']}")
elif "HIGH RISK" in analytics["recommendation"]:
    st.warning(f"⚠️ {analytics['recommendation']}")
elif "ELEVATED" in analytics["recommendation"]:
    st.info(f"📍 {analytics['recommendation']}")
else:
    st.success(f"✅ {analytics['recommendation']}")

# ── KPI bar ───────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🚨 Critical Events", analytics["critical_events"])
c2.metric("⚠️ High Risk Events", analytics["high_events"])
c3.metric("📍 Total Events", analytics["total_events"])
c4.metric("⏰ Last 48h", analytics["events_last_48h"])
c5.metric("🌐 Worst Region", analytics["worst_affected_region"])

st.write("---")

# ═══════════════════════════════════════════════════════════════════════════════
# WAR ROOM — Globe (left) + Live Intelligence Feed (right)
# ═══════════════════════════════════════════════════════════════════════════════

globe_col, news_col = st.columns([2.5, 1], gap="medium")

with globe_col:
    st.subheader("🗺 Global Threat Map")
    st.caption(
        "Routes: 🟢 Operational · 🟡 Alert · 🟠 High Risk · 🔴 Critical  |  "
        "⬛ Port squares colored by congestion  |  🔴 Rings = critical threat zones"
    )

    route_statuses = {}
    if len(shipping_df) > 0:
        route_statuses = dict(zip(shipping_df["Route"], shipping_df["Status"]))

    globe_fig = create_dashboard_map(
        filtered_events,
        show_routes=True,
        route_statuses=route_statuses,
        port_congestion_df=port_cong_df if len(port_cong_df) > 0 else None,
    )
    st.plotly_chart(globe_fig, use_container_width=True)

with news_col:
    st.subheader("📡 Live Intel Feed")

    # Topic filter
    TOPIC_OPTIONS = ["All", "conflict", "shipping", "trade", "weather", "other"]
    topic_filter = st.selectbox(
        "Filter", TOPIC_OPTIONS,
        format_func=lambda x: x.title() if x != "All" else "All Topics",
        key="news_topic",
        label_visibility="collapsed",
    )

    if len(news_feed_df) > 0:
        display_news = (
            news_feed_df
            if topic_filter == "All"
            else news_feed_df[news_feed_df["topic"] == topic_filter]
        )
        st.caption(f"{len(display_news)} articles · 5-min refresh")
    else:
        display_news = pd.DataFrame()
        st.caption("No articles loaded")

    TOPIC_BG = {
        "conflict": "#3d0a0a",
        "shipping": "#0a1e3d",
        "weather":  "#0a2e14",
        "trade":    "#1e0a3d",
        "other":    "#0d1420",
    }
    TOPIC_ICON = {
        "conflict": "💥",
        "shipping": "🚢",
        "weather":  "⛈",
        "trade":    "📦",
        "other":    "📰",
    }
    TOPIC_BORDER = {
        "conflict": "#cc2222",
        "shipping": "#2266cc",
        "weather":  "#22aa44",
        "trade":    "#8844cc",
        "other":    "#446688",
    }

    # Scrollable container
    news_html = ""
    for _, art in display_news.head(40).iterrows():
        topic = art.get("topic", "other")
        bg     = TOPIC_BG.get(topic, "#0d1420")
        icon   = TOPIC_ICON.get(topic, "📰")
        border = TOPIC_BORDER.get(topic, "#446688")
        date   = art["date"]
        try:
            time_str = pd.Timestamp(date).strftime("%b %d %H:%M")
        except Exception:
            time_str = ""
        title  = str(art["title"])[:110] + ("…" if len(str(art["title"])) > 110 else "")
        source = str(art["source"])[:25]
        url    = str(art["url"])

        news_html += f"""
<div style="background:{bg};padding:8px 10px;border-radius:6px;margin:3px 0;
border-left:3px solid {border}">
  <div style="color:#8ab8e0;font-size:0.72em;margin-bottom:2px">
    {icon} {time_str} · {source}
  </div>
  <a href="{url}" target="_blank"
     style="color:#d0e8ff;text-decoration:none;font-size:0.82em;line-height:1.3">
    <b>{title}</b>
  </a>
</div>"""

    if news_html:
        st.markdown(
            f'<div style="height:680px;overflow-y:auto;padding-right:4px">{news_html}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No news articles match the current filter.")

st.write("---")

# ═══════════════════════════════════════════════════════════════════════════════
# SECONDARY TABS
# ═══════════════════════════════════════════════════════════════════════════════

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Events",
    "🚢 Shipping & Ports",
    "📈 Analytics",
    "💰 Impact",
])

# ── Tab 1: Events list ────────────────────────────────────────────────────────
with tab1:
    st.subheader("Active Events")

    if len(filtered_events) == 0:
        st.info("No events match your filters")
    else:
        st.caption(f"Showing {len(filtered_events)} event(s) — sorted newest first")
        render_event_list(filtered_events.sort_values("date", ascending=False))

# ── Tab 2: Shipping & Ports ───────────────────────────────────────────────────
with tab2:
    col_s, col_p = st.columns([1, 1], gap="large")

    with col_s:
        st.subheader("Chokepoint Status")
        st.caption("Derived from ACLED proximity + GDELT news signals · 15-min refresh")

        STATUS_EMOJI = {
            "Operational":              "🟢",
            "Operational - Alert":      "🟡",
            "Operational - High Risk":  "🟠",
            "Critical - Avoid":         "🔴",
        }

        if len(shipping_df) > 0:
            for _, row in shipping_df.iterrows():
                emoji = STATUS_EMOJI.get(row["Status"], "⚪")
                with st.expander(
                    f"{emoji} **{row['Route']}** — {row['Status']}  |  {row['Average Delay']}  |  {row['Cost Impact']}"
                ):
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric("Risk Score",    f"{row['Risk Score']}/100")
                    mc2.metric("Nearby Events", row["Nearby Events"])
                    mc3.metric("News Signals",  row["News Signals"])
        else:
            st.info("Computing route status...")

        st.write("---")
        st.subheader("Regional Risk")
        if len(risk_df) > 0:
            RISK_COLORS = {"Critical": "#8B0000", "High": "#FF4500", "Medium": "#FFA500", "Low": "#228B22"}
            def _risk_style(val):
                color = RISK_COLORS.get(val, "#333")
                return f"background-color: {color}; color: white; font-weight: bold; border-radius: 4px; padding: 2px 6px"
            st.dataframe(
                risk_df.style.applymap(_risk_style, subset=["Risk Level"]),
                use_container_width=True,
                hide_index=True,
            )

    with col_p:
        st.subheader("Port Congestion")
        st.caption("Derived from GDELT articles + ACLED events + OpenWeather · 15-min refresh")

        if len(port_cong_df) > 0:
            CONG_COLORS = {"Critical": "#FF2222", "High": "#FF8C00", "Medium": "#FFD700", "Low": "#00CC44"}

            # Bar chart
            fig_bar = px.bar(
                port_cong_df.sort_values("Score", ascending=False),
                x="Port", y="Score",
                color="Congestion",
                color_discrete_map=CONG_COLORS,
                title="Port Congestion Scores",
            )
            fig_bar.update_layout(
                paper_bgcolor="#000510",
                plot_bgcolor="#040e22",
                font_color="#d0e8ff",
                title_font_color="#d0e8ff",
                legend=dict(bgcolor="rgba(0,5,16,0.8)", font_color="#d0e8ff"),
                xaxis=dict(tickangle=-30),
                margin=dict(t=40, b=0),
                height=280,
            )
            st.plotly_chart(fig_bar, use_container_width=True)

            # Port detail expanders
            for _, p in port_cong_df.sort_values("Score", ascending=False).iterrows():
                cong = p["Congestion"]
                emoji = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}.get(cong, "⚪")
                with st.expander(f"{emoji} **{p['Port']}** — {cong} (Score: {p['Score']}/100)"):
                    pc1, pc2, pc3, pc4 = st.columns(4)
                    pc1.metric("Events",     p["ACLED Events"])
                    pc2.metric("News",       p["News Articles"])
                    pc3.metric("Weather",    p["Weather Alert"])
                    pc4.metric("Wind",       f"{p['Wind (m/s)']} m/s")
                    st.caption(f"Conditions: {p['Weather']}")
        else:
            st.info("Computing port congestion...")

# ── Tab 3: Analytics ──────────────────────────────────────────────────────────
with tab3:
    st.subheader("📈 Detailed Risk Analysis")

    col_a, col_b = st.columns(2)

    with col_a:
        st.write("**Event Type Distribution**")
        if len(filtered_events) > 0:
            event_counts = filtered_events["type"].value_counts()
            fig = px.bar(
                x=event_counts.index,
                y=event_counts.values,
                labels={"x": "Event Type", "y": "Count"},
                color=event_counts.values,
                color_continuous_scale="Reds",
            )
            fig.update_layout(
                paper_bgcolor="#000510", plot_bgcolor="#040e22",
                font_color="#d0e8ff", margin=dict(t=10),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data to display")

    with col_b:
        st.write("**Impact Level Distribution**")
        if len(filtered_events) > 0:
            impact_counts = filtered_events["impact"].value_counts()
            fig = px.pie(
                values=impact_counts.values,
                names=impact_counts.index,
                color_discrete_sequence=["#8B0000", "#FF4500", "#FFA500", "#FFD700"],
            )
            fig.update_layout(
                paper_bgcolor="#000510", font_color="#d0e8ff", margin=dict(t=10),
                legend=dict(bgcolor="rgba(0,5,16,0.8)"),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data to display")

    st.write("---")
    st.write("**Events Timeline (Last 30 Days)**")
    if len(filtered_events) > 0:
        daily_counts = (
            pd.DataFrame({"date": filtered_events["date"].dt.date, "events": 1})
            .groupby("date").sum().reset_index()
        )
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=daily_counts["date"],
            y=daily_counts["events"],
            fill="tozeroy",
            mode="lines+markers",
            line_color="#FF4500",
            name="Events",
        ))
        fig.update_layout(
            paper_bgcolor="#000510", plot_bgcolor="#040e22",
            font_color="#d0e8ff",
            xaxis_title="Date", yaxis_title="Events",
            hovermode="x unified", margin=dict(t=10),
        )
        st.plotly_chart(fig, use_container_width=True)

# ── Tab 4: Financial Impact ───────────────────────────────────────────────────
with tab4:
    st.subheader("💰 Business Impact Assessment")

    cost_impact = RiskAnalytics.calculate_cost_impact(filtered_events, oil_price, {})

    ic1, ic2, ic3 = st.columns(3)
    ic1.metric("Daily Cost Impact",  f"${cost_impact['daily_cost_increase_usd']:,.0f}",
               delta=f"${cost_impact['daily_cost_increase_usd']:,.0f}")
    ic2.metric("Monthly Projection", f"${cost_impact['monthly_cost_increase_usd']:,.0f}")
    ic3.metric("Affected Vessels ~", f"{cost_impact['affected_vessels']:.0f}")

    st.write("---")
    st.write("**Cost Impact Breakdown**")

    cost_data = pd.DataFrame({
        "Timeframe": ["Daily", "Weekly", "Monthly"],
        "Cost Increase (USD)": [
            cost_impact["daily_cost_increase_usd"],
            cost_impact["weekly_cost_increase_usd"],
            cost_impact["monthly_cost_increase_usd"],
        ],
    })
    fig = px.bar(
        cost_data, x="Timeframe", y="Cost Increase (USD)",
        color="Cost Increase (USD)", color_continuous_scale="Reds",
        text="Cost Increase (USD)",
    )
    fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside")
    fig.update_layout(
        paper_bgcolor="#000510", plot_bgcolor="#040e22",
        font_color="#d0e8ff", margin=dict(t=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.write("---")
    st.write("**Chokepoint Delay & Cost Impact**")
    if len(shipping_df) > 0:
        delay_display = shipping_df[["Route", "Average Delay", "Cost Impact", "Risk Score", "Status"]].copy()
        st.dataframe(delay_display, use_container_width=True, hide_index=True)
    else:
        st.info("Loading shipping status...")

    st.write("---")
    fc1, fc2 = st.columns(2)
    with fc1:
        st.write(f"🛢 Oil Price Multiplier: **{cost_impact['oil_multiplier']}x**")
        if oil_price:
            st.write(f"Current WTI: ${oil_price:.2f}/barrel")
    with fc2:
        st.write(f"⚠️ Event Risk Multiplier: **{cost_impact['event_risk_multiplier']}x**")
        st.write(f"Events affecting costs: {analytics['critical_events'] + analytics['high_events']}")


# ── Footer ────────────────────────────────────────────────────────────────────
st.write("---")
f1, f2, f3 = st.columns(3)
f1.caption(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC  |  Refresh #{count}  |  Auto: {auto_interval}min")
f2.caption("Data: ACLED · GDELT · NewsAPI · Guardian · FRED · NOAA · OpenWeather")
f3.caption("War Room v3.0 — Dynamic Intelligence Dashboard")
