"""
dynamic_status.py — Compute shipping/port/regional status from live API data.

All functions accept events_df.to_json() as input (a JSON string) so that
Streamlit's @st.cache_data can hash them — DataFrames are not hashable.
"""

import math
from io import StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed
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

        # Multi-source news clusters from events_df — corroborated by ≥2
        # distinct domains, deduped by cluster_id, with a 0.5× decay for
        # anything older than 24h. This is what feeds the risk formula
        # (the raw `news_signal` count is too noisy: a single trending
        # headline can produce 10+ articles and pin the score to 100).
        news_clusters_score = 0.0
        if len(events_df) > 0 and "hint_key" in events_df.columns:
            cp_hint = strait_name.lower()
            try:
                hint_match = (
                    events_df["hint_key"].astype(str).str.lower()
                    .str.contains(cp_hint, na=False, regex=False)
                )
                multi_source = events_df["n_sources"].fillna(1) >= 2
                matched = events_df[hint_match & multi_source]
                if "cluster_id" in matched.columns:
                    matched = matched.drop_duplicates(subset="cluster_id")
                if len(matched) > 0:
                    now = pd.Timestamp.now(tz="UTC")
                    ages = (now - pd.to_datetime(matched["date"], utc=True, errors="coerce")).dt.total_seconds()
                    weights = ages.fillna(86400).apply(lambda s: 1.0 if s < 86400 else 0.5)
                    news_clusters_score = float(weights.sum())
            except Exception:  # noqa: BLE001  never blow up risk computation on a column quirk
                news_clusters_score = 0.0

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

        # Composite risk score 0–100. Rebalanced so a single dominant input
        # can't peg the score on its own:
        #   - NGA contributes up to +45 (was +80) — a closure-class warning
        #     should be a strong signal, not the only signal.
        #   - AIS drop is capped at +25 (was +50) so a noisy day can't
        #     account for half the score.
        #   - News uses multi-source clusters (×6) instead of raw GDELT
        #     article counts (was ×3). Clusters are far rarer than
        #     articles, so a trending headline no longer floods the score.
        risk_score = min(
            100,
            int(round(nga_sev * 45))
            + min(25, ais_points)
            + critical_nearby * 25
            + high_nearby * 10
            + int(round(news_clusters_score * 6))
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
            "Multi-source Clusters": round(news_clusters_score, 1),
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


# ITU-R AIS ship-type codes that are NOT commercial cargo/tanker queue.
# When `ship_type` is known and falls in this set, the vessel is excluded
# from the anchorage-queue count. Codes 70-79 (cargo) and 80-89 (tanker)
# are intentionally NOT in this set — those count as commercial queue.
# When `ship_type` is unknown (NULL / NaN), the vessel is INCLUDED — the
# filter degrades gracefully so the metric keeps working while the AIS
# Type-5 (ShipStaticData) backlog populates.
_NON_COMMERCIAL_SHIP_TYPES: frozenset[int] = frozenset({
    30,                                      # Fishing
    31, 32,                                  # Towing / large tow
    33, 34, 35,                              # Dredging / Diving / Military
    36, 37,                                  # Sailing / Pleasure craft
    50, 51, 52, 53, 54, 55, 58, 59,          # Pilot/SAR/Tug/Port tender etc.
    60, 61, 62, 63, 64, 65, 66, 67, 68, 69,  # Passenger
})


def _ais_anchored_count(
    ais_df: pd.DataFrame,
    lat: float,
    lon: float,
    radius_km: float,
    exclude_types: frozenset[int] = _NON_COMMERCIAL_SHIP_TYPES,
) -> int:
    """Count AIS positions within radius_km that are at anchor (SOG < 0.5 kn).

    `exclude_types` removes known non-commercial vessels (fishing, pleasure
    craft, ferries, tugs, pilot boats, etc.). Vessels with unknown
    `ship_type` are kept — see comment on `_NON_COMMERCIAL_SHIP_TYPES`.
    """
    if ais_df is None or len(ais_df) == 0:
        return 0
    sub = ais_df[ais_df["sog_kn"].fillna(0) < 0.5]
    if len(sub) == 0:
        return 0
    if exclude_types and "ship_type" in sub.columns:
        # Cast to int for set membership; NaN → -1 (treated as unknown → kept)
        st = sub["ship_type"].fillna(-1).astype(int)
        sub = sub[~st.isin(exclude_types)]
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

    # ── Batched GDELT calls covering ALL ports ──────────────────────────────
    # Each batch quotes full port names (not first-word splits) so multi-word
    # ports like "Los Angeles" match correctly; congestion-class keywords are
    # required at the query level, then re-checked per-port below.
    port_names = list(PORT_BASELINES.keys())
    articles: list[dict] = []
    BATCH = 12
    _CONGEST_KW = ("congestion", "delay", "backlog", "queue", "closure", "strike")
    for _i in range(0, len(port_names), BATCH):
        _quoted = " OR ".join(f'"{n}"' for n in port_names[_i:_i + BATCH])
        _q = (
            f"({_quoted}) AND "
            f"(congestion OR delay OR backlog OR queue OR \"port closure\" OR strike)"
        )
        try:
            articles.extend(APIClient.get_gdelt_articles(_q, timespan="48H") or [])
        except Exception:  # noqa: BLE001
            continue

    # Pre-index articles by lowercase title text for substring matching
    article_titles = [(a.get("title") or "").lower() for a in articles]

    # ── Live AIS snapshot (≤10 min old) ──────────────────────────────────────
    ais_df = latest_positions(max_age_sec=600)

    # ── Parallel marine weather fetch for all ports ───────────────────────────
    # Fetching 30+ ports sequentially takes 15-40 s; parallel cuts this to ~2 s.
    _port_items = list(PORT_BASELINES.items())
    _marine_cache: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as _ex:
        _futs = {
            _ex.submit(APIClient.get_marine_weather, ref["lat"], ref["lon"]): pname
            for pname, ref in _port_items
        }
        for _fut in as_completed(_futs):
            _pname = _futs[_fut]
            try:
                _marine_cache[_pname] = _fut.result() or {}
            except Exception:
                _marine_cache[_pname] = {}

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

        # 2. Real marine weather (pre-fetched in parallel above)
        marine = _marine_cache.get(port_name, {})
        wave_m = marine.get("wave_height_m") or 0.0
        swell_m = marine.get("swell_height_m") or 0.0
        # Hazard if seas above 3 m or swell above 2.5 m
        wx_hazard = (wave_m or 0) > 3.0 or (swell_m or 0) > 2.5
        wx_mult = 1.5 if wx_hazard else 1.0
        wx_label = f"Wave {wave_m:.1f}m / Swell {swell_m:.1f}m" if marine else "n/a"

        # 3. News signal — title must contain the FULL port name AND a
        # congestion-class keyword. Avoids false positives from substring
        # matches on common first-words (e.g. "Los", "New", "Port").
        port_lc = port_name.lower()
        news_hits = sum(
            1 for t in article_titles
            if port_lc in t and any(k in t for k in _CONGEST_KW)
        )

        # 4. Conflict events within 100 km
        nearby = _events_within_radius(events_df, lat, lon, 100)

        # 5. Expected delay (days) — only when AIS queue is known.
        # The raw queue/berths ratio is clamped at 5× because beyond that
        # the count is almost always inflated (ambient AIS contacts within
        # the anchorage radius rather than a genuine 17-day port wait).
        # 5× × baseline_turnaround = realistic upper bound on real-world
        # observed delay for any modern major port.
        if queue is None:
            expected_delay_d: float | None = None
        else:
            ratio = min(queue / max(1, berths), 5.0)
            expected_delay_d = round(ratio * baseline_d * wx_mult, 1)

        # 6. Score derived from real delay + event/news multipliers.
        # `delay × 5` (was × 10) means the score caps at 100 only when
        # observed delay reaches 20 days — previously it saturated at 10
        # days and pinned every busy port to 100.
        event_bump = len(nearby) * 4
        if expected_delay_d is None:
            news_bump = min(12, news_hits * 2)
            score = int(min(100, event_bump + news_bump))
            confidence = "News-only"
        else:
            news_bump = min(20, news_hits * 3)
            base = expected_delay_d * 5
            score = int(min(100, base + event_bump + news_bump))
            confidence = "Live AIS"

        if   score >= 70: congestion = "Critical"
        elif score >= 40: congestion = "High"
        elif score >= 15: congestion = "Medium"
        else:             congestion = "Low"

        rows.append({
            "Port":             port_name,
            "Country":          ref["country"],
            "Type":             ref["port_type"].title(),
            "Congestion":       congestion,
            "Confidence":       confidence,
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

    # ── Maritime industry RSS (free, no key) ─────────────────────────────────
    rss_df = APIClient.get_maritime_rss()
    if len(rss_df) > 0:
        for _, row in rss_df.iterrows():
            title = row.get("title", "")
            records.append({
                "title":  title,
                "source": row.get("source", "Maritime"),
                "date":   row.get("date", pd.Timestamp.now(tz="UTC")),
                "url":    row.get("url", "#"),
                "topic":  _classify_topic(title),
            })

    # ── GNews (optional, key-gated) ──────────────────────────────────────────
    gnews_df = APIClient.get_gnews(query=keywords)
    if len(gnews_df) > 0:
        for _, row in gnews_df.iterrows():
            title = row.get("title", "")
            records.append({
                "title":  title,
                "source": row.get("source", "GNews"),
                "date":   row.get("date", pd.Timestamp.now(tz="UTC")),
                "url":    row.get("url", "#"),
                "topic":  _classify_topic(title),
            })

    # ── NewsData.io (optional, key-gated) ────────────────────────────────────
    newsdata_df = APIClient.get_newsdata(query=keywords)
    if len(newsdata_df) > 0:
        for _, row in newsdata_df.iterrows():
            title = row.get("title", "")
            records.append({
                "title":  title,
                "source": row.get("source", "NewsData"),
                "date":   row.get("date", pd.Timestamp.now(tz="UTC")),
                "url":    row.get("url", "#"),
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

    # ── GDELT supplementary / fallback (free, no key required) ──────────────
    # Fires when Guardian + NewsAPI together return fewer than 10 articles so
    # the Intel Feed always has content even if API keys are missing or quota
    # is exhausted.
    if len(records) < 10:
        gdelt_arts = APIClient.get_gdelt_articles(
            "(shipping OR maritime OR port OR conflict OR military OR sanctions OR trade)"
            " sourcelang:english",
            timespan="24H",
        )
        for art in gdelt_arts[:40]:
            title = (art.get("title") or "").strip()
            url   = art.get("url") or "#"
            if not title:
                continue
            raw_date = art.get("seendate") or art.get("crawldate") or ""
            try:
                date = pd.to_datetime(raw_date, format="%Y%m%d%H%M%S", utc=True)
                if pd.isnull(date):
                    raise ValueError
            except Exception:
                date = pd.Timestamp.now(tz="UTC")
            records.append({
                "title":  title,
                "source": art.get("domain", "GDELT"),
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
        tail = df.iloc[40:].copy().reset_index(drop=True)
        head["_cluster"]  = [c["cluster"]  for c in classifications]
        head["_severity"] = [c["severity"] for c in classifications]
        head["_fresh"]    = [c["fresh"]    for c in classifications]
        fresh = head[head["_fresh"]]
        if len(fresh) > 0:
            fresh = (fresh.sort_values("_severity", ascending=False)
                         .drop_duplicates(subset="_cluster", keep="first"))
            now_utc = pd.Timestamp.now(tz="UTC")
            age_h = (now_utc - pd.to_datetime(fresh["date"], utc=True, errors="coerce")) \
                .dt.total_seconds() / 3600
            recency = 1.0 / (1.0 + (age_h.fillna(0) / 12.0))
            fresh["_score"] = fresh["_severity"] * recency
            fresh = fresh.sort_values("_score", ascending=False)
            top = fresh.drop(columns=[c for c in ("_cluster", "_severity", "_fresh", "_score")
                                      if c in fresh.columns]).reset_index(drop=True)
            # Keep the long tail (articles beyond head[40]) so the feed isn't
            # gutted to a handful of cluster-leaders. Tail stays sorted newest
            # first underneath the Groq-ranked top.
            if len(tail) > 0:
                tail = tail.sort_values("date", ascending=False).reset_index(drop=True)
                return pd.concat([top, tail], ignore_index=True).drop_duplicates(
                    subset="title").reset_index(drop=True)
            return top
        # Groq marked everything stale — fall through to unfiltered sort

    # Sort newest first (fallback path)
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    return df


# ── Region clusterer for the Intel Feed ───────────────────────────────────────
_REGION_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Suez / Red Sea",          ("suez", "red sea", "bab el-mandeb", "bab al-mandab",
                                 "houthi", "port said", "yemen", "djibouti")),
    ("Strait of Hormuz",        ("hormuz", "iran", "gulf of oman", "persian gulf",
                                 "strait of oman", "tehran")),
    ("Malacca / Singapore",     ("malacca", "singapore strait", "lombok", "sunda")),
    ("Panama Canal",            ("panama canal", "panama drought", "gatun", "neopanamax")),
    ("English Channel / N. Europe", ("english channel", "dover strait", "rotterdam",
                                     "antwerp", "hamburg", "felixstowe", "north sea")),
    ("Far East / Taiwan",       ("taiwan", "south china sea", "luzon", "scs",
                                 "shanghai", "ningbo", "busan", "yokohama")),
    ("Black Sea",               ("black sea", "bosphorus", "bosporus", "odesa",
                                 "ukraine grain", "novorossiysk")),
    ("Americas",                ("los angeles", "long beach", "houston", "savannah",
                                 "santos", "buenaventura", "vancouver")),
]


def cluster_news_by_region(news_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Group articles by maritime region based on title keyword matching.

    Each article is assigned to the FIRST matching region (so order in
    `_REGION_KEYWORDS` is the priority order). Articles with no match land
    in the "Other" bucket. Returns dict {region_name: DataFrame} keyed in
    insertion order, with empty regions omitted.
    """
    if news_df is None or len(news_df) == 0:
        return {}
    titles = news_df["title"].fillna("").str.lower()
    buckets: dict[str, list[int]] = {}
    for region, kws in _REGION_KEYWORDS:
        buckets[region] = []
    buckets["Other"] = []

    for idx, t in titles.items():
        placed = False
        for region, kws in _REGION_KEYWORDS:
            if any(kw in t for kw in kws):
                buckets[region].append(idx)
                placed = True
                break
        if not placed:
            buckets["Other"].append(idx)

    out: dict[str, pd.DataFrame] = {}
    for region, idxs in buckets.items():
        if not idxs:
            continue
        out[region] = news_df.loc[idxs].sort_values("date", ascending=False).reset_index(drop=True)
    return out
