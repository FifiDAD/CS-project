# =============================================================================
# nga_warnings.py — OFFICIAL NGA MARITIME WARNINGS FEED
# =============================================================================
# The NGA (US National Geospatial-Intelligence Agency) publishes a free
# stream of "Maritime Safety Broadcast Warnings" — these are the
# official notices to mariners. Things like "Suez Canal closed for
# maintenance from X to Y", "Mines reported at lat/lon", "GPS jamming
# active in this area", "Attack on vessel reported here", and naval
# exercise zones. They are the single most authoritative signal we
# have for whether a chokepoint is safe right now.
#
# This file fetches that feed from the public NGA endpoint (no API key
# needed), assigns a 0-1 SEVERITY score to each warning based on its
# text (an attack-class warning scores high, an exercise lower), and
# exposes two functions:
#
#   - fetch_warnings()                  -> DataFrame of all current warnings
#   - severity_for_chokepoint(cp, df)   -> the worst severity inside a
#                                          given chokepoint bounding box.
#
# dynamic_status.compute_shipping_status() multiplies the chokepoint
# severity by 45 in the final 0-100 risk score formula.
#
# Public endpoint: https://msi.nga.mil/api/publications/broadcast-warn
#
# IMPORTANT: NGA warnings are treated as the strongest signal in the
# risk score. If an active closure-class or attack-class warning is
# present inside a chokepoint bbox, that chokepoint gets pinned to
# Critical regardless of any other noise from news/events.
# =============================================================================

from __future__ import annotations

import logging
import re
from typing import Iterable

import pandas as pd
import requests
import streamlit as st

from api_config import CACHE_TTL_EVENTS

logger = logging.getLogger(__name__)

NGA_BROADCAST_URL = "https://msi.nga.mil/api/publications/broadcast-warn"
_HEADERS = {"User-Agent": "LogisticsDashboard/1.0"}

# Regexes used to extract decimal-degree positions from the free-text
# `text` field. NGA publishes positions like "26-30.00N 056-30.00E" or
# decimal "26.5N 56.5E"; we accept both.
_POS_DM = re.compile(
    r"(\d{1,3})-(\d{1,2}(?:\.\d+)?)\s*([NS])\s+(\d{1,3})-(\d{1,2}(?:\.\d+)?)\s*([EW])",
    re.IGNORECASE,
)
_POS_DD = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*([NS])\s+(\d{1,3}(?:\.\d+)?)\s*([EW])",
    re.IGNORECASE,
)


def _dm_to_dd(deg: str, min_: str, hemi: str) -> float:
    # Convert degrees/minutes text into decimal degrees.
    val = float(deg) + float(min_) / 60.0
    return -val if hemi.upper() in ("S", "W") else val


def _extract_positions(text: str) -> list[tuple[float, float]]:
    if not text:
        return []
    out: list[tuple[float, float]] = []
    # Try degree-minute coordinates first.
    for m in _POS_DM.finditer(text):
        try:
            lat = _dm_to_dd(m.group(1), m.group(2), m.group(3))
            lon = _dm_to_dd(m.group(4), m.group(5), m.group(6))
            out.append((lat, lon))
        except ValueError:
            continue
    if out:
        return out
    # Fall back to decimal-degree coordinates.
    for m in _POS_DD.finditer(text):
        try:
            lat = float(m.group(1)) * (-1 if m.group(2).upper() == "S" else 1)
            lon = float(m.group(3)) * (-1 if m.group(4).upper() == "W" else 1)
            out.append((lat, lon))
        except ValueError:
            continue
    return out


# Keyword → severity weight (0..1). Higher = more disruptive to shipping.
_SEVERITY_KEYWORDS: list[tuple[float, tuple[str, ...]]] = [
    (1.00, ("closed", "closure", "mine", "mines", "blockade", "ceasefire violated", "exclusion zone")),
    (0.85, ("attack", "missile", "drone strike", "torpedo", "uav strike", "piracy", "hijack")),
    (0.70, ("gps jamming", "gps interference", "spoofing", "navigation jamming")),
    (0.55, ("military exercise", "live fire", "naval drill", "warning shot")),
    (0.35, ("debris", "wreck", "obstruction", "abandoned vessel")),
]


def _severity(text: str) -> float:
    if not text:
        return 0.0
    t = text.lower()
    # Use the first matching keyword group as the warning severity.
    for weight, kws in _SEVERITY_KEYWORDS:
        if any(k in t for k in kws):
            return weight
    return 0.15  # any active warning still counts a little


def _age_decay(msg_year: int | None, current_year: int) -> float:
    """NGA broadcast warnings can stay 'in force' for years. Down-weight older
    messages so a 2024 warning grades weaker than a same-year one and a 2021
    warning grades very weak. 1.0 = current year, 0.5 = 1y old, 0.2 = 2y+."""
    if not msg_year:
        return 0.5
    delta = current_year - int(msg_year)
    if delta <= 0:
        return 1.0
    if delta == 1:
        return 0.5
    if delta == 2:
        return 0.3
    return 0.2


@st.cache_data(ttl=CACHE_TTL_EVENTS)
def fetch_warnings() -> pd.DataFrame:
    """Fetch active NGA broadcast warnings.

    Returns DataFrame with columns: id, issued, text, severity, latitudes,
    longitudes (lists). Empty DataFrame on failure — callers must handle.
    """
    from datetime import datetime
    current_year = datetime.utcnow().year
    try:
        r = requests.get(
            NGA_BROADCAST_URL,
            params={"output": "json"},
            headers=_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("NGA broadcast warnings fetch failed: %s", exc)
        return pd.DataFrame(columns=["id", "issued", "text", "severity", "lats", "lons"])

    items: Iterable = (
        payload if isinstance(payload, list)
        else payload.get("broadcast-warn") or payload.get("broadcastWarn")
            or payload.get("data") or payload.get("results") or []
    )
    rows = []
    for it in items:
        if not isinstance(it, dict):
            continue
        # Join likely text fields into one warning body.
        text = " ".join(
            str(it.get(k, "") or "") for k in ("text", "navText", "subject", "title", "body")
        )
        positions = _extract_positions(text)
        msg_year = it.get("msgYear")
        msg_id = f"{msg_year}-{it.get('msgNumber','')}" if msg_year else it.get("id", "")
        decay = _age_decay(msg_year, current_year)
        # Store position lists because one warning can mention several points.
        rows.append({
            "id":       msg_id,
            "msgYear":  msg_year,
            "issued":   it.get("issueDate") or it.get("dateIssued") or it.get("authority", ""),
            "navArea":  it.get("navArea", ""),
            "text":     text.strip(),
            "severity": _severity(text) * decay,   # age-decayed
            "lats":     [p[0] for p in positions],
            "lons":     [p[1] for p in positions],
        })
    return pd.DataFrame(rows)


def severity_for_chokepoint(
    warnings_df: pd.DataFrame,
    lat: float,
    lon: float,
    radius_km: float,
) -> tuple[float, int]:
    """Return (max_severity, warning_count) for warnings within radius_km
    of the chokepoint center. Severity is in 0..1.

    Warnings without parsable coordinates are ignored — we do NOT
    optimistically apply them to every chokepoint.
    """
    if warnings_df is None or len(warnings_df) == 0:
        return 0.0, 0

    # Cheap bbox filter using deg → km approximation
    dlat = radius_km / 111.0
    dlon = radius_km / 85.0  # mid-latitude proxy; we re-check below

    max_sev = 0.0
    count = 0
    for _, row in warnings_df.iterrows():
        # Check every parsed point from the warning.
        for plat, plon in zip(row["lats"], row["lons"]):
            if abs(plat - lat) > dlat or abs(plon - lon) > dlon:
                continue
            # Fine-grained haversine
            # Confirm the point is really inside the radius.
            from math import asin, cos, radians, sin, sqrt
            dphi = radians(plat - lat)
            dlam = radians(plon - lon)
            a = (sin(dphi / 2) ** 2
                 + cos(radians(lat)) * cos(radians(plat)) * sin(dlam / 2) ** 2)
            d_km = 6371.0 * 2 * asin(min(1.0, sqrt(a)))
            if d_km <= radius_km:
                max_sev = max(max_sev, float(row["severity"]))
                count += 1
                break  # don't double-count one warning
    return max_sev, count
