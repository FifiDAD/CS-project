# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the dashboard:**
```bash
.venv/bin/streamlit run app.py
```

**Run the simplified version (fewer API dependencies):**
```bash
.venv/bin/streamlit run app_simple.py
```

**Test all API integrations:**
```bash
python test_apis.py
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

## Architecture

Streamlit-based shipping risk dashboard aggregating 9 external APIs. The goal is to help shipping companies plan routes based on geopolitical risk, port congestion, fuel costs, and weather.

### Data Flow

```
app.py
  └── _load_core_data() [cached 15min]
        ├── sample_data.get_events_data()        → calls APIClient.get_acled_events() with fallback
        ├── APIClient.get_oil_price()            → FRED API
        ├── APIClient.get_shipping_index()       → FRED API
        └── APIClient.get_exchange_rates()       → ExchangeRate-API

  └── dynamic_status.py [each function cached separately]
        ├── compute_shipping_status(events_json) → ACLED proximity + GDELT news → route risk scores
        ├── compute_risk_summary(events_json)    → ACLED proximity → regional risk table
        ├── compute_port_congestion(events_json) → GDELT + ACLED + OpenWeather → port scores
        └── get_news_feed()                      → Guardian API + NewsAPI → unified feed

  └── analytics.RiskAnalytics [pure computation, no API calls]
        ├── get_summary_metrics()  → KPI bar + alert banner
        └── calculate_cost_impact() → Tab 3 financial metrics
```

### Critical Caching Pattern

All `dynamic_status.py` functions accept `events_df.to_json()` (a JSON string) rather than a DataFrame directly. This is intentional — Streamlit's `@st.cache_data` cannot hash DataFrames, so the JSON string is used as the cache key. Always pass `.to_json()` when calling these functions, and reconstruct with `pd.read_json(StringIO(json_str))` inside.

### Key Files

| File | Role |
|---|---|
| `app.py` | Full UI layout: CSS, sidebar, KPI bar, globe map, news summary, 4 tabs |
| `maps.py` | Plotly orthographic globe — routes, ports, event markers, day/night overlay |
| `dynamic_status.py` | All live risk computations (shipping, ports, regions, news) |
| `analytics.py` | `RiskAnalytics` class — cost/delay/metric calculations (pure functions, no APIs) |
| `components.py` | `filter_events()` is the only actively used function; other helpers exist but are not wired up |
| `config.py` | `MAJOR_SHIPPING_ROUTES` (waypoint coords), `EVENT_TYPES`, `IMPACT_LEVELS`, `ROUTE_STATUS_COLORS` |
| `api_config.py` | API keys, cache TTLs, `STRAIT_COORDINATES`, `CRITICAL_PORTS`, `KEY_REGIONS` — **do not modify** |
| `api_integrations.py` | `APIClient` static methods for every external API — **do not modify** |
| `sample_data.py` | Fallback events returned when ACLED fails; always produces valid DataFrame schema |

### Map (`maps.py`)

`create_dashboard_map(filtered_events, show_routes, route_statuses, port_congestion_df)` returns a Plotly `Figure` (orthographic globe). It renders: day/night overlay with terminator line, 5 shipping routes colour-coded by status, 8 port markers colour-coded by congestion, and event markers sized by impact with threat rings for Critical events. Routes are coloured via `ROUTE_STATUS_COLORS` in `config.py`.

### Risk Score Formula (`dynamic_status.py`)

- **Chokepoint (0–100):** `critical_events × 25 + high_events × 10 + gdelt_articles × 3`
- **Port congestion (0–100):** `gdelt_articles × 2 + acled_events × 15 + weather_alert × 20`
- **Regional (score):** `critical × 3 + high × 2 + other × 1` → thresholds at 2/4/6

### APIs & Keys

Keys are stored in `api_config.py` with `os.getenv()` fallbacks — set environment variables to override hardcoded defaults. APIs without keys: ACLED, GDELT, NOAA, World Bank, Exchange Rates. APIs with keys: NewsAPI, FRED, Guardian, OpenWeather.

NOAA (`get_weather_hazards()`) and World Bank data are configured but not currently called in `app.py`.

### Cache TTLs

| Data type | TTL |
|---|---|
| News articles | 5 min (`CACHE_TTL_NEWS`) |
| Events, shipping, ports, regions | 15 min (`CACHE_TTL_EVENTS`) |
| Prices, exchange rates | 30 min (`CACHE_TTL_PRICES`) |

### Current Tab Structure

`app.py` has 4 tabs: **Shipping & Ports** (chokepoint status + regional risk + port congestion), **Analytics** (event type/impact charts + 30-day timeline), **Impact** (financial cost estimates), **Fuel Calculator** (voyage cost estimator with live WTI crude and route risk surcharge).
