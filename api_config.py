# API configuration for the Global Events Dashboard

# Public API endpoints
ACLED_BASE_URL = "https://api.acleddata.com/acled/read"
GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
WORLD_BANK_BASE_URL = "http://api.worldbank.org/v2"
NOAA_ALERTS_URL = "https://api.weather.gov/alerts/active"

# API keys (replace with your own values)
NEWSAPI_KEY = "YOUR_NEWSAPI_KEY_HERE"
FRED_API_KEY = "YOUR_FRED_KEY_HERE"
OPENWEATHER_KEY = "YOUR_OPENWEATHER_KEY_HERE"
GUARDIAN_API_KEY = "YOUR_GUARDIAN_KEY_HERE"

# Caching and app configuration
CACHE_TTL_MINUTES = 30
CACHE_ENABLED = True

# Default regions and monitoring targets used by the dashboard
KEY_REGIONS = {
    "Middle East": {"lat": 29.0, "lon": 45.0},
    "Eastern Europe": {"lat": 50.0, "lon": 30.0},
    "Southeast Asia": {"lat": 9.0, "lon": 103.0},
    "Atlantic": {"lat": 25.0, "lon": -40.0},
    "Indian Ocean": {"lat": -10.0, "lon": 80.0},
}

TRADE_MONITOR_COUNTRIES = ["US", "CN", "DE", "GB", "JP"]
CRITICAL_PORTS = [
    "Suez Canal",
    "Panama Canal",
    "Singapore Strait",
    "Strait of Hormuz",
    "English Channel",
]
