"""Map visualization functions for the Global Events Dashboard"""

import folium
from folium import plugins
import pandas as pd
from config import EVENT_TYPES, MAJOR_SHIPPING_ROUTES, DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM

def create_base_map(center=None, zoom=None):
    """Create base folium map"""
    
    if center is None:
        center = DEFAULT_MAP_CENTER
    if zoom is None:
        zoom = DEFAULT_MAP_ZOOM
    
    m = folium.Map(
        location=center,
        zoom_start=zoom,
        tiles="OpenStreetMap"
    )
    
    return m

def add_events_to_map(map_obj, events_df):
    """Add conflict events as markers to the map"""
    
    for idx, row in events_df.iterrows():
        event_type = row["type"]
        
        # Get color and icon from config
        color = EVENT_TYPES.get(event_type, {}).get("color", "gray")
        icon_text = EVENT_TYPES.get(event_type, {}).get("icon", "📍")
        
        # Create popup text
        popup_text = f"""
        <b>{row['type']}</b><br>
        Location: {row['location']}<br>
        Time: {row['date'].strftime('%Y-%m-%d %H:%M')}<br>
        Impact: {row['impact']}<br>
        Description: {row['description']}<br>
        Business Impact: {row['business_impact']}
        """
        
        # Add marker
        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            popup=folium.Popup(popup_text, max_width=300),
            icon=folium.Icon(color=color, icon="warning"),
            tooltip=f"{row['type']} - {row['location']}"
        ).add_to(map_obj)
    
    return map_obj

def add_shipping_routes_to_map(map_obj, routes_dict):
    """Add shipping routes to the map"""
    
    for route_name, route_info in routes_dict.items():
        coords = route_info["coords"]
        status = route_info["status"]
        traffic = route_info["traffic"]
        
        # Determine color based on traffic
        traffic_color = {
            "Critical": "red",
            "Very High": "orange",
            "High": "yellow",
            "Medium": "blue",
            "Low": "green"
        }
        
        color = traffic_color.get(traffic, "blue")
        weight = {"Critical": 5, "Very High": 4, "High": 3, "Medium": 2, "Low": 1}.get(traffic, 2)
        
        # Add route line
        folium.PolyLine(
            locations=coords,
            color=color,
            weight=weight,
            opacity=0.8,
            popup=f"{route_name}<br>Traffic: {traffic}<br>Status: {status}",
            tooltip=f"{route_name} ({traffic})"
        ).add_to(map_obj)
    
    return map_obj

def create_dashboard_map(events_df, show_routes=True):
    """Create complete dashboard map with all elements"""
    
    # Create base map
    m = create_base_map()
    
    # Add events
    m = add_events_to_map(m, events_df)
    
    # Add shipping routes
    if show_routes:
        m = add_shipping_routes_to_map(m, MAJOR_SHIPPING_ROUTES)
    
    # Add layer control
    folium.LayerControl().add_to(m)
    
    return m
