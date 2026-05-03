"""Live event feed for the dashboard.

Pulls geocoded events from the live aggregator (GDELT + any other
streams added in Phase 2). NEVER silently substitutes mock data —
if the live feed is empty or fails, returns an empty DataFrame so
the UI can surface "Live event feed unavailable" rather than show
fabricated events.

Set environment variable DASHBOARD_USE_SAMPLE_DATA=1 to opt into
the static sample (development / unit tests only).
"""

import logging
import os
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)


@st.cache_data(ttl=900)
def get_events_data() -> pd.DataFrame:
    """Return the live events DataFrame, or an empty frame if no data is available.

    Never returns mock data unless DASHBOARD_USE_SAMPLE_DATA=1 is set.
    """
    if os.getenv("DASHBOARD_USE_SAMPLE_DATA") == "1":
        return get_sample_events()

    try:
        from events_aggregator import get_combined_events
        df = get_combined_events(days=30)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live event aggregator failed: %s", exc, exc_info=True)
        return pd.DataFrame()

    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def get_sample_events() -> pd.DataFrame:
    """Static sample events — dev/test only. Not used in production rendering."""
    events = [
        {
            "event_id": "E001",
            "type": "Military Strike",
            "location": "Ukraine, Eastern Region",
            "latitude": 48.5,
            "longitude": 37.5,
            "date": datetime.now() - timedelta(hours=2),
            "impact": "Critical",
            "description": "Military activity reported in eastern sector",
            "affected_routes": ["English Channel"],
            "business_impact": "Port operations at risk",
        },
        {
            "event_id": "E002",
            "type": "Port Disruption",
            "location": "Red Sea, Houthi Area",
            "latitude": 15.5,
            "longitude": 42.0,
            "date": datetime.now() - timedelta(hours=6),
            "impact": "High",
            "description": "Port operations disrupted due to regional tensions",
            "affected_routes": ["Suez Canal"],
            "business_impact": "Shipping delays expected, 15-20% cost increase",
        },
    ]
    return pd.DataFrame(events)
