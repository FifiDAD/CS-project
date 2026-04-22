"""Global Events Dashboard - War Room Edition."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime

from analytics import RiskAnalytics
from api_config import CACHE_TTL_EVENTS
from api_integrations import APIClient
from components import filter_events, render_event_list
from config import EVENT_TYPES, MAJOR_SHIPPING_ROUTES
from dynamic_status import (
    compute_port_congestion,
    compute_risk_summary,
    compute_shipping_status,
    get_news_feed,
)
from maps import create_dashboard_map, render_interactive_globe
from sample_data import get_events_data
from streamlit_autorefresh import st_autorefresh


st.set_page_config(
    page_title="Global Logistics War Room",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "auto_refresh" not in st.session_state:
    st.session_state["auto_refresh"] = True
if "email_notifications" not in st.session_state:
    st.session_state["email_notifications"] = False

st.markdown(
    """
<style>
.stApp { background-color: #000510; }
section[data-testid="stSidebar"] { background-color: #020d1f; }
.stTabs [data-baseweb="tab-panel"] { background-color: #000510; }
.stMarkdown, .stText, p, h1, h2, h3, label { color: #d0e8ff !important; }
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, #0a1a3a 0%, #0d2244 100%);
    border: 1px solid #1a3a6c;
    border-radius: 8px;
    padding: 12px;
}
.stTabs [data-baseweb="tab"] {
    background-color: #020d1f;
    color: #7ab0e0;
    border-bottom: 2px solid #1a3a6c;
}
.stTabs [aria-selected="true"] {
    border-bottom: 2px solid #4a9eff !important;
    color: #ffffff !important;
}
div[data-testid="stExpander"] {
    background-color: #040e22;
    border: 1px solid #1a3a6c;
    border-radius: 6px;
}
.stDataFrame { background-color: #040e22; }
hr { border-color: #1a3a6c; }
div[data-testid="stAlert"] { border-radius: 6px; }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=CACHE_TTL_EVENTS)
def _load_core_data():
    """Load the base data needed across dashboard views."""
    events = get_events_data()
    oil_price = APIClient.get_oil_price()
    shipping_idx = APIClient.get_shipping_index()
    exchange_rates = APIClient.get_exchange_rates()
    return events, oil_price, shipping_idx, exchange_rates


st.sidebar.title("🔍 War Room Controls")
st.sidebar.write("---")

st.sidebar.subheader("⏱ Auto-Refresh")
st.session_state["auto_refresh"] = st.sidebar.toggle(
    "Enable auto-refresh",
    value=st.session_state.get("auto_refresh", True),
)
auto_interval = st.sidebar.selectbox(
    "Interval",
    options=[5, 10, 15, 30],
    index=1,
    format_func=lambda value: f"{value} minutes",
    key="refresh_interval",
)
count = st_autorefresh(
    interval=auto_interval * 60 * 1000 if st.session_state.get("auto_refresh", True) else 0,
    limit=None,
    key="war_room_refresh",
)
st.sidebar.caption(
    f"Refresh #{count} · every {auto_interval} min"
    if st.session_state.get("auto_refresh", True)
    else "Auto-refresh disabled"
)

st.sidebar.write("---")

if st.sidebar.button("🔄 Force Refresh Now", key="refresh"):
    st.cache_data.clear()
    st.rerun()

with st.spinner("Loading intelligence feeds..."):
    events_df, oil_price, shipping_index, exchange_rates = _load_core_data()

events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()

with st.spinner("Computing threat assessments..."):
    shipping_df = compute_shipping_status(events_json)
    risk_df = compute_risk_summary(events_json)
    port_cong_df = compute_port_congestion(events_json)
    news_feed_df = get_news_feed()

st.sidebar.write("---")
st.sidebar.subheader("📡 Data Sources")
if len(events_df) > 0:
    st.sidebar.success(f"✅ Events: {len(events_df)} loaded")
else:
    st.sidebar.warning("⚠️ Events: using sample data")

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
    for currency, rate in list(exchange_rates.items())[:3]:
        st.sidebar.metric(f"💱 USD/{currency}", f"{rate:.4f}")

st.sidebar.write("---")
st.sidebar.subheader("🔎 Event Filters")
event_type_filter = st.sidebar.selectbox(
    "Event Type",
    ["All Types"] + list(EVENT_TYPES.keys()),
    key="event_type",
)
impact_filter = st.sidebar.selectbox(
    "Impact Level",
    ["All Levels", "Critical", "High", "Medium", "Low"],
    key="impact",
)
search_text = st.sidebar.text_input(
    "Search",
    placeholder="Location or description...",
    key="search",
)

filtered_events = filter_events(events_df, event_type_filter, impact_filter, search_text)

st.sidebar.download_button(
    "📥 Export Events (CSV)",
    data=filtered_events.to_csv(index=False),
    file_name=f"events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    mime="text/csv",
)

with st.sidebar.expander("⚙️ Settings"):
    st.session_state["email_notifications"] = st.toggle(
        "Email notifications",
        value=st.session_state.get("email_notifications", False),
    )

st.title("🌍 Global Logistics War Room")
st.caption(
    "Real-time tracking · ACLED · GDELT · NewsAPI · Guardian · FRED · OpenWeather"
    f" · Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC"
)

analytics = RiskAnalytics.get_summary_metrics(filtered_events, oil_price, shipping_index)

if "CRITICAL" in analytics["recommendation"]:
    st.error(f"🚨 {analytics['recommendation']}")
elif "HIGH RISK" in analytics["recommendation"]:
    st.warning(f"⚠️ {analytics['recommendation']}")
elif "ELEVATED" in analytics["recommendation"]:
    st.info(f"📍 {analytics['recommendation']}")
else:
    st.success(f"✅ {analytics['recommendation']}")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🚨 Critical Events", analytics["critical_events"])
c2.metric("⚠️ High Risk Events", analytics["high_events"])
c3.metric("📍 Total Events", analytics["total_events"])
c4.metric("⏰ Last 48h", analytics["events_last_48h"])
c5.metric("🌐 Worst Region", analytics["worst_affected_region"])

st.write("---")

globe_col, news_col = st.columns([2.5, 1], gap="medium")

with globe_col:
    st.subheader("🗺 Global Threat Map")
    st.caption(
        "Routes: 🟢 Operational · 🟡 Alert · 🟠 High Risk · 🔴 Critical"
        " | Port squares show congestion | Rings mark critical threat zones"
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
    render_interactive_globe(globe_fig, height=750, latitude_limit=60, key="main-threat-map")

with news_col:
    st.subheader("📡 Live Intel Feed")

    topic_options = ["All", "conflict", "shipping", "trade", "weather", "other"]
    topic_filter = st.selectbox(
        "Filter",
        topic_options,
        format_func=lambda value: value.title() if value != "All" else "All Topics",
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

    topic_bg = {
        "conflict": "#3d0a0a",
        "shipping": "#0a1e3d",
        "weather": "#0a2e14",
        "trade": "#1e0a3d",
        "other": "#0d1420",
    }
    topic_icon = {
        "conflict": "💥",
        "shipping": "🚢",
        "weather": "⛈",
        "trade": "📦",
        "other": "📰",
    }
    topic_border = {
        "conflict": "#cc2222",
        "shipping": "#2266cc",
        "weather": "#22aa44",
        "trade": "#8844cc",
        "other": "#446688",
    }

    news_html = ""
    for _, article in display_news.head(40).iterrows():
        topic = article.get("topic", "other")
        bg = topic_bg.get(topic, "#0d1420")
        icon = topic_icon.get(topic, "📰")
        border = topic_border.get(topic, "#446688")
        date = article["date"]
        try:
            time_str = pd.Timestamp(date).strftime("%b %d %H:%M")
        except Exception:
            time_str = ""
        title = str(article["title"])[:110] + ("…" if len(str(article["title"])) > 110 else "")
        source = str(article["source"])[:25]
        url = str(article["url"])

        news_html += f"""
<div style="background:{bg};padding:8px 10px;border-radius:6px;margin:3px 0;border-left:3px solid {border}">
  <div style="color:#8ab8e0;font-size:0.72em;margin-bottom:2px">{icon} {time_str} · {source}</div>
  <a href="{url}" target="_blank" style="color:#d0e8ff;text-decoration:none;font-size:0.82em;line-height:1.3">
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

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "📋 Events",
        "🚢 Shipping & Ports",
        "📈 Analytics",
        "💰 Impact",
        "⛽ Fuel Calculator",
    ]
)

with tab1:
    st.subheader("Active Events")
    if len(filtered_events) == 0:
        st.info("No events match your filters.")
    else:
        st.caption(f"Showing {len(filtered_events)} event(s) - sorted newest first")
        render_event_list(filtered_events.sort_values("date", ascending=False))

with tab2:
    col_s, col_p = st.columns([1, 1], gap="large")

    with col_s:
        st.subheader("Chokepoint Status")
        st.caption("Derived from ACLED proximity and GDELT news signals.")

        status_emoji = {
            "Operational": "🟢",
            "Operational - Alert": "🟡",
            "Operational - High Risk": "🟠",
            "Critical - Avoid": "🔴",
        }

        if len(shipping_df) > 0:
            for _, row in shipping_df.iterrows():
                emoji = status_emoji.get(row["Status"], "⚪")
                with st.expander(
                    f"{emoji} **{row['Route']}** - {row['Status']} | {row['Average Delay']} | {row['Cost Impact']}"
                ):
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric("Risk Score", f"{row['Risk Score']}/100")
                    mc2.metric("Nearby Events", row["Nearby Events"])
                    mc3.metric("News Signals", row["News Signals"])
        else:
            st.info("Computing route status...")

        st.write("---")
        st.subheader("Regional Risk")
        if len(risk_df) > 0:
            risk_colors = {
                "Critical": "#8B0000",
                "High": "#FF4500",
                "Medium": "#FFA500",
                "Low": "#228B22",
            }

            def _risk_style(value):
                color = risk_colors.get(value, "#333")
                return f"background-color: {color}; color: white; font-weight: bold;"

            st.dataframe(
                risk_df.style.map(_risk_style, subset=["Risk Level"]),
                use_container_width=True,
                hide_index=True,
            )

    with col_p:
        st.subheader("Port Congestion")
        st.caption("Derived from GDELT, event proximity, and weather signals.")

        if len(port_cong_df) > 0:
            congestion_colors = {
                "Critical": "#FF2222",
                "High": "#FF8C00",
                "Medium": "#FFD700",
                "Low": "#00CC44",
            }

            fig_bar = px.bar(
                port_cong_df.sort_values("Score", ascending=False),
                x="Port",
                y="Score",
                color="Congestion",
                color_discrete_map=congestion_colors,
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

            for _, port in port_cong_df.sort_values("Score", ascending=False).iterrows():
                congestion = port["Congestion"]
                emoji = {
                    "Critical": "🔴",
                    "High": "🟠",
                    "Medium": "🟡",
                    "Low": "🟢",
                }.get(congestion, "⚪")
                with st.expander(
                    f"{emoji} **{port['Port']}** - {congestion} (Score: {port['Score']}/100)"
                ):
                    pc1, pc2, pc3, pc4 = st.columns(4)
                    pc1.metric("Events", port["ACLED Events"])
                    pc2.metric("News", port["News Articles"])
                    pc3.metric("Weather", port["Weather Alert"])
                    pc4.metric("Wind", f"{port['Wind (m/s)']} m/s")
                    st.caption(f"Conditions: {port['Weather']}")
        else:
            st.info("Computing port congestion...")

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
                paper_bgcolor="#000510",
                plot_bgcolor="#040e22",
                font_color="#d0e8ff",
                margin=dict(t=10),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data to display.")

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
                paper_bgcolor="#000510",
                font_color="#d0e8ff",
                margin=dict(t=10),
                legend=dict(bgcolor="rgba(0,5,16,0.8)"),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data to display.")

    st.write("---")
    st.write("**Events Timeline (Last 30 Days)**")
    if len(filtered_events) > 0:
        daily_counts = (
            pd.DataFrame({"date": filtered_events["date"].dt.date, "events": 1})
            .groupby("date")
            .sum()
            .reset_index()
        )
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=daily_counts["date"],
                y=daily_counts["events"],
                fill="tozeroy",
                mode="lines+markers",
                line_color="#FF4500",
                name="Events",
            )
        )
        fig.update_layout(
            paper_bgcolor="#000510",
            plot_bgcolor="#040e22",
            font_color="#d0e8ff",
            xaxis_title="Date",
            yaxis_title="Events",
            hovermode="x unified",
            margin=dict(t=10),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No timeline data to display.")

with tab4:
    st.subheader("💰 Business Impact Assessment")

    cost_impact = RiskAnalytics.calculate_cost_impact(filtered_events, oil_price, {})

    ic1, ic2, ic3 = st.columns(3)
    ic1.metric(
        "Daily Cost Impact",
        f"${cost_impact['daily_cost_increase_usd']:,.0f}",
        delta=f"${cost_impact['daily_cost_increase_usd']:,.0f}",
    )
    ic2.metric("Monthly Projection", f"${cost_impact['monthly_cost_increase_usd']:,.0f}")
    ic3.metric("Affected Vessels ~", f"{cost_impact['affected_vessels']:.0f}")

    st.write("---")
    st.write("**Cost Impact Breakdown**")

    cost_data = pd.DataFrame(
        {
            "Timeframe": ["Daily", "Weekly", "Monthly"],
            "Cost Increase (USD)": [
                cost_impact["daily_cost_increase_usd"],
                cost_impact["weekly_cost_increase_usd"],
                cost_impact["monthly_cost_increase_usd"],
            ],
        }
    )
    fig = px.bar(
        cost_data,
        x="Timeframe",
        y="Cost Increase (USD)",
        color="Cost Increase (USD)",
        color_continuous_scale="Reds",
        text="Cost Increase (USD)",
    )
    fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside")
    fig.update_layout(
        paper_bgcolor="#000510",
        plot_bgcolor="#040e22",
        font_color="#d0e8ff",
        margin=dict(t=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.write("---")
    st.write("**Chokepoint Delay and Cost Impact**")
    if len(shipping_df) > 0:
        delay_display = shipping_df[
            ["Route", "Average Delay", "Cost Impact", "Risk Score", "Status"]
        ].copy()
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

with tab5:
    st.subheader("⛽ Voyage Fuel Cost Estimator")
    st.caption("Estimate fuel cost from live WTI pricing and route risk surcharges.")

    wti = oil_price if oil_price else 78.45
    bunker_price_per_ton = wti * 6.35

    st.info(
        f"🛢 Live WTI Crude: **${wti:.2f}/bbl** -> "
        f"Estimated Bunker (HFO): **${bunker_price_per_ton:.0f}/ton**"
    )

    st.write("---")

    inp1, inp2 = st.columns(2, gap="large")

    with inp1:
        st.write("**Vessel Parameters**")

        vessel_preset = st.selectbox(
            "Vessel Type (preset)",
            options=[
                "Custom",
                "Small Feeder (600 TEU) - 18 t/day",
                "Medium Feeder (1,500 TEU) - 30 t/day",
                "Panamax (4,500 TEU) - 55 t/day",
                "Post-Panamax (8,000 TEU) - 80 t/day",
                "ULCS (20,000+ TEU) - 130 t/day",
                "Suezmax Tanker - 65 t/day",
                "VLCC Tanker - 90 t/day",
                "Capesize Bulk - 50 t/day",
            ],
            key="vessel_preset",
        )

        preset_consumption = {
            "Small Feeder (600 TEU) - 18 t/day": 18,
            "Medium Feeder (1,500 TEU) - 30 t/day": 30,
            "Panamax (4,500 TEU) - 55 t/day": 55,
            "Post-Panamax (8,000 TEU) - 80 t/day": 80,
            "ULCS (20,000+ TEU) - 130 t/day": 130,
            "Suezmax Tanker - 65 t/day": 65,
            "VLCC Tanker - 90 t/day": 90,
            "Capesize Bulk - 50 t/day": 50,
        }
        default_cons = preset_consumption.get(vessel_preset, 50)

        consumption = st.number_input(
            "Fuel Consumption (tons/day)",
            min_value=1.0,
            max_value=500.0,
            value=float(default_cons),
            step=1.0,
            key="consumption",
        )
        voyage_days = st.number_input(
            "Voyage Duration (days)",
            min_value=1,
            max_value=120,
            value=14,
            step=1,
            key="voyage_days",
        )

    with inp2:
        st.write("**Route and Risk**")

        route_options = ["No specific route"] + list(MAJOR_SHIPPING_ROUTES.keys())
        selected_route = st.selectbox("Shipping Route", options=route_options, key="calc_route")

        route_risk_surcharge = 0.0
        route_status_label = "N/A"
        if selected_route != "No specific route" and len(shipping_df) > 0:
            route_row = shipping_df[shipping_df["Route"] == selected_route]
            if len(route_row) > 0:
                risk_score = route_row.iloc[0]["Risk Score"]
                route_status_label = route_row.iloc[0]["Status"]
                cost_impact_str = route_row.iloc[0]["Cost Impact"]
                try:
                    route_risk_surcharge = float(
                        cost_impact_str.replace("%", "").replace("+", "")
                    ) / 100
                except Exception:
                    route_risk_surcharge = risk_score / 400

        speed_reduction = st.slider(
            "Speed Reduction due to conditions (%)",
            min_value=0,
            max_value=30,
            value=0,
            step=5,
            key="speed_reduction",
            help="Rough seas, heavy weather, or security routing can extend voyage time.",
        )
        cargo_value = st.number_input(
            "Cargo Value (USD, optional)",
            min_value=0,
            max_value=500_000_000,
            value=0,
            step=100_000,
            format="%d",
            key="cargo_value",
        )

    st.write("---")

    effective_days = voyage_days * (1 + speed_reduction / 100)
    total_fuel_tons = consumption * effective_days
    base_fuel_cost = total_fuel_tons * bunker_price_per_ton
    risk_surcharge_usd = base_fuel_cost * route_risk_surcharge
    total_cost = base_fuel_cost + risk_surcharge_usd

    insurance_estimate = 0.0
    if cargo_value > 0:
        base_insurance_pct = 0.001
        if route_risk_surcharge > 0.15:
            base_insurance_pct = 0.003
        elif route_risk_surcharge > 0.05:
            base_insurance_pct = 0.0015
        insurance_estimate = cargo_value * base_insurance_pct

    st.subheader("📊 Estimate Results")

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Total Fuel (tons)", f"{total_fuel_tons:,.0f} t")
    r2.metric("Base Fuel Cost", f"${base_fuel_cost:,.0f}")
    r3.metric(
        "Route Risk Surcharge",
        f"${risk_surcharge_usd:,.0f}",
        delta=f"+{route_risk_surcharge * 100:.0f}%" if route_risk_surcharge > 0 else "No surcharge",
        delta_color="inverse",
    )
    r4.metric("Total Estimated Cost", f"${total_cost:,.0f}")

    if cargo_value > 0:
        st.metric(
            "Insurance Estimate",
            f"${insurance_estimate:,.0f}",
            help="Rough estimate only. Confirm actual war-risk premiums with your broker.",
        )

    st.write("---")

    breakdown_items = {"Base Fuel": base_fuel_cost}
    if risk_surcharge_usd > 0:
        breakdown_items["Route Surcharge"] = risk_surcharge_usd
    if insurance_estimate > 0:
        breakdown_items["Insurance (est.)"] = insurance_estimate

    fig_breakdown = go.Figure(
        go.Bar(
            x=list(breakdown_items.keys()),
            y=list(breakdown_items.values()),
            marker_color=["#4a9eff", "#FF4500", "#FFD700"][: len(breakdown_items)],
            text=[f"${value:,.0f}" for value in breakdown_items.values()],
            textposition="outside",
            textfont=dict(color="#d0e8ff"),
        )
    )
    fig_breakdown.update_layout(
        paper_bgcolor="#000510",
        plot_bgcolor="#040e22",
        font_color="#d0e8ff",
        yaxis_title="USD",
        margin=dict(t=20, b=0),
        height=300,
        showlegend=False,
    )
    st.plotly_chart(fig_breakdown, use_container_width=True)

    if selected_route != "No specific route":
        st.write("---")
        st.write(f"**Route Context - {selected_route}**")
        rc1, rc2 = st.columns(2)
        with rc1:
            st.write(f"Status: **{route_status_label}**")
            st.write(f"Cost surcharge applied: **+{route_risk_surcharge * 100:.0f}%**")
        with rc2:
            if speed_reduction > 0:
                st.write(
                    f"Speed reduction: **{speed_reduction}%** -> effective days: **{effective_days:.1f}**"
                )
            st.write(f"Bunker price used: **${bunker_price_per_ton:.0f}/ton** (from live WTI)")

st.write("---")
f1, f2, f3 = st.columns(3)
f1.caption(
    f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC"
    f" | Refresh #{count}"
    f" | Auto: {'on' if st.session_state.get('auto_refresh', True) else 'off'}"
)
f2.caption("Data: ACLED · GDELT · NewsAPI · Guardian · FRED · NOAA · OpenWeather")
f3.caption("War Room v3.0 - Dynamic Intelligence Dashboard")
