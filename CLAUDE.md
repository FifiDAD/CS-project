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

**Train the ETA predictor (ML feature):**
```bash
python train_eta_model.py --seed         # cold start: synthetic seed + full CV + hyperparam sweep
python train_eta_model.py --seed --no-cv # fast iteration (skip CV + sweep)
python train_eta_model.py                # real AIS data; refuses if <200 rows
```
Pipeline: 5-fold time-series CV → 27-cell hyperparam sweep → train final
q10/q50/q90 boosters with best config → SHAP backing data + calibration plot.
Writes `models/`: `eta_xgb.joblib`, `eta_meta.json`, `eta_feature_importance.png`,
`eta_calibration.png`, `eta_shap_values.npy` + X_test + feature_names.

**Run tests:**
```bash
pytest tests/ -v   # 31 tests, ~8s
```

The MariNav Router page exposes:
- Per-card ML ETA + interval bar (CSS p10/p50/p90)
- "Compare ML vs heuristic baseline" toggle in sidebar
- Per-chokepoint "Why this prediction?" expander (SHAP top-K contributions)
- ML diagnostics expander: CV metrics, best HP, feature importance, calibration
  plot, top-5 sweep, per-chokepoint MAE, "Retrain now" button.

Predictions fall back to a calibrated heuristic when the artifact is missing.
`eta_scheduler.start_eta_scheduler()` (called from `app.py`) auto-retrains
once daily when ≥200 real AIS rows exist and the cooldown has elapsed.

**Live quality tracking (`pages/5_ETA_Quality.py` + `eta_quality.py`)**: every
call to `predict_transit_minutes()` now writes one row to the
`eta_predictions` table in `.ais_positions.db` with the inputs and
outputs. `eta_quality.match_open_predictions()` later joins each open
prediction to the realised entry/exit timestamps from `sightings` (same
bbox + gap-split logic as the trainer), filling in `actual_min`.
`compute_quality_metrics()` aggregates the closed-out pairs into rolling
MAE, MAPE, within-tolerance hit-rates (±15% / ±25%), p10–p90 interval
coverage, pinball loss at α=0.1/0.5/0.9, bias, and a per-chokepoint
drift flag (rolling MAE > 1.25× training MAE). The MariNav Router cards
now show a composite 0–100 `Confidence: NN%` chip computed by
`compute_confidence_score()`. The matcher is invoked at the top of
`eta_scheduler.retrain_now()` so a retrain always works against the
freshest labels. No deep learning involved anywhere — pure numpy +
sqlite + pandas on top of the existing XGBoost quantile artifact.

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
| `eta_model.py` | Chokepoint ETA Predictor — XGBoost quantile regression. Extracts labeled transits from `sightings`, exposes `predict_transit_minutes()` / `predict_total_for_route()` (with `force_heuristic` kwarg) / `explain_prediction()` (SHAP top-K contributions in minutes). Lazy-imports xgboost+joblib+shap so `app_simple.py` stays importable without ML libs. |
| `train_eta_model.py` | Offline trainer with 5-fold time-series CV + 27-cell hyperparam sweep + SHAP backend + calibration plot. Saves `models/eta_xgb.joblib`, `eta_meta.json`, `eta_feature_importance.png`, `eta_calibration.png`, `eta_shap_values.npy`. CLI: `--db`, `--seed`, `--no-cv`, `--cv-splits`. |
| `eta_scheduler.py` | Background daemon (`start_eta_scheduler()`, idempotent like `start_consumer()`) that retrains the ETA model once daily when ≥200 real AIS rows have accumulated. Exposes `retrain_now()` for the "Retrain now" UI button. |
| `tests/` | pytest suite (31 tests). `conftest.py` builds in-memory SQLite with synthetic vessel tracks; `test_eta_model.py` covers extract_transits edges + encoding + inference fallbacks; `test_train_eta_model.py` smoke-tests the trainer. Run with `pytest tests/ -v`. |

### Map (`maps.py`)

`create_dashboard_map(filtered_events, show_routes, route_statuses, port_congestion_df)` returns a Plotly `Figure` (orthographic globe). It renders: day/night overlay with terminator line, 5 shipping routes colour-coded by status, 8 port markers colour-coded by congestion, and event markers sized by impact with threat rings for Critical events. Routes are coloured via `ROUTE_STATUS_COLORS` in `config.py`.

### Risk Score Formula (`dynamic_status.py`)

- **Chokepoint (0–100):** `nga_sev × 45 + min(25, ais_drop_points) + critical_nearby × 25 + high_nearby × 10 + news_clusters_score × 6` — see `dynamic_status.py:183-190`. `news_clusters_score` is multi-source (≥2 distinct domains) and decays 0.5× after 24h; the per-chokepoint GDELT lookup uses a 7-day window.
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
