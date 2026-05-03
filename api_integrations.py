"""API Integration Module - Fetch real data from free APIs"""

import os
from pathlib import Path

import requests
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st

# Persistent HTTP cache so dev reloads don't burn quota.
# Layered under @st.cache_data — Streamlit memoizes per-session, this
# survives restarts and across processes (e.g. test_apis.py + streamlit).
try:
    import requests_cache
    requests_cache.install_cache(
        str(Path(__file__).resolve().parent / ".requests_cache"),
        backend="sqlite",
        expire_after=300,                     # 5 min default
        allowable_methods=("GET",),
        allowable_codes=(200,),               # never cache 429/5xx
        stale_if_error=False,
    )
except ImportError:
    pass

from api_config import (
    GDELT_BASE_URL, GDELT_DOC_URL, WORLD_BANK_BASE_URL,
    NEWSAPI_KEY, FRED_API_KEY, OPENWEATHER_KEY, GUARDIAN_API_KEY,
    CACHE_TTL_NEWS, CACHE_TTL_EVENTS, CACHE_TTL_PRICES,
    KEY_REGIONS, TRADE_MONITOR_COUNTRIES,
    CRITICAL_PORTS, NOAA_ALERTS_URL, OPENWEATHER_URL,
    OPEN_METEO_MARINE, SHIPANDBUNKER_URL, GDELT_LASTUPDATE,
)

_GDELT_HEADERS = {"User-Agent": "LogisticsDashboard/1.0 (contact: ops@example.com)"}


def _gdelt_get(url: str, params: dict, timeout: int = 10) -> requests.Response | None:
    """GDELT throttles to 1 req / 5 sec and gets stricter after repeated 429s.
    Retry with growing back-off (6s, 12s, 20s)."""
    import time as _t
    for attempt, nap in enumerate((6, 12, 20)):
        try:
            r = requests.get(url, params=params, headers=_GDELT_HEADERS, timeout=timeout)
        except requests.RequestException:
            return None
        if r.status_code == 429 and attempt < 2:
            _t.sleep(nap)
            continue
        return r
    return None


class APIClient:
    """Centralized API client with caching and error handling"""

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_EVENTS)
    def get_gdelt_events(query="conflict military shipping"):
        """Fetch global events timeline from GDELT (free; needs User-Agent)."""
        try:
            params = {
                'query': query,
                'mode': 'TimelineVol',
                'timespan': '1week',
                'format': 'json',
            }
            response = _gdelt_get(GDELT_BASE_URL, params)
            if response is None or response.status_code != 200:
                return {}
            ctype = response.headers.get("Content-Type", "")
            if "json" not in ctype:
                return {}
            return response.json()
        except (requests.RequestException, ValueError):
            return {}

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_NEWS)
    def get_gdelt_articles(query: str, timespan: str = "24H") -> list:
        """Fetch articles from GDELT DOC API. Free, but requires User-Agent."""
        try:
            params = {
                "query": query,
                "mode": "artlist",
                "maxrecords": 75,
                "timespan": timespan,
                "format": "json",
                "sort": "HybridRel",
            }
            response = _gdelt_get(GDELT_DOC_URL, params)
            if response is None or response.status_code != 200:
                return []
            ctype = response.headers.get("Content-Type", "")
            if "json" not in ctype:
                return []
            return response.json().get("articles", [])
        except (requests.RequestException, ValueError):
            return []

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_NEWS)
    def get_news_alerts(keywords="shipping port conflict military"):
        """Fetch news from NewsAPI (500 requests/day free)"""
        try:
            if not NEWSAPI_KEY:
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
            if not GUARDIAN_API_KEY:
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
            if not FRED_API_KEY:
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
            if not FRED_API_KEY:
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
            if not OPENWEATHER_KEY:
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

    # -------------------------------------------------------------------
    # Marine / shipping-specific APIs (Phase A additions)
    # -------------------------------------------------------------------

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_EVENTS)
    def get_marine_weather(lat: float, lon: float) -> dict:
        """Open-Meteo Marine API — wave height, swell, currents. Free, no key."""
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": "wave_height,wave_period,wind_wave_height,swell_wave_height,ocean_current_velocity,ocean_current_direction",
                "timezone": "UTC",
            }
            r = requests.get(OPEN_METEO_MARINE, params=params, timeout=10)
            r.raise_for_status()
            current = r.json().get("current", {}) or {}
            return {
                "wave_height_m":      current.get("wave_height"),
                "wave_period_s":      current.get("wave_period"),
                "wind_wave_height_m": current.get("wind_wave_height"),
                "swell_height_m":     current.get("swell_wave_height"),
                "current_speed_kn":   current.get("ocean_current_velocity"),
                "current_dir_deg":    current.get("ocean_current_direction"),
            }
        except (requests.RequestException, ValueError):
            return {}

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_PRICES)
    def get_bunker_prices() -> pd.DataFrame:
        """Scrape Ship & Bunker daily prices for major ports.

        Returns columns: port, grade (VLSFO/IFO380/MGO), price_usd_per_mt, change.
        Empty DataFrame on parse failure — caller should fall back to a default.
        """
        from bs4 import BeautifulSoup

        try:
            r = requests.get(
                SHIPANDBUNKER_URL,
                headers={"User-Agent": "Mozilla/5.0 LogisticsDashboard/1.0"},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            rows = []
            for grade in ("VLSFO", "MGO", "IFO380"):
                table = soup.select_one(f"table.price-table.{grade}")
                if not table:
                    continue
                for tr in table.select("tbody tr"):
                    cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
                    if len(cells) < 3:
                        continue
                    port = cells[0]
                    if port.lower().startswith(("global", "americas", "apac", "emea")):
                        continue  # skip aggregate rows
                    try:
                        price = float(cells[1].replace(",", ""))
                        change = float(cells[2].replace(",", "").replace("+", ""))
                    except ValueError:
                        continue
                    rows.append({
                        "port": port, "grade": grade,
                        "price_usd_per_mt": price, "change_usd": change,
                    })
            return pd.DataFrame(rows)
        except (requests.RequestException, ValueError, ImportError):
            return pd.DataFrame()

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_EVENTS)
    def get_piracy_incidents(days: int = 90) -> pd.DataFrame:
        """Pull recent piracy incidents.

        IMB's Live Piracy Map is JS-rendered, so we use IMO/UKMTO + GDELT as a
        proxy: query GDELT DOC for piracy keywords, geocode by sourcecountry/title
        heuristics. Returns DataFrame with columns: date, lat, lon, title, url.
        """
        articles = APIClient.get_gdelt_articles(
            "piracy OR \"armed robbery at sea\" OR hijack ship", timespan=f"{days*24}H",
        )
        if not articles:
            return pd.DataFrame()
        # Region centroids for crude geocoding when only sourcecountry is known.
        region_hint = {
            "Somalia": (5.0, 49.0),
            "Yemen": (13.5, 45.0),
            "Nigeria": (3.0, 6.5),
            "Indonesia": (1.0, 105.0),
            "Singapore": (1.3, 103.8),
            "Malaysia": (3.5, 101.5),
            "Philippines": (8.0, 124.0),
            "Bangladesh": (22.0, 91.5),
            "India": (15.0, 72.0),
        }
        rows = []
        for a in articles:
            country = a.get("sourcecountry") or ""
            coord = region_hint.get(country)
            if not coord:
                continue
            seen = a.get("seendate", "")
            try:
                dt = datetime.strptime(seen, "%Y%m%dT%H%M%SZ") if seen else datetime.now()
            except ValueError:
                dt = datetime.now()
            rows.append({
                "date": dt,
                "lat": coord[0],
                "lon": coord[1],
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "source_country": country,
            })
        return pd.DataFrame(rows)

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_EVENTS)
    def get_shipping_events(timespan: str = "72H") -> pd.DataFrame:
        """Strictly shipping-relevant events from GDELT DOC API.

        Queries for articles about: port strikes / closures, vessel attacks,
        strait disruptions, container terminal incidents, maritime sanctions,
        cyclones / typhoons threatening ports. Each article is bucketed into
        the 5-category taxonomy and geocoded by chokepoint/port name in title
        (precise) or sourcecountry centroid (coarse).

        Returns columns: date, latitude, longitude, type, subtype, location,
        impact, description, business_impact, url, source.
        """
        # ONE batched English-only query covering all shipping disruption
        # signals. Each returned article is locally classified into one of
        # the five buckets by keyword sniffing of its title.
        # Rationale: 8 sequential GDELT calls would each be rate-limited;
        # one call returns up to 75 articles in under 2 seconds.
        BIG_QUERY = (
            'sourcelang:english '
            '(port OR vessel OR tanker OR shipping OR maritime OR cargo OR '
            'strait OR canal OR harbour OR harbor OR Houthi) AND '
            '(strike OR "closed" OR blocked OR attack OR hijack OR drone OR '
            'missile OR sanctions OR embargo OR typhoon OR cyclone OR '
            'hurricane OR "supply chain" OR "freight rates")'
        )
        # Bucket classification rules — first match wins.
        BUCKET_RULES = [
            ('⚠️ Threat',     'Houthi / Red Sea',  ('houthi', 'red sea')),
            ('⚠️ Threat',     'Vessel attack',     ('hijack', 'attacked', 'missile', 'drone strike', 'piracy', 'pirate')),
            ('🛑 Disruption', 'Port strike',       ('port strike', 'dockworker', 'longshore', 'stevedore', 'union strike')),
            ('🛑 Disruption', 'Port closure',      ('port closed', 'port shut', 'terminal closed', 'harbor closed', 'harbour closed')),
            ('🛑 Disruption', 'Strait disruption', ('suez', 'hormuz', 'bab el-mandeb', 'malacca', 'panama canal', 'strait')),
            ('🌊 Weather',    'Tropical storm',    ('typhoon', 'cyclone', 'hurricane', 'storm shut', 'storm closes')),
            ('🏛 Political',  'Trade sanctions',   ('sanction', 'embargo', 'oil export ban')),
            ('📦 Trade',      'Supply chain shock', ('supply chain', 'container shortage', 'freight rates', 'shipping costs')),
        ]
        # Post-fetch sanity filter: title MUST contain a maritime keyword.
        MARITIME_KEYWORDS = (
            "ship", "vessel", "tanker", "cargo", "container", "freight",
            "port ", "ports ", "harbour", "harbor", "terminal",
            "maritime", "shipping", "strait", "canal", "houthi",
            "dockwork", "longshore", "stevedore", "bunker",
        )

        # ── Geocoding hints: precise (chokepoint/port name in title) > coarse (sourcecountry) ──
        # Precise: lat/lon when title mentions a specific point
        PRECISE_HINTS: dict[str, tuple[float, float]] = {
            "suez canal":       (30.42,  32.35),
            "bab el-mandeb":    (12.58,  43.33),
            "strait of hormuz": (26.35,  56.40),
            "strait of malacca":(2.50,  101.30),
            "singapore strait": (1.25,  103.83),
            "panama canal":     (9.08,  -79.68),
            "english channel":  (50.55,  -1.20),
            "red sea":          (15.50,  41.00),
            "rotterdam":        (51.97,   4.13),
            "shanghai":         (30.96, 121.56),
            "singapore":        (1.35,  103.82),
            "los angeles":      (33.74,-118.21),
            "long beach":       (33.75,-118.21),
            "hamburg":          (53.55,  10.01),
            "antwerp":          (51.30,   4.32),
            "yokohama":         (35.44, 139.66),
            "busan":            (35.10, 129.04),
            "houston":          (29.73, -95.26),
            "jebel ali":        (25.01,  55.06),
            "salalah":          (16.94,  54.00),
            "port said":        (31.26,  32.30),
            "ningbo":           (29.88, 122.02),
            "qingdao":          (36.07, 120.32),
            "guangzhou":        (23.10, 113.44),
            "hong kong":        (22.30, 114.19),
            "tokyo":            (35.61, 139.78),
            "santos":           (-23.95, -46.33),
            "durban":           (-29.87,  31.03),
            "mundra":           (22.75,  69.72),
        }
        # Coarse: country sourcecountry centroid as fallback
        COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
            "United States": (39, -98),  "China": (35, 105),     "Japan": (36, 138),
            "Singapore": (1.3, 103.8),   "Germany": (51, 10),    "Netherlands": (52, 5),
            "United Kingdom": (54, -2),  "France": (46, 2),      "Egypt": (27, 30),
            "Israel": (31, 35),          "Yemen": (15, 47),      "Iran": (32, 53),
            "Saudi Arabia": (25, 45),    "United Arab Emirates": (24, 54),
            "South Korea": (36, 128),    "Taiwan": (24, 121),    "India": (22, 78),
            "Indonesia": (-2, 118),      "Malaysia": (4, 102),   "Philippines": (13, 122),
            "Vietnam": (16, 106),        "Thailand": (15, 101),  "Australia": (-25, 134),
            "Russia": (61, 105),         "Ukraine": (49, 32),    "Turkey": (39, 35),
            "Greece": (39, 22),          "Italy": (42, 12),      "Spain": (40, -4),
            "South Africa": (-29, 24),   "Brazil": (-14, -51),   "Mexico": (23, -102),
            "Canada": (60, -110),        "Somalia": (5, 47),     "Nigeria": (10, 8),
            "Pakistan": (30, 70),        "Bangladesh": (24, 90), "Sri Lanka": (8, 81),
        }

        articles = APIClient.get_gdelt_articles(BIG_QUERY, timespan=timespan)
        rows = []
        for a in articles:
            title = a.get("title") or ""
            title_lower = title.lower()
            # Hard sanity filter — title must mention a maritime concept.
            if not any(kw in title_lower for kw in MARITIME_KEYWORDS):
                continue
            # Classify into bucket
            bucket, subtype = "⚠️ Threat", "Maritime incident"
            for b, s, kws in BUCKET_RULES:
                if any(kw in title_lower for kw in kws):
                    bucket, subtype = b, s
                    break
            # Geocode: precise if a chokepoint/port name is in the title; else
            # fall back to the article's sourcecountry centroid.
            lat = lon = None
            for hint, coord in PRECISE_HINTS.items():
                if hint in title_lower:
                    lat, lon = coord
                    break
            if lat is None:
                sc = a.get("sourcecountry") or ""
                coord = COUNTRY_CENTROIDS.get(sc)
                if coord:
                    lat, lon = coord
            if lat is None:
                continue
            seen = a.get("seendate", "")
            try:
                dt = datetime.strptime(seen, "%Y%m%dT%H%M%SZ") if seen else datetime.now()
            except ValueError:
                dt = datetime.now()
            impact = ("Critical" if bucket == "⚠️ Threat" else
                      "High" if bucket in ("🛑 Disruption", "🌊 Weather") else
                      "Medium")
            rows.append({
                "date": dt,
                "latitude": lat,
                "longitude": lon,
                "type": bucket,
                "subtype": subtype,
                "location": a.get("sourcecountry", "") or "—",
                "impact": impact,
                "description": title[:200],
                "business_impact": f"Source: {a.get('domain','')}",
                "url": a.get("url", ""),
                "source": "GDELT-DOC",
            })

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        # Deduplicate by URL
        df = df.drop_duplicates(subset="url").reset_index(drop=True)
        return df

    # GDELT v2 raw events CSV — auth-free, geocoded, updated every 15 min.
    _GDELT_EVENT_COLS = [
        "GLOBALEVENTID", "SQLDATE", "MonthYear", "Year", "FractionDate",
        "Actor1Code", "Actor1Name", "Actor1CountryCode", "Actor1KnownGroupCode",
        "Actor1EthnicCode", "Actor1Religion1Code", "Actor1Religion2Code",
        "Actor1Type1Code", "Actor1Type2Code", "Actor1Type3Code",
        "Actor2Code", "Actor2Name", "Actor2CountryCode", "Actor2KnownGroupCode",
        "Actor2EthnicCode", "Actor2Religion1Code", "Actor2Religion2Code",
        "Actor2Type1Code", "Actor2Type2Code", "Actor2Type3Code",
        "IsRootEvent", "EventCode", "EventBaseCode", "EventRootCode",
        "QuadClass", "GoldsteinScale", "NumMentions", "NumSources",
        "NumArticles", "AvgTone",
        "Actor1Geo_Type", "Actor1Geo_Fullname", "Actor1Geo_CountryCode",
        "Actor1Geo_ADM1Code", "Actor1Geo_ADM2Code", "Actor1Geo_Lat",
        "Actor1Geo_Long", "Actor1Geo_FeatureID",
        "Actor2Geo_Type", "Actor2Geo_Fullname", "Actor2Geo_CountryCode",
        "Actor2Geo_ADM1Code", "Actor2Geo_ADM2Code", "Actor2Geo_Lat",
        "Actor2Geo_Long", "Actor2Geo_FeatureID",
        "ActionGeo_Type", "ActionGeo_Fullname", "ActionGeo_CountryCode",
        "ActionGeo_ADM1Code", "ActionGeo_ADM2Code", "ActionGeo_Lat",
        "ActionGeo_Long", "ActionGeo_FeatureID",
        "DATEADDED", "SOURCEURL",
    ]

    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_EVENTS)
    def get_gdelt_events_csv(max_files: int = 4) -> pd.DataFrame:
        """Fetch the latest N GDELT v2 export.CSV.zip files (15 min each).

        Returns DataFrame with the canonical events schema:
            date, latitude, longitude, country, event_type, fatalities,
            notes, source, goldstein, num_mentions, avg_tone, url
        Filtered to high-impact rows (QuadClass in {3,4} = verbal/material conflict
        or with abs(GoldsteinScale) >= 4) so we don't drown the map in trivia.
        """
        import io
        import zipfile

        try:
            r = requests.get(GDELT_LASTUPDATE, timeout=10)
            r.raise_for_status()
        except requests.RequestException:
            return pd.DataFrame()

        urls = []
        for line in r.text.strip().splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2].endswith(".export.CSV.zip"):
                urls.append(parts[2])
        if not urls:
            return pd.DataFrame()
        urls = urls[:max_files]

        frames = []
        for url in urls:
            try:
                resp = requests.get(url, timeout=20)
                resp.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    name = zf.namelist()[0]
                    with zf.open(name) as fh:
                        df = pd.read_csv(
                            fh, sep="\t", header=None,
                            names=APIClient._GDELT_EVENT_COLS,
                            dtype=str, on_bad_lines="skip",
                        )
                frames.append(df)
            except (requests.RequestException, zipfile.BadZipFile, ValueError):
                continue
        if not frames:
            return pd.DataFrame()

        raw = pd.concat(frames, ignore_index=True)
        for col in ("ActionGeo_Lat", "ActionGeo_Long", "GoldsteinScale",
                    "AvgTone", "NumMentions", "QuadClass"):
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
        raw = raw.dropna(subset=["ActionGeo_Lat", "ActionGeo_Long"])

        # Strict filter for shipping operators: only keep events that are
        #  - in the disruption-relevant CAMEO root codes (Threaten / Protest /
        #    Force posture / Coerce / Assault / Fight / Mass violence)
        #  - severe (|GoldsteinScale| >= 5)
        #  - corroborated (>=10 article mentions)
        relevant_roots = {"13", "14", "15", "17", "18", "19", "20"}
        signal = raw[
            raw["EventRootCode"].isin(relevant_roots)
            & (raw["GoldsteinScale"].abs() >= 5)
            & (raw["NumMentions"] >= 10)
        ]
        if signal.empty:
            return pd.DataFrame()

        signal = signal.assign(
            date=pd.to_datetime(signal["SQLDATE"], format="%Y%m%d", errors="coerce"),
            latitude=signal["ActionGeo_Lat"],
            longitude=signal["ActionGeo_Long"],
            country=signal["ActionGeo_CountryCode"].fillna(""),
            event_type=signal["EventRootCode"].fillna("00"),
            fatalities=0,  # GDELT doesn't supply per-event fatality counts
            notes=signal["Actor1Name"].fillna("") + " ~ " + signal["Actor2Name"].fillna(""),
            source="GDELT",
            goldstein=signal["GoldsteinScale"],
            num_mentions=signal["NumMentions"],
            avg_tone=signal["AvgTone"],
            url=signal["SOURCEURL"],
        )
        cols = ["date", "latitude", "longitude", "country", "event_type",
                "fatalities", "notes", "source", "goldstein",
                "num_mentions", "avg_tone", "url"]
        return signal[cols].reset_index(drop=True)


class DataProcessor:
    """Process and analyze fetched data"""

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
