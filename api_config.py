"""API Configuration — endpoints + monitoring constants. Secrets live in secrets.py."""

import os

# Re-export keys for backwards compatibility with existing imports.
# New code should import secrets from app_secrets.py directly, but older modules
# still expect these names to live here.
from app_secrets import (
    NEWSAPI_KEY,
    FRED_API_KEY,
    OPENWEATHER_KEY,
    GUARDIAN_API_KEY,
    AISSTREAM_KEY,
)

# Optional generic news APIs — gated on env vars. Empty string when unset
# means the corresponding APIClient method returns an empty DataFrame and the
# rest of the news feed continues to work.
GNEWS_KEY    = os.getenv("GNEWS_KEY", "")
NEWSDATA_KEY = os.getenv("NEWSDATA_KEY", "")

# Maritime industry RSS feeds (no key required). Each entry: (display_source, url).
MARITIME_RSS_FEEDS: list[tuple[str, str]] = [
    ("gCaptain",            "https://gcaptain.com/feed/"),
    ("Maritime Executive",  "https://www.maritime-executive.com/articles.rss"),
    ("Splash247",           "https://splash247.com/feed/"),
    ("The Maritime Standard", "https://www.themaritimestandard.com/feed/"),
]

# ============================================
# API ENDPOINTS
# ============================================

# Raw endpoint constants are collected here so APIClient methods do not bury
# service URLs inside request code.
GDELT_BASE_URL      = "https://api.gdeltproject.org/api/v2/doc/doc"  # timeline modes too
GDELT_DOC_URL       = "https://api.gdeltproject.org/api/v2/doc/doc"
WORLD_BANK_BASE_URL = "https://api.worldbank.org/v2"
NOAA_ALERTS_URL     = "https://api.weather.gov/alerts/active"
UN_COMTRADE_URL     = "https://unstats.un.org/comtrade/api"
OPENWEATHER_URL     = "https://api.openweathermap.org/data/2.5/weather"
OPEN_METEO_MARINE   = "https://marine-api.open-meteo.com/v1/marine"
SHIPANDBUNKER_URL   = "https://shipandbunker.com/prices"
IMB_PIRACY_RSS      = "https://www.icc-ccs.org/piracy-reporting-centre/live-piracy-map"
AISSTREAM_WS_URL    = "wss://stream.aisstream.io/v0/stream"
GDELT_LASTUPDATE    = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"

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
    # Broad monitoring regions used for overview-level risk and map context.
    "Middle East": {"lat": 28, "lon": 45, "radius": 1000},
    "Eastern Ukraine": {"lat": 48.5, "lon": 37.5, "radius": 500},
    "South China Sea": {"lat": 10, "lon": 112, "radius": 800},
    "Red Sea-Suez": {"lat": 15.5, "lon": 42, "radius": 400},
    "Persian Gulf": {"lat": 27, "lon": 52, "radius": 300},
    "Strait of Malaysia": {"lat": 2, "lon": 104, "radius": 200},
}

TRADE_MONITOR_COUNTRIES = [
    # Mix of major trade partners and sanctioned/high-risk states to monitor.
    "China", "United States", "Germany", "Japan", "India",
    "United Kingdom", "France", "Italy", "Netherlands", "Canada",
    "Russia", "Iran", "North Korea", "Venezuela", "Syria"
]

CRITICAL_PORTS = {
    # Major ports used as static fallback markers and congestion scoring anchors.
    "Singapore":   {"lat":  1.35, "lon": 103.82, "risk_weight": 1.0},
    "Shanghai":    {"lat": 30.96, "lon": 121.56,  "risk_weight": 0.9},
    "Rotterdam":   {"lat": 51.97, "lon":   4.13,  "risk_weight": 0.8},
    "Dubai":       {"lat": 25.27, "lon":  55.27,  "risk_weight": 1.0},
    "Hong Kong":   {"lat": 22.30, "lon": 114.19,  "risk_weight": 0.7},
    "Los Angeles": {"lat": 33.74, "lon": -118.21, "risk_weight": 0.6},
    "Hamburg":     {"lat": 53.55, "lon":  10.01,  "risk_weight": 0.7},
    "Port Said":   {"lat": 31.26, "lon":  32.30,  "risk_weight": 1.0},
}

# Precise strait/chokepoint coordinates for proximity-based risk computation.
# `aliases` are extra search terms fed into the GDELT query so we catch
# articles that don't use the canonical strait name (e.g. "Persian Gulf
# tensions" instead of "Strait of Hormuz blockade").
STRAIT_COORDINATES = {
    "Suez Canal": {
        "lat": 30.42, "lon": 32.35, "radius_km": 250,
        "aliases": ['"Suez Canal"', '"Red Sea shipping"', '"Egypt canal"'],
    },
    "Bab el-Mandeb": {
        "lat": 12.58, "lon": 43.33, "radius_km": 250,
        "aliases": ['"Bab el-Mandeb"', '"Bab al-Mandab"', '"Red Sea"', '"Houthi"', '"Yemen"'],
    },
    "Strait of Hormuz": {
        "lat": 26.35, "lon": 56.40, "radius_km": 300,
        "aliases": ['"Strait of Hormuz"', '"Persian Gulf"', '"Iran tanker"', '"Hormuz blockade"', '"Iran navy"'],
    },
    "Bosphorus": {
        "lat": 41.12, "lon": 29.07, "radius_km": 200,
        "aliases": ['"Bosphorus"', '"Bosporus"', '"Istanbul strait"', '"Turkish straits"'],
    },
    "Strait of Malacca": {
        "lat": 2.50, "lon": 101.50, "radius_km": 250,
        "aliases": ['"Strait of Malacca"', '"Malacca strait"', '"Malacca shipping"'],
    },
    "Singapore Strait": {
        "lat": 1.25, "lon": 103.83, "radius_km": 150,
        "aliases": ['"Singapore Strait"', '"Singapore port"', '"Malacca"'],
    },
    "Taiwan Strait": {
        "lat": 24.50, "lon": 119.50, "radius_km": 300,
        "aliases": ['"Taiwan Strait"', '"Taiwan tensions"', '"PLA navy Taiwan"'],
    },
    "Panama Canal": {
        "lat": 9.08, "lon": -79.68, "radius_km": 150,
        "aliases": ['"Panama Canal"', '"Panama drought"', '"Gatun"'],
    },
    "English Channel": {
        "lat": 50.55, "lon": -1.20, "radius_km": 200,
        "aliases": ['"English Channel"', '"Dover Strait"', '"Channel shipping"'],
    },
}

# ============================================
# Usage notes
# ============================================
# You can still configure keys with environment variables if needed,
# or use the values above directly for local development.

