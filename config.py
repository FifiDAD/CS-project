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

# Shipping routes — realistic multi-waypoint paths along actual shipping lanes
MAJOR_SHIPPING_ROUTES = {
    "Suez Canal": {
        "coords": [
            # Mediterranean approach → Canal → Red Sea → Gulf of Aden
            [35.0, 14.0], [33.5, 25.0], [31.5, 32.0], [30.7, 32.4], [30.0, 32.6],
            [27.0, 33.5], [22.0, 37.0], [17.0, 41.0], [13.0, 43.5], [11.5, 44.0],
        ],
        "status": "operational", "traffic": "High",
    },
    "Panama Canal": {
        "coords": [
            # Caribbean → Canal → Pacific
            [10.5, -75.5], [9.8, -77.0], [9.3, -79.0], [9.0, -79.6], [8.8, -80.5],
            [8.5, -82.0], [8.0, -84.0],
        ],
        "status": "operational", "traffic": "High",
    },
    "Singapore Strait": {
        "coords": [
            # Malacca approach → Singapore → South China Sea
            [5.5, 99.0], [4.0, 100.5], [2.5, 102.0], [1.5, 103.5], [1.2, 103.9],
            [1.0, 104.5], [1.2, 106.0], [2.0, 108.0],
        ],
        "status": "operational", "traffic": "Very High",
    },
    "Strait of Hormuz": {
        "coords": [
            # Persian Gulf → Strait → Arabian Sea
            [26.5, 50.5], [26.8, 53.0], [26.6, 55.5], [26.2, 56.3], [25.8, 57.0],
            [24.5, 58.5], [23.0, 60.0],
        ],
        "status": "operational", "traffic": "Critical",
    },
    "English Channel": {
        "coords": [
            # Atlantic → Channel → North Sea
            [49.5, -6.0], [50.0, -4.0], [50.3, -2.0], [50.6, 0.0], [51.0, 1.5],
            [51.5, 3.0], [52.0, 4.5],
        ],
        "status": "operational", "traffic": "Very High",
    },
}

# Status string → line color on the globe
ROUTE_STATUS_COLORS = {
    "Operational":              "limegreen",
    "Operational - Alert":      "yellow",
    "Operational - High Risk":  "orange",
    "Critical - Avoid":         "red",
}
