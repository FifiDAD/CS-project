"""Events aggregator — produce a single DataFrame of live, georeferenced
events from GDELT v2 (and any other live feeds added in Phase 2 such as
LiveUAMap) for the rest of the dashboard to consume.

Output schema (canonical):
    event_id, type, location, latitude, longitude, date, impact,
    description, affected_routes, business_impact, source
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from api_integrations import APIClient
from config import MAJOR_SHIPPING_ROUTES
from port_baselines import PORT_BASELINES


# Pre-flatten all corridor anchor points (route waypoints + monitored ports)
# so we can score every event by minimum distance to a shipping corridor.
_CORRIDOR_POINTS: list[tuple[float, float]] = []
for _route in MAJOR_SHIPPING_ROUTES.values():
    _CORRIDOR_POINTS.extend((c[0], c[1]) for c in _route["coords"])
for _p in PORT_BASELINES.values():
    _CORRIDOR_POINTS.append((_p["lat"], _p["lon"]))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(min(1.0, a)))


def _min_corridor_distance_km(lat: float, lon: float) -> float:
    """Min great-circle km from a point to ANY shipping-corridor anchor."""
    return min(_haversine_km(lat, lon, plat, plon)
               for plat, plon in _CORRIDOR_POINTS)


# CAMEO event-root-code → shipping-meaningful bucket
# Five buckets that a fleet operator can act on:
#   🛑 Disruption  — port/strait closure, strike, blockade
#   ⚠️ Threat      — military, missile/drone, attack on vessels
#   🌊 Weather     — storm, cyclone, fog (keyword-detected; no native CAMEO code)
#   🏛 Political   — sanctions, embargo, tariff, diplomatic break
#   📦 Trade       — supply-chain disruption (keyword fallback)
_CAMEO_BUCKET = {
    "13": ("🏛 Political",  "Threat"),
    "14": ("🛑 Disruption", "Protest / Strike"),
    "15": ("⚠️ Threat",     "Force posture"),
    "16": ("🏛 Political",  "Diplomatic break"),
    "17": ("⚠️ Threat",     "Coercion"),
    "18": ("⚠️ Threat",     "Assault"),
    "19": ("⚠️ Threat",     "Armed clash"),
    "20": ("⚠️ Threat",     "Mass violence"),
}


def _classify_bucket(root_code: str, headline: str) -> tuple[str, str]:
    """Return (bucket, sub_label) pair. Falls back to keyword sniff in headline."""
    bucket = _CAMEO_BUCKET.get(str(root_code))
    if bucket:
        return bucket
    text = (headline or "").lower()
    if any(w in text for w in ("storm", "cyclone", "hurricane", "typhoon", "fog", "tsunami")):
        return ("🌊 Weather", "Storm warning")
    if any(w in text for w in ("sanction", "embargo", "tariff")):
        return ("🏛 Political", "Sanctions / Tariff")
    if any(w in text for w in ("port", "strike", "blockade", "shutdown", "closed")):
        return ("🛑 Disruption", "Port disruption")
    if any(w in text for w in ("supply chain", "container", "freight", "shortage")):
        return ("📦 Trade", "Supply-chain alert")
    return ("⚠️ Threat", "Event")


def _impact_from_goldstein(score: float) -> str:
    """GoldsteinScale ranges -10 .. +10; very negative = severe conflict."""
    if pd.isna(score):
        return "Medium"
    if score <= -7:
        return "Critical"
    if score <= -4:
        return "High"
    if score <= -1:
        return "Medium"
    return "Low"


@st.cache_data(ttl=900)
def get_combined_events(
    days: int = 30,
    max_gdelt_files: int = 4,
    corridor_radius_km: float = 500.0,
) -> pd.DataFrame:
    """Return a DataFrame in the dashboard's canonical event shape.

    Geographically filtered to events within `corridor_radius_km` of a
    monitored shipping route or port — drops global noise (e.g. inland
    political events with zero shipping relevance).
    """
    frames: list[pd.DataFrame] = []

    # 1) Shipping-relevant articles (GDELT DOC API, curated query)
    try:
        ship = APIClient.get_shipping_events(timespan=f"{days*24}H")
    except Exception:  # noqa: BLE001
        ship = pd.DataFrame()
    if len(ship) > 0:
        frames.append(pd.DataFrame({
            "event_id":        [f"SHIP_{i}" for i in ship.index],
            "type":            ship["type"],
            "subtype":         ship["subtype"],
            "location":        ship["location"],
            "latitude":        ship["latitude"],
            "longitude":       ship["longitude"],
            "date":            ship["date"],
            "impact":          ship["impact"],
            "description":     ship["description"],
            "affected_routes": [[] for _ in range(len(ship))],
            "business_impact": ship["business_impact"],
            "url":             ship["url"],
            "source":          ship["source"],
        }))

    # 2) GDELT v2 raw events CSV (geocoded, 15-min refresh) — high-impact only.
    try:
        csv = APIClient.get_gdelt_events_csv(max_files=max_gdelt_files)
    except Exception:  # noqa: BLE001
        csv = pd.DataFrame()
    if len(csv) > 0:
        impact = csv["goldstein"].apply(
            lambda g: "Critical" if (g is not None and g <= -7)
                      else "High" if (g is not None and g <= -4)
                      else "Medium"
        )
        buckets = [_classify_bucket(rc, n) for rc, n
                   in zip(csv["event_type"].fillna(""), csv["notes"].fillna(""))]
        frames.append(pd.DataFrame({
            "event_id":        [f"GDLT_{i}" for i in csv.index],
            "type":            [b[0] for b in buckets],
            "subtype":         [b[1] for b in buckets],
            "location":        csv["country"].fillna("—"),
            "latitude":        csv["latitude"],
            "longitude":       csv["longitude"],
            "date":            csv["date"],
            "impact":          impact,
            "description":     csv["notes"].fillna(""),
            "affected_routes": [[] for _ in range(len(csv))],
            "business_impact": csv["goldstein"].apply(
                lambda g: f"Goldstein {g:.1f}" if g is not None else "—"
            ),
            "url":             csv["url"].fillna(""),
            "source":          "GDELT-CSV",
        }))

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["latitude", "longitude"])
    out = out[(out["latitude"] != 0) | (out["longitude"] != 0)]

    # Geo-filter: only keep events within corridor_radius_km of a corridor anchor
    if len(out) > 0:
        out["corridor_distance_km"] = out.apply(
            lambda r: _min_corridor_distance_km(r["latitude"], r["longitude"]),
            axis=1,
        )
        out = out[out["corridor_distance_km"] <= corridor_radius_km]

    return out.reset_index(drop=True)
