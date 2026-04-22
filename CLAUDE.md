# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the dashboard:**
```bash
.venv/bin/streamlit run app.py
```

**Test all API integrations:**
```bash
python test_apis.py
```

**Run the simplified version:**
```bash
.venv/bin/streamlit run app_simple.py
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

## Architecture

This is a Streamlit-based supply chain risk dashboard that aggregates data from 9 external APIs to track geopolitical events affecting global logistics.

**Data flow:**
1. `app.py` calls `load_data()` which uses `APIClient` from `api_integrations.py` to fetch from external APIs
2. Raw data is processed by `DataProcessor` (also in `api_integrations.py`) into a normalized event format
3. `RiskAnalytics` in `analytics.py` computes business impact metrics (cost, delays, risk scores)
4. `components.py` renders reusable UI elements; `maps.py` generates Folium maps
5. All data is Streamlit-cached with 30-minute TTL (`@st.cache_data(ttl=1800)`)

**Key files:**
- `api_integrations.py` — `APIClient` (fetches from ACLED, GDELT, NewsAPI, FRED, Guardian, NOAA, World Bank, Exchange Rates) + `DataProcessor`
- `api_config.py` — API keys, endpoint URLs, monitored regions, and critical port coordinates
- `config.py` — Static constants: event types with colors/icons, impact levels, shipping route definitions
- `sample_data.py` — Fallback data used when APIs fail; always returns valid event structures

**API key configuration:** Keys are stored directly in `api_config.py` (not environment variables). APIs that require keys: NewsAPI, FRED, Guardian, OpenWeather. APIs that work without keys: ACLED, GDELT, NOAA, World Bank, Exchange Rates.

**Fallback behavior:** When any API call fails, `sample_data.py` provides hardcoded sample events so the dashboard always renders.

## Dashboard Tabs

The main `app.py` has 5 tabs: Map (Folium), Events (filterable list), Shipping (route status), Analytics (risk scoring), Impact (financial calculations).
