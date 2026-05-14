# =============================================================================
# sample_data.py — THE LIVE-EVENTS ENTRY POINT (with optional fake fallback)
# =============================================================================
# Despite its name, this file is what every page actually calls to get
# the "current events" data. It's named "sample_data" for historical
# reasons (it used to return hardcoded fake events for development); now
# it pulls REAL events from our events_aggregator (GDELT-backed).
#
# Critically: if the live feed fails or returns no rows, we return an
# EMPTY DataFrame rather than silently substituting fake events. That
# way the UI can honestly say "Live event feed unavailable" instead of
# showing fabricated incidents.
#
# Developers can opt in to the static fake-data fallback by setting the
# environment variable DASHBOARD_USE_SAMPLE_DATA=1 — useful for offline
# development and unit tests so we don't hammer GDELT every reload.
# =============================================================================

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
        # Use static demo rows only when explicitly enabled.
        return get_sample_events()

    try:
        # Load the real combined event feed for normal dashboard use.
        from events_aggregator import get_combined_events
        df = get_combined_events(days=30)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live event aggregator failed: %s", exc, exc_info=True)
        return pd.DataFrame()

    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def get_sample_events() -> pd.DataFrame:
    """Static sample events — dev/test only. Not used in production rendering."""
    # Small fixed dataset used for local demos and tests.
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
