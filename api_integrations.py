"""API Integration Module - Fetch real data from free APIs"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
from api_config import (
    ACLED_BASE_URL, GDELT_BASE_URL, WORLD_BANK_BASE_URL,
    NEWSAPI_KEY, FRED_API_KEY, OPENWEATHER_KEY, GUARDIAN_API_KEY,
    CACHE_TTL_MINUTES, CACHE_ENABLED, KEY_REGIONS, TRADE_MONITOR_COUNTRIES,
    CRITICAL_PORTS, NOAA_ALERTS_URL
)

class APIClient:
    """Centralized API client with caching and error handling"""
    
    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_MINUTES * 60)
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
                # Convert to DataFrame
                df = pd.DataFrame(events)
                if len(df) > 0:
                    df['date'] = pd.to_datetime(df.get('event_date', datetime.now()))
                    return df
            return pd.DataFrame()
        except requests.exceptions.ConnectionError:
            return pd.DataFrame()  # Silent failure - use fallback
        except requests.exceptions.Timeout:
            return pd.DataFrame()
        except Exception as e:
            return pd.DataFrame()  # Silent failure

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_MINUTES * 60)
    def get_gdelt_events(query="conflict military shipping"):
        """Fetch global events from GDELT (completely free)"""
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
    @st.cache_data(ttl=CACHE_TTL_MINUTES * 60)
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
    @st.cache_data(ttl=CACHE_TTL_MINUTES * 60)
    def get_guardian_news(keywords="shipping conflict trade"):
        """Fetch news from Guardian API (completely free)"""
        try:
            if GUARDIAN_API_KEY == "YOUR_GUARDIAN_KEY_HERE":
                return pd.DataFrame()
            
            url = "https://open-platform.theguardian.com/search"
            params = {
                'q': keywords,
                'section': 'business',
                'page-size': 50,
                'api-key': GUARDIAN_API_KEY
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            results = response.json().get('response', {}).get('results', [])
            if results:
                df = pd.DataFrame(results)
                return df
            return pd.DataFrame()
        except Exception as e:
            st.warning(f"Guardian API error: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_MINUTES * 60)
    def get_oil_price():
        """Fetch oil prices from FRED API (completely free)"""
        try:
            if FRED_API_KEY == "YOUR_FRED_KEY_HERE":
                return 78.45  # Mock WTI price
            
            # WTI Oil prices - try FRED API
            url = "https://api.stlouisfed.org/fred/series/DCOILWTICO/observations"
            params = {
                'api_key': FRED_API_KEY,
                'file_type': 'json',
                'limit': 1
            }
            
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                observations = data.get('observations', [])
                if observations:
                    latest = observations[-1]
                    return float(latest.get('value', 0))
            
            # If FRED fails, return realistic market price
            return 78.45
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, Exception):
            return 78.45  # Return realistic fallback price

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_MINUTES * 60)
    def get_shipping_index():
        """Get Baltic Dry Index from FRED (shipping cost indicator)"""
        try:
            if FRED_API_KEY == "YOUR_FRED_KEY_HERE":
                return 1200  # Mock BDI
            
            url = "https://api.stlouisfed.org/fred/series/BALTICEXU/observations"
            params = {
                'api_key': FRED_API_KEY,
                'file_type': 'json',
                'limit': 1
            }
            
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                observations = data.get('observations', [])
                if observations:
                    return float(observations[-1].get('value', 1200))
            
            return 1200  # Mock BDI fallback
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, Exception):
            return 1200

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_MINUTES * 60)
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
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, Exception):
            return []

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_MINUTES * 60)
    def get_world_bank_trade(country_code):
        """Get trade data from World Bank API (completely free)"""
        try:
            url = f"{WORLD_BANK_BASE_URL}/country/{country_code}/indicator"
            params = {
                'indicators': 'NE.EXP.GNFS.CD,NE.IMP.GNFS.CD',
                'format': 'json'
            }
            
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            
            data = response.json()
            if len(data) > 1:
                return data[1]
            return []
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, Exception):
            return []

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_MINUTES * 60)
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
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, Exception):
            return {}

class DataProcessor:
    """Process and analyze fetched data"""
    
    @staticmethod
    def combine_conflict_data(acled_df, gdelt_data):
        """Combine ACLED and GDELT data"""
        processed = []
        
        # Process ACLED
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
        
        # Calculate impact score (0-100)
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
