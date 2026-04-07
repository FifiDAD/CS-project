"""API configuration and key placeholders for the Global Events Dashboard."""

import os

# -----------------------------
# API keys
# -----------------------------
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "YOUR_NEWSAPI_KEY_HERE")
FRED_API_KEY = os.getenv("FRED_API_KEY", "YOUR_FRED_KEY_HERE")
OPENWEATHER_KEY = os.getenv("OPENWEATHER_KEY", "YOUR_OPENWEATHER_KEY_HERE")
GUARDIAN_API_KEY = os.getenv("GUARDIAN_API_KEY", "YOUR_GUARDIAN_KEY_HERE")

# -----------------------------
# URL endpoints
# -----------------------------
ACLED_BASE_URL = "https://api.acleddata.com/acled/read"
GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
WORLD_BANK_BASE_URL = "http://api.worldbank.org/v2"
NOAA_ALERTS_URL = "https://api.weather.gov/alerts/active"

# -----------------------------
# Cache and monitor settings
# -----------------------------
CACHE_TTL_MINUTES = 30
CACHE_ENABLED = True

KEY_REGIONS = [
    "Middle East",
    "Eastern Europe",
    "Southeast Asia",
    "Indian Ocean",
    "Atlantic",
]

TRADE_MONITOR_COUNTRIES = ["US", "CN", "DE", "SG", "AE", "GB"]
CRITICAL_PORTS = [
    "Suez Canal",
    "Panama Canal",
    "Strait of Hormuz",
    "English Channel",
    "Singapore Strait",
]

# -----------------------------
# Usage notes
# -----------------------------
# Replace the placeholder values above with your actual API keys.
# You can also create a .env file in the project root with the same
# environment variable names, and Streamlit will load them automatically.
