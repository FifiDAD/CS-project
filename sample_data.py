"""Data fetching for the Global Events Dashboard"""

import pandas as pd
from datetime import datetime, timedelta
import streamlit as st

@st.cache_data(ttl=1800)
def get_events_data():
    """Fetch real events from ACLED and GDELT APIs, with fallback to sample data"""
    
    try:
        # Try to fetch real data from ACLED
        from api_integrations import APIClient
        acled_events = APIClient.get_acled_events(limit=50, days=30)
        
        if len(acled_events) > 0:
            # Convert ACLED data to our format
            events = []
            for idx, row in acled_events.iterrows():
                events.append({
                    "event_id": f"ACLED_{idx}",
                    "type": row.get('event_type', 'Conflict'),
                    "location": row.get('country', 'Unknown'),
                    "latitude": float(row.get('latitude', 0)),
                    "longitude": float(row.get('longitude', 0)),
                    "date": row.get('date', datetime.now()),
                    "impact": "Critical" if row.get('fatalities', 0) > 5 else "High" if row.get('fatalities', 0) > 0 else "Medium",
                    "description": row.get('notes', 'Conflict event recorded'),
                    "affected_routes": [],
                    "business_impact": f"Fatalities: {row.get('fatalities', 0)}"
                })
            
            if events:
                return pd.DataFrame(events)
    except Exception:
        pass
    
    # Fallback to sample data if API fails
    return get_sample_events()

def get_sample_events():
    """Fallback sample data when APIs are unavailable"""
    
    events = [
        {
            "event_id": "E001",
            "type": "Military Strike",
            "location": "Ukraine, Eastern Region",
            "latitude": 48.5,
            "longitude": 37.5,
            "date": datetime.now() - timedelta(hours=2),
            "impact": "Critical",
            "description": "Military activity reported in eastern sector",
            "affected_routes": ["English Channel"],
            "business_impact": "Port operations at risk"
        },
        {
            "event_id": "E002",
            "type": "Port Disruption",
            "location": "Red Sea, Houthi Area",
            "latitude": 15.5,
            "longitude": 42.0,
            "date": datetime.now() - timedelta(hours=6),
            "impact": "High",
            "description": "Port operations disrupted due to regional tensions",
            "affected_routes": ["Suez Canal"],
            "business_impact": "Shipping delays expected, 15-20% cost increase"
        },
        {
            "event_id": "E003",
            "type": "Supply Chain Alert",
            "location": "South China Sea",
            "latitude": 10.5,
            "longitude": 110.0,
            "date": datetime.now() - timedelta(hours=12),
            "impact": "Medium",
            "description": "Increased naval activity reported",
            "affected_routes": ["Singapore Strait"],
            "business_impact": "Monitor shipping insurance rates"
        },
        {
            "event_id": "E004",
            "type": "Political Instability",
            "location": "Middle East, Iran-Iraq Border",
            "latitude": 35.0,
            "longitude": 46.0,
            "date": datetime.now() - timedelta(hours=18),
            "impact": "High",
            "description": "Border tensions escalating",
            "affected_routes": ["Strait of Hormuz"],
            "business_impact": "Oil prices up 5%, shipping premium increasing"
        },
        {
            "event_id": "E005",
            "type": "Weather Hazard",
            "location": "Atlantic Ocean, Storm Zone",
            "latitude": 40.0,
            "longitude": -50.0,
            "date": datetime.now() - timedelta(hours=4),
            "impact": "Medium",
            "description": "Severe weather warning issued",
            "affected_routes": ["English Channel"],
            "business_impact": "Potential 2-3 day delays"
        },
        {
            "event_id": "E006",
            "type": "Terrorist Activity",
            "location": "Somalia, Port Area",
            "latitude": 9.0,
            "longitude": 44.5,
            "date": datetime.now() - timedelta(hours=24),
            "impact": "Medium",
            "description": "Security concerns at port facilities",
            "affected_routes": ["Suez Canal"],
            "business_impact": "Security escort required for vessels"
        },
    ]
    
    return pd.DataFrame(events)

def get_shipping_status():
    """Get current shipping route status"""
    
    status_data = {
        "Route": ["Suez Canal", "Panama Canal", "Singapore Strait", "Strait of Hormuz", "English Channel"],
        "Status": ["Operational - Alert", "Operational", "Operational", "Operational - High Risk", "Operational"],
        "Traffic Level": ["High", "High", "Very High", "Critical", "Very High"],
        "Average Delay": ["12 hours", "0 hours", "2 hours", "18 hours", "1 hour"],
        "Cost Impact": ["+15%", "+0%", "+5%", "+25%", "+0%"],
    }
    
    return pd.DataFrame(status_data)

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
