"""Configuration and constants for the Global Events Dashboard"""

# Map settings
DEFAULT_MAP_CENTER = [20, 0]
DEFAULT_MAP_ZOOM = 2

# Event types and colors
EVENT_TYPES = {
    "Military Strike": {"color": "red", "icon": "💥"},
    "Port Disruption": {"color": "orange", "icon": "🚢"},
    "Terrorist Activity": {"color": "darkred", "icon": "⚠️"},
    "Political Instability": {"color": "purple", "icon": "🏛️"},
    "Supply Chain Alert": {"color": "blue", "icon": "📦"},
    "Weather Hazard": {"color": "darkblue", "icon": "⛈️"},
}

# Impact levels
IMPACT_LEVELS = {
    "Critical": {"color": "#8B0000", "level": 3},
    "High": {"color": "#FF4500", "level": 2},
    "Medium": {"color": "#FFA500", "level": 1},
    "Low": {"color": "#FFD700", "level": 0},
}

# Shipping routes info
MAJOR_SHIPPING_ROUTES = {
    "Suez Canal": {"coords": [[30.5, 32.3], [31.0, 32.5]], "status": "operational", "traffic": "High"},
    "Panama Canal": {"coords": [[9.0, -79.5], [10.0, -79.0]], "status": "operational", "traffic": "High"},
    "Singapore Strait": {"coords": [[1.0, 103.5], [1.5, 104.5]], "status": "operational", "traffic": "Very High"},
    "Strait of Hormuz": {"coords": [[25.5, 56.0], [26.5, 57.0]], "status": "operational", "traffic": "Critical"},
    "English Channel": {"coords": [[50.0, -2.0], [51.5, 1.5]], "status": "operational", "traffic": "Very High"},
}
