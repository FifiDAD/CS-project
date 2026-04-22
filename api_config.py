"""Configuration for API-backed dashboard features."""

import os


NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "YOUR_NEWSAPI_KEY_HERE")
FRED_API_KEY = os.getenv("FRED_API_KEY", "YOUR_FRED_KEY_HERE")
OPENWEATHER_KEY = os.getenv("OPENWEATHER_KEY", "YOUR_OPENWEATHER_KEY_HERE")
GUARDIAN_API_KEY = os.getenv("GUARDIAN_API_KEY", "YOUR_GUARDIAN_KEY_HERE")


ACLED_BASE_URL = "https://api.acleddata.com/acled/read"
GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/search/tv"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
WORLD_BANK_BASE_URL = "https://api.worldbank.org/v2"
NOAA_ALERTS_URL = "https://api.weather.gov/alerts/active"
UN_COMTRADE_URL = "https://unstats.un.org/comtrade/api"
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"


CACHE_ENABLED = True
CACHE_TTL_MINUTES = 30
CACHE_TTL_NEWS = 300
CACHE_TTL_EVENTS = 900
CACHE_TTL_PRICES = 1800


KEY_REGIONS = {
    "Middle East": {"lat": 28.0, "lon": 45.0, "radius": 1000},
    "Eastern Ukraine": {"lat": 48.5, "lon": 37.5, "radius": 500},
    "South China Sea": {"lat": 10.0, "lon": 112.0, "radius": 800},
    "Red Sea-Suez": {"lat": 15.5, "lon": 42.0, "radius": 400},
    "Persian Gulf": {"lat": 27.0, "lon": 52.0, "radius": 300},
    "Strait of Malaysia": {"lat": 2.0, "lon": 104.0, "radius": 200},
}

TRADE_MONITOR_COUNTRIES = [
    "China",
    "United States",
    "Germany",
    "Japan",
    "India",
    "United Kingdom",
    "France",
    "Italy",
    "Netherlands",
    "Canada",
    "Russia",
    "Iran",
    "North Korea",
    "Venezuela",
    "Syria",
]

CRITICAL_PORTS = {
    "Singapore": {"lat": 1.35, "lon": 103.82, "risk_weight": 1.0},
    "Shanghai": {"lat": 30.96, "lon": 121.56, "risk_weight": 0.9},
    "Rotterdam": {"lat": 51.97, "lon": 4.13, "risk_weight": 0.8},
    "Dubai": {"lat": 25.27, "lon": 55.27, "risk_weight": 1.0},
    "Hong Kong": {"lat": 22.30, "lon": 114.19, "risk_weight": 0.7},
    "Los Angeles": {"lat": 33.74, "lon": -118.21, "risk_weight": 0.6},
    "Hamburg": {"lat": 53.55, "lon": 10.01, "risk_weight": 0.7},
    "Port Said": {"lat": 31.26, "lon": 32.30, "risk_weight": 1.0},
}

STRAIT_COORDINATES = {
    "Suez Canal": {"lat": 30.42, "lon": 32.35, "radius_km": 200},
    "Strait of Hormuz": {"lat": 26.35, "lon": 56.40, "radius_km": 200},
    "Singapore Strait": {"lat": 1.25, "lon": 103.83, "radius_km": 150},
    "Panama Canal": {"lat": 9.08, "lon": -79.68, "radius_km": 150},
    "English Channel": {"lat": 50.55, "lon": -1.20, "radius_km": 200},
}
