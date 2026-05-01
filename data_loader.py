"""Shared cached data loading — used by all TradeWatch pages."""
import streamlit as st
from sample_data import get_events_data
from api_integrations import APIClient
from api_config import CACHE_TTL_EVENTS


@st.cache_data(ttl=CACHE_TTL_EVENTS)
def load_core_data():
    events         = get_events_data()
    oil_price      = APIClient.get_oil_price()
    shipping_idx   = APIClient.get_shipping_index()
    exchange_rates = APIClient.get_exchange_rates()
    return events, oil_price, shipping_idx, exchange_rates
