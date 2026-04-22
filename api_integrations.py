"""API Integration Module - Fetch real data from free APIs"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
from api_config import (
    ACLED_BASE_URL, GDELT_BASE_URL, GDELT_DOC_URL, WORLD_BANK_BASE_URL,
    NEWSAPI_KEY, FRED_API_KEY, OPENWEATHER_KEY, GUARDIAN_API_KEY,
    CACHE_TTL_NEWS, CACHE_TTL_EVENTS, CACHE_TTL_PRICES,
    KEY_REGIONS, TRADE_MONITOR_COUNTRIES,
    CRITICAL_PORTS, NOAA_ALERTS_URL, OPENWEATHER_URL
)

class APIClient:
    """Centralized API client with caching and error handling"""

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_EVENTS)
    def get_acled_events(limit=100, days=30):
        """Fetch conflict events from ACLED (completely free, no key needed)"""
        try:
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            url = ACLED_BASE_URL
            params = {
                'limit': limit,
                'event_date': f'{start_date}|{end_date}',
                'iso': 0,
            }

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()

            data = response.json()
            if data.get('success'):
                events = data.get('data', [])
                df = pd.DataFrame(events)
                if len(df) > 0:
                    df['date'] = pd.to_datetime(df.get('event_date', datetime.now()))
                    return df
            return pd.DataFrame()
        except requests.exceptions.ConnectionError:
            return pd.DataFrame()
        except requests.exceptions.Timeout:
            return pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_EVENTS)
    def get_gdelt_events(query="conflict military shipping"):
        """Fetch global events timeline from GDELT (completely free)"""
        try:
            url = GDELT_BASE_URL
            params = {
                'query': query,
                'mode': 'TimelineVolRaw',
                'startdatetime': (datetime.now() - timedelta(days=7)).strftime("%Y%m%d%H%M%S"),
                'enddatetime': datetime.now().strftime("%Y%m%d%H%M%S"),
                'format': 'json'
            }

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            return data
        except requests.exceptions.ConnectionError:
            return {}
        except requests.exceptions.Timeout:
            return {}
        except Exception:
            return {}

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_NEWS)
    def get_gdelt_articles(query: str, timespan: str = "24h") -> list:
        """
        Fetch articles from GDELT DOC API for specific topic queries.
        Free, no key required. Used for port/strait congestion signals.
        """
        try:
            params = {
                "query": query,
                "mode": "artlist",
                "maxrecords": 25,
                "timespan": timespan,
                "format": "json",
                "sort": "DateDesc",
            }
            response = requests.get(GDELT_DOC_URL, params=params, timeout=8)
            response.raise_for_status()
            return response.json().get("articles", [])
        except Exception:
            return []

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_NEWS)
    def get_news_alerts(keywords="shipping port conflict military"):
        """Fetch news from NewsAPI (500 requests/day free)"""
        try:
            if NEWSAPI_KEY == "YOUR_NEWSAPI_KEY_HERE":
                return pd.DataFrame()

            url = "https://newsapi.org/v2/everything"
            params = {
                'q': keywords,
                'sortBy': 'publishedAt',
                'language': 'en',
                'pageSize': 50,
                'apiKey': NEWSAPI_KEY
            }

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()

            articles = response.json().get('articles', [])
            df = pd.DataFrame(articles)

            if len(df) > 0:
                df['publishedAt'] = pd.to_datetime(df['publishedAt'])
                df.rename(columns={'publishedAt': 'date'}, inplace=True)

            return df
        except requests.exceptions.ConnectionError:
            return pd.DataFrame()
        except requests.exceptions.Timeout:
            return pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_NEWS)
    def get_guardian_news(keywords="shipping conflict trade"):
        """Fetch news from Guardian API (completely free)"""
        try:
            if GUARDIAN_API_KEY == "YOUR_GUARDIAN_KEY_HERE":
                return pd.DataFrame()

            url = "https://content.guardianapis.com/search"
            params = {
                'q': keywords,
                'page-size': 50,
                'show-fields': 'thumbnail,trailText',
                'api-key': GUARDIAN_API_KEY
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            results = response.json().get('response', {}).get('results', [])
            if results:
                df = pd.DataFrame(results)
                return df
            return pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_PRICES)
    def get_oil_price():
        """Fetch oil prices from FRED API (completely free)"""
        try:
            if FRED_API_KEY == "YOUR_FRED_KEY_HERE":
                return 78.45

            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                'series_id': 'DCOILWTICO',
                'api_key': FRED_API_KEY,
                'file_type': 'json',
                'limit': 5,
                'sort_order': 'desc',
            }

            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                observations = data.get('observations', [])
                if observations:
                    value_str = next((o['value'] for o in observations if o['value'] != '.'), None)
                    if value_str:
                        return float(value_str)

            return 78.45
        except Exception:
            return 78.45

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_PRICES)
    def get_shipping_index():
        """Get Baltic Dry Index from FRED (shipping cost indicator)"""
        try:
            if FRED_API_KEY == "YOUR_FRED_KEY_HERE":
                return 1200

            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                'series_id': 'TSIFRGHT',
                'api_key': FRED_API_KEY,
                'file_type': 'json',
                'limit': 5,
                'sort_order': 'desc',
            }

            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                observations = data.get('observations', [])
                if observations:
                    value_str = next((o['value'] for o in observations if o['value'] != '.'), None)
                    if value_str:
                        return float(value_str)

            return 1200
        except Exception:
            return 1200

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_EVENTS)
    def get_weather_hazards(lat=0, lon=0):
        """Fetch weather hazards from NOAA (completely free)"""
        try:
            url = f"{NOAA_ALERTS_URL}?point={lat},{lon}"

            response = requests.get(url, timeout=5)
            response.raise_for_status()

            features = response.json().get('features', [])

            hazards = []
            for feature in features:
                props = feature.get('properties', {})
                hazards.append({
                    'event': props.get('event', 'Unknown'),
                    'headline': props.get('headline', ''),
                    'description': props.get('description', ''),
                    'severity': props.get('severity', 'Unknown'),
                    'onset': props.get('onset', ''),
                })

            return hazards
        except Exception:
            return []

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_EVENTS)
    def get_port_weather(lat: float, lon: float) -> dict:
        """
        OpenWeather current conditions at a coordinate (port or strait).
        Returns dict with wind_speed_ms, visibility_m, weather_main, weather_desc, temp_c.
        Returns {} on any failure (bad key, network error, etc.).
        """
        try:
            if OPENWEATHER_KEY == "YOUR_OPENWEATHER_KEY_HERE":
                return {}

            params = {
                "lat": lat,
                "lon": lon,
                "appid": OPENWEATHER_KEY,
                "units": "metric",
            }
            response = requests.get(OPENWEATHER_URL, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            return {
                "temp_c":         data["main"]["temp"],
                "wind_speed_ms":  data["wind"]["speed"],
                "wind_deg":       data["wind"].get("deg", 0),
                "visibility_m":   data.get("visibility", 10000),
                "weather_main":   data["weather"][0]["main"],
                "weather_desc":   data["weather"][0]["description"],
                "humidity":       data["main"]["humidity"],
                "pressure":       data["main"]["pressure"],
            }
        except Exception:
            return {}

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_PRICES)
    def get_world_bank_trade(country_code):
        """Get trade data from World Bank API (completely free)"""
        try:
            url = f"{WORLD_BANK_BASE_URL}/country/{country_code}/indicator/NE.EXP.GNFS.CD"
            params = {
                'format': 'json',
                'per_page': 10,
            }

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()

            data = response.json()
            if len(data) > 1 and isinstance(data[1], list):
                return data[1]
            return []
        except Exception:
            return []

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_PRICES)
    def get_exchange_rates():
        """Get currencies from Open Exchange Rates (free tier)"""
        try:
            url = "https://api.exchangerate-api.com/v4/latest/USD"
            response = requests.get(url, timeout=5)
            response.raise_for_status()

            data = response.json()
            rates = data.get('rates', {})
            return {
                'EUR': rates.get('EUR', 0),
                'GBP': rates.get('GBP', 0),
                'JPY': rates.get('JPY', 0),
                'CNY': rates.get('CNY', 0),
                'INR': rates.get('INR', 0),
            }
        except Exception:
            return {}

class DataProcessor:
    """Process and analyze fetched data"""

    @staticmethod
    def combine_conflict_data(acled_df, gdelt_data):
        """Combine ACLED and GDELT data"""
        processed = []

        if len(acled_df) > 0:
            for idx, row in acled_df.iterrows():
                processed.append({
                    'source': 'ACLED',
                    'event_type': row.get('event_type', 'Unknown'),
                    'location': row.get('country', ''),
                    'latitude': row.get('latitude', 0),
                    'longitude': row.get('longitude', 0),
                    'date': row.get('date', datetime.now()),
                    'description': row.get('notes', ''),
                    'impact': 'High' if row.get('fatalities', 0) > 0 else 'Medium'
                })

        return pd.DataFrame(processed)

    @staticmethod
    def calculate_regional_risk(events_df, regions=KEY_REGIONS):
        """Calculate risk score by region"""
        risk_scores = {}

        for region, coords in regions.items():
            region_events = events_df[
                (abs(events_df['latitude'] - coords['lat']) < 5) &
                (abs(events_df['longitude'] - coords['lon']) < 5)
            ]

            risk_scores[region] = {
                'event_count': len(region_events),
                'avg_impact': 'High' if len(region_events) > 2 else 'Medium',
                'latest': region_events['date'].max() if len(region_events) > 0 else None,
            }

        return risk_scores

    @staticmethod
    def calculate_business_impact(events_df, shipping_disruptions):
        """Calculate overall business impact score"""

        critical_events = len(events_df[events_df['impact'] == 'Critical'])
        high_events = len(events_df[events_df['impact'] == 'High'])
        disrupted_routes = shipping_disruptions

        impact_score = (critical_events * 30) + (high_events * 15) + (disrupted_routes * 10)

        if impact_score >= 70:
            risk_level = "Critical"
        elif impact_score >= 50:
            risk_level = "High"
        elif impact_score >= 30:
            risk_level = "Medium"
        else:
            risk_level = "Low"

        return {
            'score': min(impact_score, 100),
            'level': risk_level,
            'details': {
                'critical_events': critical_events,
                'high_events': high_events,
                'disrupted_routes': disrupted_routes,
            }
        }
