"""
dynamic_status.py — Compute shipping/port/regional status from live API data.

All functions accept events_df.to_json() as input (a JSON string) so that
Streamlit's @st.cache_data can hash them — DataFrames are not hashable.
"""

import math
from io import StringIO
import pandas as pd
import streamlit as st
from datetime import datetime

from api_config import (
    STRAIT_COORDINATES, CRITICAL_PORTS, KEY_REGIONS,
    CACHE_TTL_NEWS, CACHE_TTL_EVENTS,
)
from api_integrations import APIClient


# ── Internal helpers ──────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon pairs."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(min(1.0, a)))


def _events_within_radius(
    events_df: pd.DataFrame,
    center_lat: float,
    center_lon: float,
    radius_km: float,
) -> pd.DataFrame:
    """Return rows of events_df whose coordinates are within radius_km."""
    if events_df.empty:
        return events_df
    mask = events_df.apply(
        lambda r: _haversine_km(r["latitude"], r["longitude"], center_lat, center_lon) <= radius_km,
        axis=1,
    )
    return events_df[mask]


def _classify_topic(title: str) -> str:
    title_lower = title.lower()
    if any(w in title_lower for w in ["ship", "vessel", "port", "strait", "canal", "freight", "maritime", "cargo"]):
        return "shipping"
    if any(w in title_lower for w in ["attack", "military", "strike", "conflict", "war", "missile", "drone", "troops", "invasion"]):
        return "conflict"
    if any(w in title_lower for w in ["storm", "cyclone", "hurricane", "typhoon", "weather", "flood", "earthquake"]):
        return "weather"
    if any(w in title_lower for w in ["sanction", "tariff", "trade", "export", "import", "supply chain", "economic"]):
        return "trade"
    return "other"


# ── Public functions ──────────────────────────────────────────────────────────

@st.cache_data(ttl=CACHE_TTL_EVENTS)
def compute_shipping_status(events_json: str) -> pd.DataFrame:
    """
    Derive strait/chokepoint status from:
    - ACLED events within radius_km of each strait
    - GDELT article mentions of disruption/attack/delay

    Returns DataFrame: Route, Status, Traffic Level, Average Delay,
                        Cost Impact, Risk Score, Nearby Events, News Signals
    """
    try:
        events_df = pd.read_json(StringIO(events_json))
    except Exception:
        events_df = pd.DataFrame(columns=["latitude", "longitude", "impact"])

    # Ensure required columns exist
    for col in ["latitude", "longitude", "impact"]:
        if col not in events_df.columns:
            events_df[col] = 0 if col != "impact" else "Low"

    TRAFFIC_LEVELS = {
        "Suez Canal":        "High",
        "Strait of Hormuz":  "Critical",
        "Singapore Strait":  "Very High",
        "Panama Canal":      "High",
        "English Channel":   "Very High",
    }

    rows = []
    for strait_name, coords in STRAIT_COORDINATES.items():
        nearby = _events_within_radius(
            events_df, coords["lat"], coords["lon"], coords["radius_km"]
        )
        critical_nearby = len(nearby[nearby["impact"] == "Critical"]) if len(nearby) > 0 else 0
        high_nearby     = len(nearby[nearby["impact"] == "High"]) if len(nearby) > 0 else 0

        # GDELT news signal for this strait
        articles = APIClient.get_gdelt_articles(
            f'"{strait_name}" disruption OR attack OR delay OR closed OR threat',
            timespan="48h",
        )
        news_signal = len(articles)

        # Composite risk score 0–100
        risk_score = min(100, critical_nearby * 25 + high_nearby * 10 + news_signal * 3)

        if risk_score >= 70:
            status  = "Critical - Avoid"
            delay_h = 24 + (risk_score - 70) // 2
            cost_pct = f"+{30 + (risk_score - 70) // 5}%"
        elif risk_score >= 40:
            status  = "Operational - High Risk"
            delay_h = 6 + (risk_score - 40) // 5
            cost_pct = f"+{10 + (risk_score - 40) // 4}%"
        elif risk_score >= 15:
            status  = "Operational - Alert"
            delay_h = 1 + risk_score // 15
            cost_pct = f"+{max(1, risk_score // 5)}%"
        else:
            status  = "Operational"
            delay_h = 0
            cost_pct = "+0%"

        rows.append({
            "Route":         strait_name,
            "Status":        status,
            "Traffic Level": TRAFFIC_LEVELS.get(strait_name, "High"),
            "Average Delay": f"{delay_h} hours" if delay_h > 0 else "0 hours",
            "Cost Impact":   cost_pct,
            "Risk Score":    risk_score,
            "Nearby Events": len(nearby),
            "News Signals":  news_signal,
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL_EVENTS)
def compute_risk_summary(events_json: str) -> pd.DataFrame:
    """
    Derive regional risk levels from ACLED event proximity to KEY_REGIONS.

    Returns DataFrame: Region, Risk Level, Active Events, Affected Routes, Business Impact
    """
    try:
        events_df = pd.read_json(StringIO(events_json))
    except Exception:
        events_df = pd.DataFrame(columns=["latitude", "longitude", "impact"])

    for col in ["latitude", "longitude", "impact"]:
        if col not in events_df.columns:
            events_df[col] = 0 if col != "impact" else "Low"

    REGION_ROUTES = {
        "Middle East":         ["Suez Canal", "Strait of Hormuz"],
        "Eastern Ukraine":     ["English Channel"],
        "South China Sea":     ["Singapore Strait"],
        "Red Sea-Suez":        ["Suez Canal"],
        "Persian Gulf":        ["Strait of Hormuz"],
        "Strait of Malaysia":  ["Singapore Strait"],
    }

    rows = []
    for region, coords in KEY_REGIONS.items():
        radius_km = coords.get("radius", 500)
        nearby = _events_within_radius(
            events_df, coords["lat"], coords["lon"], radius_km
        )

        critical = len(nearby[nearby["impact"] == "Critical"]) if len(nearby) > 0 else 0
        high     = len(nearby[nearby["impact"] == "High"]) if len(nearby) > 0 else 0
        total    = len(nearby)

        score = critical * 3 + high * 2 + (total - critical - high)

        if score >= 6:
            risk_level = "Critical"
            biz_impact = "Very High"
        elif score >= 4:
            risk_level = "High"
            biz_impact = "High"
        elif score >= 2:
            risk_level = "Medium"
            biz_impact = "Medium"
        else:
            risk_level = "Low"
            biz_impact = "Low"

        affected_routes = REGION_ROUTES.get(region, [])

        rows.append({
            "Region":          region,
            "Risk Level":      risk_level,
            "Active Events":   total,
            "Affected Routes": len(affected_routes),
            "Business Impact": biz_impact,
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL_EVENTS)
def compute_port_congestion(events_json: str) -> pd.DataFrame:
    """
    Derive port congestion from GDELT news + ACLED events + OpenWeather conditions.

    Returns DataFrame: Port, Congestion, Score, ACLED Events,
                        News Articles, Weather Alert, Lat, Lon
    """
    try:
        events_df = pd.read_json(StringIO(events_json))
    except Exception:
        events_df = pd.DataFrame(columns=["latitude", "longitude", "impact"])

    for col in ["latitude", "longitude", "impact"]:
        if col not in events_df.columns:
            events_df[col] = 0 if col != "impact" else "Low"

    rows = []
    for port_name, coords in CRITICAL_PORTS.items():
        lat, lon = coords["lat"], coords["lon"]

        # GDELT news articles mentioning this port with congestion keywords
        articles = APIClient.get_gdelt_articles(
            f'"{port_name}" port (congestion OR delay OR backlog OR queue OR disruption)',
            timespan="48h",
        )

        # ACLED events within 100 km
        nearby_events = _events_within_radius(events_df, lat, lon, 100)

        # OpenWeather conditions
        weather = APIClient.get_port_weather(lat, lon)
        weather_alert = False
        weather_desc = "N/A"
        wind_ms = 0.0
        if weather:
            wind_ms = weather.get("wind_speed_ms", 0)
            visibility = weather.get("visibility_m", 10000)
            weather_alert = wind_ms > 15 or visibility < 2000
            weather_desc = weather.get("weather_desc", "N/A").title()

        # Composite score
        score = min(100, len(articles) * 2 + len(nearby_events) * 15 + (20 if weather_alert else 0))

        if score >= 70:   congestion = "Critical"
        elif score >= 45: congestion = "High"
        elif score >= 20: congestion = "Medium"
        else:             congestion = "Low"

        rows.append({
            "Port":          port_name,
            "Congestion":    congestion,
            "Score":         score,
            "ACLED Events":  len(nearby_events),
            "News Articles": len(articles),
            "Weather":       weather_desc,
            "Wind (m/s)":    round(wind_ms, 1),
            "Weather Alert": "⚠️ Yes" if weather_alert else "✅ No",
            "Lat":           lat,
            "Lon":           lon,
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL_NEWS)
def get_news_feed(keywords: str = "shipping port conflict military supply chain trade sanctions") -> pd.DataFrame:
    """
    Merge Guardian + NewsAPI articles into a unified, deduplicated, topic-classified feed.
    Returns DataFrame: title, source, date, url, topic  (sorted date desc)
    """
    records = []

    # ── Guardian ──────────────────────────────────────────────────────────────
    guardian_df = APIClient.get_guardian_news(keywords=keywords)
    if len(guardian_df) > 0:
        for _, row in guardian_df.iterrows():
            title = row.get("webTitle", "")
            url   = row.get("webUrl", "#")
            date_str = row.get("webPublicationDate", "")
            try:
                date = pd.to_datetime(date_str, utc=True)
            except Exception:
                date = pd.Timestamp.now(tz="UTC")
            records.append({
                "title":  title,
                "source": "The Guardian",
                "date":   date,
                "url":    url,
                "topic":  _classify_topic(title),
            })

    # ── NewsAPI ───────────────────────────────────────────────────────────────
    newsapi_df = APIClient.get_news_alerts(keywords=keywords)
    if len(newsapi_df) > 0:
        for _, row in newsapi_df.iterrows():
            title = row.get("title", "") or ""
            url   = row.get("url", "#") or "#"
            date  = row.get("date", pd.Timestamp.now(tz="UTC"))
            src   = ""
            if isinstance(row.get("source"), dict):
                src = row["source"].get("name", "NewsAPI")
            else:
                src = str(row.get("source", "NewsAPI"))
            records.append({
                "title":  title,
                "source": src,
                "date":   date,
                "url":    url,
                "topic":  _classify_topic(title),
            })

    if not records:
        return pd.DataFrame(columns=["title", "source", "date", "url", "topic"])

    df = pd.DataFrame(records)

    # Deduplicate by normalized title
    df["_title_key"] = df["title"].str.lower().str.strip().str[:80]
    df = df.drop_duplicates(subset="_title_key").drop(columns="_title_key")

    # Sort newest first
    df = df.sort_values("date", ascending=False).reset_index(drop=True)

    return df
