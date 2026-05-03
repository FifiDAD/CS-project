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
from nga_warnings import fetch_warnings as _fetch_nga_warnings, severity_for_chokepoint
from ais_consumer import (
    CHOKEPOINT_BBOXES as _AIS_BBOXES,
    transits_24h as _ais_transits_24h,
    transits_baseline as _ais_baseline,
)


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
    - Geo-filtered conflict events (GDELT) within radius_km of each strait
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
        "Bab el-Mandeb":     "High",
        "Strait of Hormuz":  "Critical",
        "Bosphorus":         "High",
        "Strait of Malacca": "Very High",
        "Singapore Strait":  "Very High",
        "Taiwan Strait":     "Very High",
        "Panama Canal":      "High",
        "English Channel":   "Very High",
    }

    # Pull NGA broadcast warnings once for all chokepoints (cached 15 min).
    nga_df = _fetch_nga_warnings()
    nga_alive = len(nga_df) > 0

    rows = []
    for strait_name, coords in STRAIT_COORDINATES.items():
        nearby = _events_within_radius(
            events_df, coords["lat"], coords["lon"], coords["radius_km"]
        )
        critical_nearby = len(nearby[nearby["impact"] == "Critical"]) if len(nearby) > 0 else 0
        high_nearby     = len(nearby[nearby["impact"] == "High"]) if len(nearby) > 0 else 0

        # GDELT news signal — multi-alias OR query catches articles that don't
        # use the canonical strait name (e.g. "Persian Gulf tensions").
        aliases = coords.get("aliases") or [f'"{strait_name}"']
        alias_clause = " OR ".join(aliases)
        articles = APIClient.get_gdelt_articles(
            f"({alias_clause}) AND (disruption OR attack OR delay OR closed OR blockade OR threat OR strike OR mine OR jamming)",
            timespan="48h",
        )
        news_signal = len(articles)

        # NGA Maritime Safety warnings — authoritative closure/hazard signal.
        nga_sev, nga_count = severity_for_chokepoint(
            nga_df, coords["lat"], coords["lon"], coords["radius_km"]
        )

        # AIS physical-signal: transits today vs 7-day rolling median for this
        # bbox. We only apply it once we have enough history (≥3 days) AND a
        # baseline of ≥20 vessels — otherwise the comparison is noise.
        bbox = _AIS_BBOXES.get(strait_name)
        ais_transits = _ais_transits_24h(bbox) if bbox else 0
        ais_base     = _ais_baseline(bbox) if bbox else None
        if ais_base is not None and ais_base >= 20:
            ais_drop = max(0.0, 1.0 - ais_transits / ais_base)
            ais_points = int(round(ais_drop * 50))    # 50% drop → +25, 100% → +50
        else:
            ais_drop = None
            ais_points = 0

        # Feed-alive check: at least one upstream source produced data.
        feed_alive = (
            (len(events_df) > 0) or (news_signal > 0) or nga_alive or ais_transits > 0
        )

        # Composite risk score 0–100. NGA severity dominates (closure-class
        # warning alone pins ≥80). AIS drop adds physical confirmation.
        risk_score = min(
            100,
            int(round(nga_sev * 80))
            + ais_points
            + critical_nearby * 25
            + high_nearby * 10
            + news_signal * 3
        )

        if not feed_alive:
            status  = "Unavailable"
            delay_h = 0
            cost_pct = "—"
            risk_score = 0
        elif risk_score >= 70:
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
            "Average Delay": "—" if status == "Unavailable" else (f"{delay_h} hours" if delay_h > 0 else "0 hours"),
            "Cost Impact":   cost_pct,
            "Risk Score":    risk_score,
            "Nearby Events": len(nearby),
            "News Signals":  news_signal,
            "NGA Warnings":  nga_count,
            "AIS 24h":       ais_transits,
            "AIS Baseline":  round(ais_base, 1) if ais_base is not None else "—",
            "AIS Drop":      f"{int(ais_drop * 100)}%" if ais_drop is not None else "—",
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL_EVENTS)
def compute_risk_summary(events_json: str) -> pd.DataFrame:
    """
    Derive regional risk levels from event proximity to KEY_REGIONS.

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

        if events_df.empty:
            risk_level = "Unavailable"
            biz_impact = "—"
        elif score >= 6:
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


def _ais_anchored_count(ais_df: pd.DataFrame, lat: float, lon: float, radius_km: float) -> int:
    """Count AIS positions within radius_km that are at anchor (SOG < 0.5 kn)."""
    if ais_df is None or len(ais_df) == 0:
        return 0
    sub = ais_df[ais_df["sog_kn"].fillna(0) < 0.5]
    if len(sub) == 0:
        return 0
    # Crude bounding box pre-filter to skip haversine on far rows
    dlat = radius_km / 111.0
    box = sub[(sub["lat"].between(lat - dlat, lat + dlat))
              & (sub["lon"].between(lon - dlat * 2, lon + dlat * 2))]
    if len(box) == 0:
        return 0
    inside = box.apply(
        lambda r: _haversine_km(r["lat"], r["lon"], lat, lon) <= radius_km, axis=1
    )
    return int(inside.sum())


@st.cache_data(ttl=CACHE_TTL_EVENTS)
def compute_port_congestion(events_json: str) -> pd.DataFrame:
    """
    Real-signal port congestion for the top 30+ monitored world ports.

    Inputs (all real, no placeholders):
      - AIS at-anchor queue (vessels with SOG < 0.5 kn within port anchorage)
        from AISStream.io WebSocket → SQLite (ais_consumer.latest_positions)
      - Marine weather at port (Open-Meteo Marine: wave height, wind, swell)
      - Recent GDELT news mentioning the port + disruption keywords (single
        batched query, attributed by name match — NOT 30 sequential calls)
      - Conflict events from the events_json feed within 100 km (real GDELT)

    Output column 'Expected Delay (days)' is computed as:
        (queue / berths) * baseline_turnaround * weather_multiplier
    Score is delay-derived rather than a hand-tuned weight sum.

    AIS coverage may not include every port immediately — when no live AIS
    is yet available for a port the queue is reported as None (UI shows
    "Collecting…") rather than a fake zero.
    """
    from port_baselines import PORT_BASELINES
    from ais_consumer import latest_positions

    try:
        events_df = pd.read_json(StringIO(events_json))
    except Exception:
        events_df = pd.DataFrame(columns=["latitude", "longitude", "impact"])
    for col in ["latitude", "longitude", "impact"]:
        if col not in events_df.columns:
            events_df[col] = 0 if col != "impact" else "Low"

    # ── Single batched GDELT call for all ports ──────────────────────────────
    port_names = list(PORT_BASELINES.keys())
    quoted = " OR ".join(f'"{n.split(" ")[0]}"' for n in port_names[:25])  # GDELT query length cap
    gdelt_query = (
        f"({quoted}) AND port AND (congestion OR delay OR backlog OR queue OR disruption)"
    )
    articles = APIClient.get_gdelt_articles(gdelt_query, timespan="48H")

    # Pre-index articles by lowercase title text for substring matching
    article_titles = [(a.get("title") or "").lower() for a in articles]

    # ── Live AIS snapshot (≤10 min old) ──────────────────────────────────────
    ais_df = latest_positions(max_age_sec=600)

    rows = []
    for port_name, ref in PORT_BASELINES.items():
        lat = ref["lat"]; lon = ref["lon"]
        radius = ref["anchorage_radius_km"]
        berths = ref["berths"]
        baseline_d = ref["baseline_turnaround_days"]

        # 1. Real anchored-vessel count
        if len(ais_df) > 0:
            queue = _ais_anchored_count(ais_df, lat, lon, radius)
            queue_label: str | int = queue
        else:
            queue = None
            queue_label = "Collecting…"

        # 2. Real marine weather (waves, swell, current)
        marine = APIClient.get_marine_weather(lat, lon) or {}
        wave_m = marine.get("wave_height_m") or 0.0
        swell_m = marine.get("swell_height_m") or 0.0
        # Hazard if seas above 3 m or swell above 2.5 m
        wx_hazard = (wave_m or 0) > 3.0 or (swell_m or 0) > 2.5
        wx_mult = 1.5 if wx_hazard else 1.0
        wx_label = f"Wave {wave_m:.1f}m / Swell {swell_m:.1f}m" if marine else "n/a"

        # 3. News signal — count articles whose title mentions this port name
        port_first = port_name.split(" ")[0].lower()
        news_hits = sum(1 for t in article_titles if port_first in t and "port" in t)

        # 4. Conflict events within 100 km
        nearby = _events_within_radius(events_df, lat, lon, 100)

        # 5. Expected delay (days)
        if queue is None:
            expected_delay_d: float | None = None
        else:
            expected_delay_d = round(
                (queue / max(1, berths)) * baseline_d * wx_mult, 1
            )

        # 6. Score derived from real delay + event/news multipliers
        if expected_delay_d is None:
            score = 0
            congestion = "Unknown"
        else:
            base = expected_delay_d * 10           # 1 day delay → 10 points
            event_bump = len(nearby) * 4
            news_bump = min(20, news_hits * 3)
            score = int(min(100, base + event_bump + news_bump))
            if   score >= 70: congestion = "Critical"
            elif score >= 40: congestion = "High"
            elif score >= 15: congestion = "Medium"
            else:             congestion = "Low"

        rows.append({
            "Port":             port_name,
            "Country":          ref["country"],
            "Type":             ref["port_type"].title(),
            "Congestion":       congestion,
            "Score":            score,
            "Queue (anchored)": queue_label,
            "Berths":           berths,
            "Baseline (d)":     baseline_d,
            "Expected Delay (d)": expected_delay_d if expected_delay_d is not None else "—",
            "Conflict Events":  len(nearby),
            "News Hits":        news_hits,
            "Sea State":        wx_label,
            "Lat":              lat,
            "Lon":              lon,
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

    # Groq-powered cluster dedup + freshness filter. Falls back silently if
    # the API key is missing or the call fails — feed still renders.
    try:
        from news_classifier import classify_titles
        classifications = classify_titles(tuple(df["title"].head(40).tolist()))
    except Exception:  # noqa: BLE001
        classifications = None

    if classifications and len(classifications) == len(df.head(40)):
        head = df.head(40).copy().reset_index(drop=True)
        head["_cluster"]  = [c["cluster"]  for c in classifications]
        head["_severity"] = [c["severity"] for c in classifications]
        head["_fresh"]    = [c["fresh"]    for c in classifications]
        # Keep only fresh items, then highest-severity per cluster.
        head = head[head["_fresh"]]
        if len(head) > 0:
            head = (head.sort_values("_severity", ascending=False)
                        .drop_duplicates(subset="_cluster", keep="first"))
            now_utc = pd.Timestamp.now(tz="UTC")
            age_h = (now_utc - pd.to_datetime(head["date"], utc=True, errors="coerce")) \
                .dt.total_seconds() / 3600
            recency = 1.0 / (1.0 + (age_h.fillna(0) / 12.0))   # half-life ~12h
            head["_score"] = head["_severity"] * recency
            head = head.sort_values("_score", ascending=False)
        return head.drop(columns=[c for c in ("_cluster", "_severity", "_fresh", "_score")
                                   if c in head.columns]).reset_index(drop=True)

    # Sort newest first (fallback path)
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    return df
