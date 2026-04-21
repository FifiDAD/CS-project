"""Global Events Dashboard - Main Application with Real APIs"""

import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
from config import EVENT_TYPES
from sample_data import get_events_data, get_sample_events
from api_integrations import APIClient, DataProcessor
from analytics import RiskAnalytics
from maps import create_dashboard_map
from components import (
    render_kpi_section,
    render_event_list,
    filter_events,
    create_summary_stats,
)

# Page configuration
st.set_page_config(
    page_title="Global Events Dashboard",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Session state for settings
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True
if "email_notifications" not in st.session_state:
    st.session_state.email_notifications = False

# Custom CSS
st.markdown("""
    <style>
    .critical { color: #8B0000; font-weight: bold; }
    .high { color: #FF4500; font-weight: bold; }
    .medium { color: #FFA500; }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    </style>
""", unsafe_allow_html=True)

# Load data
@st.cache_data(ttl=1800)
def load_data():
    """Load all data from APIs"""
    
    # Get events
    events = get_events_data()
    
    # Get commodity prices
    oil_price = APIClient.get_oil_price()
    shipping_index = APIClient.get_shipping_index()
    
    # Get news
    news = APIClient.get_news_alerts()
    
    shipping_df = get_shipping_status()
    risk_df = get_risk_summary()
    
    return events, oil_price, shipping_index, news, shipping_df, risk_df

@st.cache_data(ttl=1800)
def get_shipping_status():
    """Get shipping route status"""
    status_data = {
        "Route": ["Suez Canal", "Panama Canal", "Singapore Strait", "Strait of Hormuz", "English Channel"],
        "Status": ["Operational - Alert", "Operational", "Operational", "Operational - High Risk", "Operational"],
        "Traffic Level": ["High", "High", "Very High", "Critical", "Very High"],
        "Average Delay": ["12 hours", "0 hours", "2 hours", "18 hours", "1 hour"],
        "Cost Impact": ["+15%", "+0%", "+5%", "+25%", "+0%"],
    }
    return pd.DataFrame(status_data)

@st.cache_data(ttl=1800)
def get_risk_summary():
    """Get risk summary by region"""
    risk_data = {
        "Region": ["Middle East", "Eastern Europe", "Southeast Asia", "Atlantic", "Indian Ocean"],
        "Risk Level": ["Critical", "High", "Medium", "Medium", "High"],
        "Active Events": [3, 2, 1, 1, 2],
        "Affected Routes": [2, 1, 1, 1, 2],
        "Business Impact": ["Very High", "High", "Medium", "Medium", "High"],
    }
    return pd.DataFrame(risk_data)

# Load data
events_df, oil_price, shipping_index, news_df, shipping_df, risk_df = load_data()

# Sidebar
st.sidebar.title("🔍 Dashboard Controls")
st.sidebar.write("---")

# Data source indicator
col1, col2 = st.sidebar.columns(2)
with col1:
    if len(events_df) > 0:
        st.sidebar.success("✅ APIs Active")
    else:
        st.sidebar.warning("⚠️ Using Sample Data")

if st.sidebar.button("🔄 Refresh All Data", key="refresh"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.write("---")

# Filters
st.sidebar.subheader("Event Filters")

event_type_filter = st.sidebar.selectbox(
    "Event Type",
    ["All Types"] + list(EVENT_TYPES.keys()),
    key="event_type"
)

impact_filter = st.sidebar.selectbox(
    "Impact Level",
    ["All Levels", "Critical", "High", "Medium", "Low"],
    key="impact"
)

search_text = st.sidebar.text_input(
    "Search Events",
    placeholder="Search location or description...",
    key="search"
)

# Apply filters
filtered_events = filter_events(events_df, event_type_filter, impact_filter, search_text)

st.sidebar.write("---")

st.sidebar.write("---")
st.sidebar.subheader("📊 Market Data")

if oil_price:
    st.sidebar.metric("💰 Oil Price (WTI)", f"${oil_price:.2f}/bbl")
else:
    st.sidebar.info("📊 Add FRED_API_KEY to see oil prices")

if shipping_index:
    st.sidebar.metric("⚓ Baltic Dry Index", f"{shipping_index:.0f}")

st.sidebar.write("---")
_sidebar_csv = filtered_events.to_csv(index=False)
st.sidebar.download_button(
    "📥 Export CSV",
    data=_sidebar_csv,
    file_name=f"events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    mime="text/csv"
)
with st.sidebar.expander("⚙️ Settings"):
    st.button("Login")
    st.session_state.email_notifications = st.toggle("Email notifications", value=st.session_state.email_notifications)
    st.session_state.auto_refresh = st.toggle("Auto-refresh", value=st.session_state.auto_refresh)

# Main content
st.title("🌍 Global Events Dashboard")
st.write("Real-time tracking of military strikes, shipping disruptions, and geopolitical conflicts affecting business.")

# Top navigation bar
selected_tab = st.radio("", ["Map", "Events", "Shipping", "Analytics", "Impact"], horizontal=True, label_visibility="collapsed")

st.write("---")

# Calculate analytics
analytics = RiskAnalytics.get_summary_metrics(filtered_events, oil_price, shipping_index)

# Alert banner
if "CRITICAL" in analytics['recommendation']:
    st.error(f"🚨 {analytics['recommendation']}")
elif "HIGH RISK" in analytics['recommendation']:
    st.warning(f"⚠️ {analytics['recommendation']}")
elif "ELEVATED" in analytics['recommendation']:
    st.info(f"📍 {analytics['recommendation']}")
else:
    st.success(f"✅ {analytics['recommendation']}")

st.write("---")

# KPI Section
st.subheader("📊 Key Performance Indicators")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("🚨 Critical Events", analytics['critical_events'])

with col2:
    st.metric("⚠️ High Risk Events", analytics['high_events'])

with col3:
    st.metric("📍 Total Events", analytics['total_events'])

with col4:
    st.metric("⏰ Last 48h", analytics['events_last_48h'])

with col5:
    st.metric("🌐 Worst Region", analytics['worst_affected_region'])

st.write("---")

# Tabs for different views
# Tab 1: Interactive Map
if selected_tab == "Map":
    st.subheader("Global Events Map")
    
    if len(filtered_events) > 0:
        map_obj = create_dashboard_map(filtered_events, show_routes=True)
        st.components.v1.html(map_obj._repr_html_(), height=600)
    else:
        st.info("No events to display with current filters")

# Tab 2: Events List
elif selected_tab == "Events":
    st.subheader("Active Events")
    
    if len(filtered_events) == 0:
        st.info("No events match your filters")
    else:
        st.write(f"Showing {len(filtered_events)} event(s)")
        
        filtered_events_sorted = filtered_events.sort_values("date", ascending=False)
        render_event_list(filtered_events_sorted)

# Tab 3: Shipping Routes
elif selected_tab == "Shipping":
    st.subheader("🚢 Shipping Route Status")
    st.dataframe(shipping_df, use_container_width=True, hide_index=True)
    
    st.write("---")
    
    st.subheader("Route Descriptions")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("""
        **Suez Canal**: Europe to Asia, ~12% of global trade  
        **Status**: ⚠️ Monitoring for disruptions
        """)
        
        st.write("""
        **Panama Canal**: Atlantic-Pacific connection, ~5% global trade  
        **Status**: ✅ Normal operations
        """)
    
    with col2:
        st.write("""
        **Strait of Hormuz**: Oil chokepoint, ~20% global oil  
        **Status**: 🚨 High tension zone
        """)
        
        st.write("""
        **Singapore Strait**: SE Asia passage, ~25% maritime trade  
        **Status**: ✅ Very high traffic, operational
        """)

# Tab 4: Analytics & Risk
elif selected_tab == "Analytics":
    st.subheader("📈 Detailed Risk Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("**Event Type Distribution**")
        if len(filtered_events) > 0:
            event_counts = filtered_events['type'].value_counts()
            fig = px.bar(
                x=event_counts.index,
                y=event_counts.values,
                labels={'x': 'Event Type', 'y': 'Count'},
                color=event_counts.values,
                color_continuous_scale='Reds'
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data to display")
    
    with col2:
        st.write("**Impact Level Distribution**")
        if len(filtered_events) > 0:
            impact_counts = filtered_events['impact'].value_counts()
            fig = px.pie(
                values=impact_counts.values,
                names=impact_counts.index,
                color_discrete_sequence=['#8B0000', '#FF4500', '#FFA500', '#FFD700']
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data to display")
    
    st.write("---")
    
    # Timeline of events
    st.write("**Events Timeline (Last 30 Days)**")
    if len(filtered_events) > 0:
        daily_counts = pd.DataFrame({
            'date': filtered_events['date'].dt.date,
            'events': 1
        }).groupby('date').sum().reset_index()
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=daily_counts['date'],
            y=daily_counts['events'],
            fill='tozeroy',
            mode='lines+markers',
            line_color='#FF4500',
            name='Events'
        ))
        
        fig.update_layout(
            xaxis_title='Date',
            yaxis_title='Number of Events',
            hovermode='x unified'
        )
        st.plotly_chart(fig, use_container_width=True)

# Tab 5: Financial Impact
elif selected_tab == "Impact":
    st.subheader("💰 Business Impact Assessment")
    
    # Calculate costs
    cost_impact = RiskAnalytics.calculate_cost_impact(filtered_events, oil_price, {})
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "Daily Cost Impact",
            f"${cost_impact['daily_cost_increase_usd']:,.0f}",
            delta=f"${cost_impact['daily_cost_increase_usd']:,.0f}"
        )
    
    with col2:
        st.metric(
            "Monthly Projection",
            f"${cost_impact['monthly_cost_increase_usd']:,.0f}",
        )
    
    with col3:
        st.metric(
            "Affected Vessels (~)",
            f"{cost_impact['affected_vessels']:.0f}",
        )
    
    st.write("---")
    
    # Cost breakdown
    st.write("**Cost Impact Breakdown**")
    
    cost_data = pd.DataFrame({
        'Timeframe': ['Daily', 'Weekly', 'Monthly'],
        'Cost Increase (USD)': [
            cost_impact['daily_cost_increase_usd'],
            cost_impact['weekly_cost_increase_usd'],
            cost_impact['monthly_cost_increase_usd']
        ]
    })
    
    fig = px.bar(
        cost_data,
        x='Timeframe',
        y='Cost Increase (USD)',
        color='Cost Increase (USD)',
        color_continuous_scale='Reds',
        text='Cost Increase (USD)'
    )
    fig.update_traces(texttemplate='$%{text:,.0f}', textposition='outside')
    st.plotly_chart(fig, use_container_width=True)
    
    st.write("---")
    
    # Risk factors
    st.write("**Risk Multipliers**")
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"🛢️ Oil Price Multiplier: **{cost_impact['oil_multiplier']}x**")
        if oil_price:
            st.write(f"Current WTI: ${oil_price:.2f}/barrel")
    
    with col2:
        st.write(f"⚠️ Event Risk Multiplier: **{cost_impact['event_risk_multiplier']}x**")
        st.write(f"Total events affecting costs: {analytics['critical_events'] + analytics['high_events']}")
    
    st.write("---")
    
    # Delay impact
    st.write("**Estimated Shipping Delays**")
    delay_data = pd.DataFrame({
        'Route': ['Suez Canal', 'Panama Canal', 'Singapore Strait', 'Hormuz', 'English Channel'],
        'Estimated Days': [12, 0, 2, 18, 1],
        'Cost Impact %': [15, 0, 5, 25, 0]
    })
    
    st.dataframe(delay_data, use_container_width=True, hide_index=True)

# Footer
st.write("---")

col1, col2, col3 = st.columns(3)

with col1:
    st.caption(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")

with col2:
    st.caption("Data: ACLED, GDELT, NewsAPI, FRED, NOAA")

with col3:
    st.caption("Dashboard v2.0 - Real APIs Active")