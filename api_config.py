"""API Configuration"""

import os

# ============================================
# FREE API KEYS
# ============================================

# Supported API keys can be loaded from environment variables first,
# with local defaults used as fallbacks for current development.
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "82ffc7cbf56f471a967475a85fb48316")
FRED_API_KEY = os.getenv("FRED_API_KEY", "c2f3fe9e461b3cf4575193da337d8ff2")
OPENWEATHER_KEY = os.getenv("OPENWEATHER_KEY", "27616ee5c23d8fa0fc3b462365972af5")
GUARDIAN_API_KEY = os.getenv("GUARDIAN_API_KEY", "1c657aa6-af8d-40d6-9ad7-984b8a497a23")

# ============================================
# API ENDPOINTS (No keys needed)
# ============================================

ACLED_BASE_URL      = "https://api.acleddata.com/api/add/"
GDELT_BASE_URL      = "https://api.gdeltproject.org/api/v2/search/tv"
GDELT_DOC_URL       = "https://api.gdeltproject.org/api/v2/doc/doc"   # article search, free
WORLD_BANK_BASE_URL = "https://api.worldbank.org/v2"
NOAA_ALERTS_URL     = "https://api.weather.gov/alerts/active"
UN_COMTRADE_URL     = "https://unstats.un.org/comtrade/api"
OPENWEATHER_URL     = "https://api.openweathermap.org/data/2.5/weather"

# ============================================
# CACHE SETTINGS (to avoid rate limits)
# ============================================

CACHE_TTL_MINUTES = 30  # Cache data for 30 minutes (legacy, kept for compatibility)
CACHE_ENABLED = True

# Tiered TTLs (seconds) — used per-method in api_integrations.py
CACHE_TTL_NEWS   = 300    # 5 min  — news articles change frequently
CACHE_TTL_EVENTS = 900    # 15 min — conflict events, weather, port/strait status
CACHE_TTL_PRICES = 1800   # 30 min — commodity prices, exchange rates, trade data

# ============================================
# REGIONS & COORDINATES FOR MONITORING
# ============================================

KEY_REGIONS = {
    "Middle East": {"lat": 28, "lon": 45, "radius": 1000},
    "Eastern Ukraine": {"lat": 48.5, "lon": 37.5, "radius": 500},
    "South China Sea": {"lat": 10, "lon": 112, "radius": 800},
    "Red Sea-Suez": {"lat": 15.5, "lon": 42, "radius": 400},
    "Persian Gulf": {"lat": 27, "lon": 52, "radius": 300},
    "Strait of Malaysia": {"lat": 2, "lon": 104, "radius": 200},
}

TRADE_MONITOR_COUNTRIES = [
    "China", "United States", "Germany", "Japan", "India",
    "United Kingdom", "France", "Italy", "Netherlands", "Canada",
    "Russia", "Iran", "North Korea", "Venezuela", "Syria"
]

CRITICAL_PORTS = {
    "Singapore":   {"lat":  1.35, "lon": 103.82, "risk_weight": 1.0},
    "Shanghai":    {"lat": 30.96, "lon": 121.56,  "risk_weight": 0.9},
    "Rotterdam":   {"lat": 51.97, "lon":   4.13,  "risk_weight": 0.8},
    "Dubai":       {"lat": 25.27, "lon":  55.27,  "risk_weight": 1.0},
    "Hong Kong":   {"lat": 22.30, "lon": 114.19,  "risk_weight": 0.7},
    "Los Angeles": {"lat": 33.74, "lon": -118.21, "risk_weight": 0.6},
    "Hamburg":     {"lat": 53.55, "lon":  10.01,  "risk_weight": 0.7},
    "Port Said":   {"lat": 31.26, "lon":  32.30,  "risk_weight": 1.0},
}

# Precise strait/chokepoint coordinates for proximity-based risk computation
STRAIT_COORDINATES = {
    "Suez Canal":        {"lat": 30.42, "lon":  32.35, "radius_km": 200},
    "Strait of Hormuz":  {"lat": 26.35, "lon":  56.40, "radius_km": 200},
    "Singapore Strait":  {"lat":  1.25, "lon": 103.83, "radius_km": 150},
    "Panama Canal":      {"lat":  9.08, "lon": -79.68, "radius_km": 150},
    "English Channel":   {"lat": 50.55, "lon":  -1.20, "radius_km": 200},
}

# ============================================
# Usage notes
# ============================================
# You can still configure keys with environment variables if needed,
# or use the values above directly for local development.

