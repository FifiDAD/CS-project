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
    OPEN_METEO_MARINE, SHIPANDBUNKER_URL,
)

_GDELT_HEADERS = {"User-Agent": "LogisticsDashboard/1.0 (contact: ops@example.com)"}

# Shared HTTP session for connection reuse. Keep-alive + TLS handshake reuse
# meaningfully shaves cold-load time across the many sequential calls to
# GDELT, FRED, OpenWeather, Open-Meteo, NewsAPI, Guardian, etc. Behaviour
# is identical to module-level _SESSION.get() because requests_cache (when
# installed above) patches both functions and sessions.
_SESSION = requests.Session()


def _gdelt_get(url: str, params: dict, timeout: int = 10) -> requests.Response | None:
    """GDELT throttles to 1 req / 5 sec and gets stricter after repeated 429s.
    Retry with growing back-off (6s, 12s, 20s)."""
    import time as _t
    for attempt, nap in enumerate((6, 12, 20)):
        try:
            # Send every GDELT request through the same retry helper.
            r = _SESSION.get(url, params=params, headers=_GDELT_HEADERS, timeout=timeout)
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
            # Timeline mode returns counts over time, not article rows.
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
                # Missing key means this source is skipped.
                return pd.DataFrame()

            url = "https://newsapi.org/v2/everything"
            params = {
                'q': keywords,
                'sortBy': 'publishedAt',
                'language': 'en',
                'pageSize': 50,
                'apiKey': NEWSAPI_KEY
            }

            response = _SESSION.get(url, params=params, timeout=5)
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

            response = _SESSION.get(url, params=params, timeout=10)
            response.raise_for_status()

            results = response.json().get('response', {}).get('results', [])
            if results:
                df = pd.DataFrame(results)
                return df
            return pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    # ── USGS Earthquakes (no key, M4.5+ last 7 days) ─────────────────────────
    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_EVENTS)
    def get_earthquakes(min_mag: float = 4.5, days: int = 7) -> pd.DataFrame:
        """USGS Earthquake Hazards Program — recent significant quakes.

        Free, no key. Returns canonical event-schema columns so the result
        can be concatenated into the main events feed and rendered on the
        globe with the existing Event layer.

        Filters to coastal-relevant quakes (within ~300 km of any port in
        port_baselines) so we don't drown the map in continental tremors.
        """
        feed = {
            (4.5, 7):  "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson",
            (2.5, 1):  "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson",
        }.get((min_mag, days),
              "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson")
        try:
            r = _SESSION.get(feed, timeout=15)
            r.raise_for_status()
            features = r.json().get("features", [])
        except (requests.RequestException, ValueError):
            return pd.DataFrame()

        from port_baselines import PORT_BASELINES
        from math import asin, cos, radians, sin, sqrt
        port_pts = [(p["lat"], p["lon"]) for p in PORT_BASELINES.values()]

        def _near_port(lat: float, lon: float, max_km: float = 500.0) -> bool:
            # Keep only quakes close enough to matter for ports.
            for plat, plon in port_pts:
                dphi = radians(plat - lat)
                dlam = radians(plon - lon)
                a = (sin(dphi / 2) ** 2
                     + cos(radians(lat)) * cos(radians(plat)) * sin(dlam / 2) ** 2)
                d = 6371.0 * 2 * asin(min(1.0, sqrt(a)))
                if d <= max_km:
                    return True
            return False

        rows = []
        for f in features:
            p = f.get("properties") or {}
            g = f.get("geometry") or {}
            coords = g.get("coordinates") or []
            if len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            mag = float(p.get("mag") or 0.0)
            if mag < min_mag:
                continue
            if not _near_port(lat, lon):
                continue
            ts_ms = p.get("time") or 0
            try:
                date = pd.to_datetime(int(ts_ms), unit="ms", utc=True)
            except (TypeError, ValueError):
                date = pd.Timestamp.now(tz="UTC")
            place = p.get("place", "") or ""
            url   = p.get("url", "") or ""
            impact = ("Critical" if mag >= 6.5 else
                      "High"     if mag >= 5.5 else
                      "Medium"   if mag >= 4.5 else
                      "Low")
            rows.append({
                "date":            date,
                "latitude":        lat,
                "longitude":       lon,
                "type":            "🌋 Seismic",
                "subtype":         f"M{mag:.1f} earthquake",
                "location":        place,
                "impact":          impact,
                "description":     f"M{mag:.1f} · {place}",
                "business_impact": (f"Tsunami / port-shutdown risk for nearby terminals"
                                    if mag >= 6.0 else
                                    f"Monitoring · low immediate port impact"),
                "url":             url,
                "source":          "USGS",
            })
        return pd.DataFrame(rows)

    # ── Maritime industry RSS (no key) ───────────────────────────────────────
    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_NEWS)
    def get_maritime_rss() -> pd.DataFrame:
        """Pull recent articles from maritime-industry RSS feeds.

        Free, no key. One slow/dead feed doesn't poison the others — each is
        wrapped individually. Returns DataFrame: title, source, date, url.
        """
        try:
            import feedparser
        except ImportError:
            return pd.DataFrame()
        from api_config import MARITIME_RSS_FEEDS

        rows = []
        for source_name, url in MARITIME_RSS_FEEDS:
            # One broken RSS feed should not stop the others.
            try:
                parsed = feedparser.parse(url, request_headers=_GDELT_HEADERS)
            except Exception:  # noqa: BLE001
                continue
            for entry in (parsed.entries or [])[:25]:
                title = (entry.get("title") or "").strip()
                link  = entry.get("link") or ""
                if not title or not link:
                    continue
                # feedparser exposes parsed dates as time.struct_time
                pub_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub_struct:
                    try:
                        date = pd.Timestamp(*pub_struct[:6], tz="UTC")
                    except Exception:  # noqa: BLE001
                        date = pd.Timestamp.now(tz="UTC")
                else:
                    date = pd.Timestamp.now(tz="UTC")
                rows.append({
                    "title":  title,
                    "source": source_name,
                    "date":   date,
                    "url":    link,
                })
        if not rows:
            return pd.DataFrame(columns=["title", "source", "date", "url"])
        return pd.DataFrame(rows)

    # ── GNews (free tier 100 req/day, requires key) ──────────────────────────
    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_NEWS)
    def get_gnews(query: str = "shipping OR maritime OR port OR sanctions") -> pd.DataFrame:
        """Fetch articles from GNews. Requires GNEWS_KEY env var.

        Returns empty DataFrame when the key is unset or the call fails.
        Sign up at https://gnews.io/ for a free key (100 req/day).
        """
        from api_config import GNEWS_KEY
        if not GNEWS_KEY:
            return pd.DataFrame()
        try:
            r = _SESSION.get(
                "https://gnews.io/api/v4/search",
                params={
                    "q":     query,
                    "lang":  "en",
                    "max":   25,
                    "token": GNEWS_KEY,
                },
                timeout=10,
            )
            r.raise_for_status()
            articles = r.json().get("articles", [])
        except (requests.RequestException, ValueError):
            return pd.DataFrame()

        rows = []
        for a in articles:
            title = (a.get("title") or "").strip()
            url   = a.get("url") or ""
            if not title or not url:
                continue
            try:
                date = pd.to_datetime(a.get("publishedAt"), utc=True)
            except Exception:  # noqa: BLE001
                date = pd.Timestamp.now(tz="UTC")
            src = (a.get("source") or {}).get("name", "GNews")
            rows.append({"title": title, "source": src, "date": date, "url": url})
        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["title", "source", "date", "url"]
        )

    # ── NewsData.io (free tier 200 req/day, requires key) ────────────────────
    @staticmethod
    @st.cache_data(ttl=CACHE_TTL_NEWS)
    def get_newsdata(query: str = "shipping OR maritime OR port OR sanctions") -> pd.DataFrame:
        """Fetch articles from NewsData.io. Requires NEWSDATA_KEY env var.

        Returns empty DataFrame when the key is unset or the call fails.
        Sign up at https://newsdata.io/ for a free key (200 req/day).
        """
        from api_config import NEWSDATA_KEY
        if not NEWSDATA_KEY:
            return pd.DataFrame()
        try:
            r = _SESSION.get(
                "https://newsdata.io/api/1/news",
                params={
                    "q":        query,
                    "language": "en",
                    "apikey":   NEWSDATA_KEY,
                },
                timeout=10,
            )
            r.raise_for_status()
            results = r.json().get("results", []) or []
        except (requests.RequestException, ValueError):
            return pd.DataFrame()

        rows = []
        for a in results[:30]:
            title = (a.get("title") or "").strip()
            url   = a.get("link") or ""
            if not title or not url:
                continue
            try:
                date = pd.to_datetime(a.get("pubDate"), utc=True)
            except Exception:  # noqa: BLE001
                date = pd.Timestamp.now(tz="UTC")
            src = a.get("source_id") or a.get("source_name") or "NewsData"
            rows.append({"title": title, "source": src, "date": date, "url": url})
        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["title", "source", "date", "url"]
        )

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

            response = _SESSION.get(url, params=params, timeout=5)
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

            response = _SESSION.get(url, params=params, timeout=5)
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

            response = _SESSION.get(url, timeout=5)
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
            response = _SESSION.get(OPENWEATHER_URL, params=params, timeout=5)
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

            response = _SESSION.get(url, params=params, timeout=5)
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
            response = _SESSION.get(url, timeout=5)
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
            r = _SESSION.get(OPEN_METEO_MARINE, params=params, timeout=10)
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
    @st.cache_data(ttl=3600)
    def get_wind_at(lat: float, lon: float) -> dict:
        """Open-Meteo Forecast — surface wind speed/direction. Free, no key.

        Returns {"wind_speed_ms": float|None, "wind_dir_deg": float|None}.
        Empty dict on failure. Cached 1h (Open-Meteo updates hourly).
        """
        try:
            r = _SESSION.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "wind_speed_10m,wind_direction_10m",
                    "wind_speed_unit": "ms",
                    "timezone": "UTC",
                },
                timeout=10,
            )
            r.raise_for_status()
            cur = r.json().get("current", {}) or {}
            return {
                "wind_speed_ms": cur.get("wind_speed_10m"),
                "wind_dir_deg":  cur.get("wind_direction_10m"),
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
            # Scrape all supported fuel tables from the same page.
            r = _SESSION.get(
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
        """Authoritative piracy / vessel-attack incidents.

        Source: NGA Maritime Safety Broadcast Warnings (msi.nga.mil) — the
        official US government channel for navigational hazards including
        piracy, hijacking, and armed robbery at sea. Real coordinates are
        parsed from each warning's free-text body.

        Returns DataFrame with columns: date, lat, lon, title, url,
        source_country (NAVAREA designator). Only rows with parsed
        coordinates are returned — no country-centroid fallbacks.
        """
        import re
        from nga_warnings import fetch_warnings

        warnings_df = fetch_warnings()
        if warnings_df is None or len(warnings_df) == 0:
            return pd.DataFrame()

        pat = re.compile(r"\b(pirac|hijack|armed robbery|boarded|skiff)\b", re.I)
        rows = []
        for _, w in warnings_df.iterrows():
            text = w.get("text", "") or ""
            # Keep warnings that look like piracy or vessel-attack reports.
            if not pat.search(text):
                continue
            if float(w.get("severity", 0.0) or 0.0) < 0.6:
                continue
            lats = w.get("lats") or []
            lons = w.get("lons") or []
            if not lats or not lons:
                continue
            issued = w.get("issued") or ""
            try:
                dt = pd.to_datetime(issued, errors="coerce")
                if pd.isna(dt):
                    dt = datetime.now()
                else:
                    dt = dt.to_pydatetime() if hasattr(dt, "to_pydatetime") else dt
            except Exception:  # noqa: BLE001
                dt = datetime.now()
            title = text.strip().replace("\n", " ")
            if len(title) > 140:
                title = title[:137] + "…"
            for lat, lon in zip(lats, lons):
                rows.append({
                    "date": dt,
                    "lat": float(lat),
                    "lon": float(lon),
                    "title": title,
                    "url": "",
                    "source_country": w.get("navArea", "") or "",
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
        # GDELT DOC rejects very long boolean queries ("Your query was too
        # short or too long"). We instead issue several focused, English-only
        # queries — each one returns up to 75 articles — and merge the
        # results, deduplicating by URL further down.
        QUERIES = (
            'sourcelang:english (port OR harbor OR harbour OR terminal) AND (strike OR "closed" OR blocked OR closure)',
            'sourcelang:english (vessel OR tanker OR ship OR cargo) AND (attack OR hijack OR drone OR missile)',
            'sourcelang:english (strait OR canal OR Houthi) AND (attack OR drone OR missile OR blocked OR closed)',
            'sourcelang:english (shipping OR maritime OR freight) AND (sanctions OR embargo OR "supply chain")',
            'sourcelang:english (port OR shipping OR maritime) AND (typhoon OR cyclone OR hurricane)',
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
        # Human-readable labels for the hint matches — used as the event's
        # `location` so a Houthi attack covered by an Indian newspaper labels
        # as "Red Sea / Yemen" rather than "India".
        HINT_LABELS: dict[str, str] = {
            "suez canal":       "Suez Canal / Egypt",
            "bab el-mandeb":    "Bab el-Mandeb / Yemen",
            "strait of hormuz": "Strait of Hormuz / Iran",
            "strait of malacca":"Strait of Malacca",
            "singapore strait": "Singapore Strait",
            "panama canal":     "Panama Canal",
            "english channel":  "English Channel",
            "red sea":          "Red Sea / Yemen",
            "rotterdam":        "Rotterdam, NL",
            "shanghai":         "Shanghai, CN",
            "singapore":        "Singapore",
            "los angeles":      "Los Angeles, US",
            "long beach":       "Long Beach, US",
            "hamburg":          "Hamburg, DE",
            "antwerp":          "Antwerp, BE",
            "yokohama":         "Yokohama, JP",
            "busan":            "Busan, KR",
            "houston":          "Houston, US",
            "jebel ali":        "Jebel Ali, AE",
            "salalah":          "Salalah, OM",
            "port said":        "Port Said, EG",
            "ningbo":           "Ningbo, CN",
            "qingdao":          "Qingdao, CN",
            "guangzhou":        "Guangzhou, CN",
            "hong kong":        "Hong Kong",
            "tokyo":            "Tokyo, JP",
            "santos":           "Santos, BR",
            "durban":           "Durban, ZA",
            "mundra":           "Mundra, IN",
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

        articles: list[dict] = []
        _seen_urls: set[str] = set()
        for _q in QUERIES:
            # Run several focused queries and merge unique article URLs.
            for _a in APIClient.get_gdelt_articles(_q, timespan=timespan) or []:
                _u = _a.get("url") or ""
                if _u and _u not in _seen_urls:
                    _seen_urls.add(_u)
                    articles.append(_a)
        rows = []
        for a in articles:
            title = a.get("title") or ""
            title_lower = title.lower()
            # Skip articles that do not mention a maritime topic.
            # Hard sanity filter — title must mention a maritime concept.
            if not any(kw in title_lower for kw in MARITIME_KEYWORDS):
                continue
            # Classify into bucket. When no rule matches the title we default
            # to a soft "Shipping news" rather than escalating every untyped
            # article into a Threat — those defaults were the source of
            # spurious "armed conflict" markers on the dashboard.
            bucket, subtype = "📦 Trade", "Shipping news"
            for b, s, kws in BUCKET_RULES:
                if any(kw in title_lower for kw in kws):
                    bucket, subtype = b, s
                    break
            # Geocode: precise if a chokepoint/port name is in the title; else
            # fall back to the article's sourcecountry centroid.
            lat = lon = None
            matched_hint: str | None = None
            for hint, coord in PRECISE_HINTS.items():
                if hint in title_lower:
                    lat, lon = coord
                    matched_hint = hint
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
                dt = (pd.to_datetime(seen, format="%Y%m%dT%H%M%SZ", utc=True)
                      if seen else pd.Timestamp.now(tz="UTC"))
            except (ValueError, TypeError):
                dt = pd.Timestamp.now(tz="UTC")
            # Threat severity: only the explicitly-named subtypes earn
            # Critical. The generic "Maritime incident" fallback (kept for
            # backward compatibility) drops to High.
            if bucket == "⚠️ Threat":
                impact = "Critical" if subtype in (
                    "Houthi / Red Sea", "Vessel attack",
                ) else "High"
            elif bucket in ("🛑 Disruption", "🌊 Weather"):
                impact = "High"
            elif bucket == "🏛 Political":
                impact = "Medium"
            else:
                impact = "Low"
            domain = a.get("domain", "") or ""
            rows.append({
                "date": dt,
                "latitude": lat,
                "longitude": lon,
                "type": bucket,
                "subtype": subtype,
                "location": (HINT_LABELS.get(matched_hint, "") if matched_hint
                             else (a.get("sourcecountry", "") or "—")),
                "impact": impact,
                "description": title[:200],
                "business_impact": f"Source: {domain}",
                "url": a.get("url", ""),
                "source": "GDELT-DOC",
                "hint_key": matched_hint or "",
                "domain": domain,
            })

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        # Deduplicate by URL
        df = df.drop_duplicates(subset="url").reset_index(drop=True)

        # Multi-source clustering: an event qualifies for the map only if
        # at least two distinct news domains cover it. We group by
        # (hint_key, subtype) — same precise location + same threat type —
        # and count unique domains. Events without a precise hint never
        # get a cluster_id and never reach the map.
        df["cluster_id"] = (
            df["hint_key"].astype(str) + "::" + df["subtype"].astype(str)
        )
        df.loc[df["hint_key"] == "", "cluster_id"] = ""
        if (df["cluster_id"] != "").any():
            cluster_counts = (
                df[df["cluster_id"] != ""]
                .groupby("cluster_id")["domain"].nunique()
                .to_dict()
            )
            df["n_sources"] = df["cluster_id"].map(cluster_counts).fillna(1).astype(int)
        else:
            df["n_sources"] = 1
        df["on_map"] = df["n_sources"] >= 2
        return df


class DataProcessor:
    """Process and analyze fetched data"""

    @staticmethod
    def calculate_regional_risk(events_df, regions=KEY_REGIONS):
        """Calculate risk score by region"""
        risk_scores = {}

        for region, coords in regions.items():
            # Count events close to each configured region center.
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
