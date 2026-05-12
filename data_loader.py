"""Shared cached data loading — used by all TradeWatch pages."""
import threading

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

from sample_data import get_events_data
from api_integrations import APIClient
from api_config import CACHE_TTL_EVENTS


@st.cache_data(ttl=CACHE_TTL_EVENTS)
def load_core_data():
    # Shared hot path for every page: load live events and market context once.
    events         = get_events_data()
    oil_price      = APIClient.get_oil_price()
    shipping_idx   = APIClient.get_shipping_index()
    exchange_rates = APIClient.get_exchange_rates()
    return events, oil_price, shipping_idx, exchange_rates


# Single-flight lock so multiple Landing reruns don't stack identical
# warm-up threads. The lock is released as soon as the prefetch finishes;
# subsequent calls then re-fire if the cache has since expired.
_PREFETCH_LOCK = threading.Lock()


def prefetch_full_dashboard() -> None:
    """Fire-and-forget warm-up of every cache the rest of the dashboard
    will hit. The Landing page is now pure-static tutorial content (no
    live fetches), so this prefetch has to load events + risk + ports +
    news + piracy from scratch in a daemon thread. By the time the user
    clicks "Open Main Dashboard" all the slow paths are already cached.

    All targets are `@st.cache_data` decorated, so calling this on every
    Landing rerun is safe — once warm, the thread returns immediately.
    The single-flight lock prevents thread stacking on rapid reruns.
    """
    if not _PREFETCH_LOCK.acquire(blocking=False):
        return  # a previous prefetch is still in flight

    ctx = get_script_run_ctx()

    def _warm() -> None:
        # Stage 1: core data (events, oil, freight index, FX). Everything
        # downstream depends on events_df.
        try:
            events_df, *_ = load_core_data()
        except Exception:
            return
        try:
            events_json = (events_df.to_json() if len(events_df) > 0
                           else pd.DataFrame().to_json())
        except Exception:
            return

        # Stage 2: heavy computed views the dashboard pages display.
        # Imports stay local to avoid slowing normal module import on startup.
        try:
            from dynamic_status import (
                compute_shipping_status, compute_port_congestion,
                compute_risk_summary, get_news_feed,
            )
            compute_shipping_status(events_json)
            compute_port_congestion(events_json)
            compute_risk_summary(events_json)
            get_news_feed()
        except Exception:
            pass

        # Stage 3: ancillary feeds.
        # Piracy is optional map context, so failures should not cancel prefetch.
        try:
            APIClient.get_piracy_incidents(days=90)
        except Exception:
            pass

    def _run() -> None:
        # Always release the single-flight lock, even if a feed fails mid-warmup.
        try:
            _warm()
        finally:
            _PREFETCH_LOCK.release()

    t = threading.Thread(target=_run, daemon=True, name="tw-prefetch-full")
    if ctx is not None:
        add_script_run_ctx(t, ctx)
    t.start()


# Backwards-compatible alias — older code paths called this with an
# `events_json` arg. New Landing has no events to pass; redirect to the
# full warm-up so callers get the same end state.
def prefetch_main_dashboard(events_json: str | None = None) -> None:
    # Preserve old call sites while routing all warm-up work through one function.
    prefetch_full_dashboard()
