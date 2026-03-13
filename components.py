"""UI Components and helper functions"""

import streamlit as st
import pandas as pd
from config import EVENT_TYPES, IMPACT_LEVELS

def render_metric_card(title, value, delta=None, color="black"):
    """Render a metric card"""
    
    col1, col2, col3 = st.columns(3)
    
    with col2:
        st.metric(
            label=title,
            value=value,
            delta=delta,
        )

def render_event_card(event):
    """Render a single event card"""
    
    icon = EVENT_TYPES.get(event["type"], {}).get("icon", "📌")
    
    with st.container():
        col1, col2 = st.columns([1, 10])
        
        with col1:
            st.write(f"{icon}")
        
        with col2:
            st.write(f"**{event['type']}** - {event['location']}")
            st.write(f"*{event['date'].strftime('%Y-%m-%d %H:%M')}*")
            st.write(f"Impact: **{event['impact']}**")
            st.write(f"{event['description']}")
            st.write(f"📦 Business Impact: {event['business_impact']}")
        
        st.divider()

def render_event_list(events_df, limit=None):
    """Render list of events"""
    
    if limit:
        events_df = events_df.head(limit)
    
    for idx, row in events_df.iterrows():
        render_event_card(row.to_dict())

def render_kpi_section(events_df):
    """Render KPI section with key metrics"""
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        critical_count = len(events_df[events_df["impact"] == "Critical"])
        st.metric("🚨 Critical Events", critical_count)
    
    with col2:
        high_count = len(events_df[events_df["impact"].isin(["Critical", "High"])])
        st.metric("⚠️ High Risk", high_count)
    
    with col3:
        strike_count = len(events_df[events_df["type"] == "Military Strike"])
        st.metric("💥 Military Strikes", strike_count)
    
    with col4:
        routes_affected = events_df["affected_routes"].explode().nunique()
        st.metric("🚢 Routes Affected", routes_affected)

def filter_events(events_df, event_type=None, impact_level=None, search_text=None):
    """Filter events based on criteria"""
    
    filtered = events_df.copy()
    
    if event_type and event_type != "All Types":
        filtered = filtered[filtered["type"] == event_type]
    
    if impact_level and impact_level != "All Levels":
        filtered = filtered[filtered["impact"] == impact_level]
    
    if search_text:
        search_text = search_text.lower()
        filtered = filtered[
            filtered["description"].str.lower().str.contains(search_text) |
            filtered["location"].str.lower().str.contains(search_text)
        ]
    
    return filtered

def get_impact_color(impact):
    """Get color for impact level"""
    
    return IMPACT_LEVELS.get(impact, {}).get("color", "#FFD700")

def create_summary_stats(events_df, shipping_df):
    """Create summary statistics"""
    
    stats = {
        "total_events": len(events_df),
        "critical_events": len(events_df[events_df["impact"] == "Critical"]),
        "high_risk_events": len(events_df[events_df["impact"].isin(["Critical", "High"])]),
        "affected_shipping_routes": len(shipping_df[shipping_df["Status"].str.contains("Alert|Risk", regex=True)]),
        "business_risk_level": "Critical" if len(events_df[events_df["impact"] == "Critical"]) > 2 else "High" if len(events_df[events_df["impact"].isin(["Critical", "High"])]) > 3 else "Medium",
    }
    
    return stats
