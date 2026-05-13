"""Events aggregator — produce a single DataFrame of live, georeferenced
events from GDELT DOC (curated maritime query) for the rest of the dashboard
to consume.

Output schema (canonical):
    event_id, type, location, latitude, longitude, date, impact,
    description, affected_routes, business_impact, source
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from api_integrations import APIClient
from config import MAJOR_SHIPPING_ROUTES
from port_baselines import PORT_BASELINES


# Pre-flatten all corridor anchor points (route waypoints + monitored ports)
# so we can score every event by minimum distance to a shipping corridor.
_CORRIDOR_POINTS: list[tuple[float, float]] = []
for _route in MAJOR_SHIPPING_ROUTES.values():
    # Add every route waypoint as a corridor point.
    _CORRIDOR_POINTS.extend((c[0], c[1]) for c in _route["coords"])
for _p in PORT_BASELINES.values():
    # Add monitored ports so nearby events are kept too.
    _CORRIDOR_POINTS.append((_p["lat"], _p["lon"]))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Calculate distance between two latitude/longitude points.
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


@st.cache_data(ttl=900)
def get_combined_events(
    days: int = 30,
    corridor_radius_km: float = 250.0,
) -> pd.DataFrame:
    """Return a DataFrame in the dashboard's canonical event shape.

    Sourced exclusively from `APIClient.get_shipping_events()` — a curated
    GDELT DOC query that requires maritime keywords in the article title and
    classifies each article into one of five operator-actionable buckets.

    Geographically filtered to events within `corridor_radius_km` of a
    monitored shipping route or port — drops any residual coastal-but-
    irrelevant noise.
    """
    frames: list[pd.DataFrame] = []

    try:
        # Main live shipping events come from the curated GDELT query.
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
            # Multi-source clustering fields produced by get_shipping_events.
            "hint_key":        ship.get("hint_key", ""),
            "domain":          ship.get("domain", ""),
            "n_sources":       ship.get("n_sources", 1),
            "on_map":          ship.get("on_map", False),
        }))

    # USGS earthquakes near monitored ports — already coastal-filtered upstream
    try:
        # Add recent earthquakes near ports as a second event source.
        quakes = APIClient.get_earthquakes(min_mag=4.5, days=7)
    except Exception:  # noqa: BLE001
        quakes = pd.DataFrame()
    if len(quakes) > 0:
        n = len(quakes)
        frames.append(pd.DataFrame({
            "event_id":        [f"EQ_{i}" for i in quakes.index],
            "type":            quakes["type"],
            "subtype":         quakes["subtype"],
            "location":        quakes["location"],
            "latitude":        quakes["latitude"],
            "longitude":       quakes["longitude"],
            "date":            quakes["date"],
            "impact":          quakes["impact"],
            "description":     quakes["description"],
            "affected_routes": [[] for _ in range(n)],
            "business_impact": quakes["business_impact"],
            "url":             quakes["url"],
            "source":          quakes["source"],
            # Earthquakes don't carry multi-source semantics; show on map
            # since USGS itself is the authoritative source.
            "hint_key":        ["" for _ in range(n)],
            "domain":          ["usgs.gov" for _ in range(n)],
            "n_sources":       [1 for _ in range(n)],
            "on_map":          [True for _ in range(n)],
        }))

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)

    # Canonicalise dates to tz-aware UTC. Source feeds may mix tz-naive
    # (datetime.strptime) and tz-aware (pd.to_datetime(..., utc=True)) values;
    # without this, sort_values("date") raises "Cannot compare tz-naive and
    # tz-aware timestamps" downstream.
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], utc=True, errors="coerce")

    out = out.dropna(subset=["latitude", "longitude"])
    out = out[(out["latitude"] != 0) | (out["longitude"] != 0)]

    if len(out) > 0:
        # Drop events that are too far from monitored routes or ports.
        out["corridor_distance_km"] = out.apply(
            lambda r: _min_corridor_distance_km(r["latitude"], r["longitude"]),
            axis=1,
        )
        out = out[out["corridor_distance_km"] <= corridor_radius_km]

    return out.reset_index(drop=True)
