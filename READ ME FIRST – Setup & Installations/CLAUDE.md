# CLAUDE.md — AI Use Declaration + Project Architecture Reference

This file serves two purposes:

1. **AI Use Declaration** (top section) — a transparent record of how we used
   Anthropic's Claude AI assistant during this project

2. **Architecture / dev reference** (bottom section) — a detailed map of the
   codebase, the data flow, and the key formulas. Useful for the a
    project overview, and also serves as context for any future Claude
   sessions on the codebase.

---

## Part 1 — AI Use Declaration

### Transparency statement

We used Claude (Anthropic's AI assistant) to help build, document, and
verify this project. We want to be upfront about exactly how the AI was
involved so our work can be evaluated fairly.

This section lists what Claude *did*, what Claude *did not do*.

### How Claude was used

**1. Workflow planning and task scoping.**
Claude helped us turn vague goals ("build a shipping dashboard") into
concrete week-by-week task lists, scope decisions (e.g. drop ACLED
integration as too complex; lean on GDELT alone), and design trade-offs
(e.g. XGBoost quantile regression vs open source ML) — we chose XGBoost
specifically because it is faster, more interpretable, and fit the project goals
much better than any off the shelf model could. 
Furthermore you will notice that the design of the project is very different to what
a traditional streamlit dashboard would allow. This is because our group was not satisfied
with the design limitations of streamlit and decided to look for solutions. 
We discovered that a common fix for this was to inject custom CSS via Streamlit's markdown component.
This allowed us to leverage design power and flexinility of CSS while still adhearing
to the requirements of the project being compiled entirely in python and streamlit.
Naturally as we have not covered CSS in class we required assistance with design code from Claude.


**2. Code commenting.**
We used Claude do reformat the comments in a way that they were organised, 
easy to understand, and interprable by anyone that didnt spend weeks on this project.

**3. Documentation cleanup.**
We also used Claude to assist us with project structure. specifically with making sure 
files were seperated correctly and according to best practices. As you will be able to tell
in the code itself, there are plenty of lines for fallback scenarios.
This ensures that even if something fails, the dashboard can still be used and interacted with.

**4. ML pipeline assistance.**
The XGBoost chokepoint ETA predictor — including the quantile regression
setup (p10 / p50 / p90), the 5-fold time-series cross-validation, the
27-cell hyperparameter sweep, the SHAP-based "Why this prediction?"
explainability surface, the per-card confidence chip, the live-quality
tracking page (`pages/5_ETA_Quality.py`), and the daily auto-retrain
scheduler — was designed with Claude's help. The team made every
decision on what to include and how to evaluate it; Claude helped
implement the underlying scikit-learn / xgboost / SHAP calls and explain
the numerical tradeoffs.

**5. Smoke-testing before submission.**
Before handing the project in, Claude helped launch the dashboard,
import-test each page module, tested for bugs, and confirm everything works end-to-end.
Additionally, it helped with organising everything in a zip file. This was done to make sure that
the professors would not have any missing files, or dependencies when installing the project

**6. Routine code questions.**
Throughout development we asked Claude to explain unfamiliar libraries
(Plotly's `add_trace` API, NetworkX's k-shortest-paths variants, H3's
hexagonal grid resolution levels, Streamlit caching semantics) and to
suggest idiomatic ways to express things in Python.

### How Claude was NOT used

- The **project idea** is the team's own.
- The **data-source selection** (which APIs, which chokepoints to monitor,
  which ports to track, what risk-score formula to use) was decided by
  the team based on our research.
- The **routing methodology** (using Uber H3 hexagonal grids + a NetworkX
  graph with risk-weighted edges, inspired by the open-source MariNav
  project) was a team architectural decision.
- The **visual design** (the dark "Naval Command" colour palette, the
  globe orthographic projection, the card layout for the 4 route
  alternatives) was designed by the team.
- The **final presentation narrative** — which pages to demo, in what
  order, and what story to tell — is owned by the team.
- The **API keys** in `.env` belong to accounts we registered ourselves.

In all cases the team reviewed and accepted (or rejected) Claude's
suggestions before they made it into the repository.

Additionally, we believe it important to mention that although the code itself
was written with Claudes help, this was NOT a project that can be done with a couple
of prompts (as our commit history can show). The team spent weeks exploring new ideas, features, and correcting previous mistakes.
Every time Claude made an edit we would check the code, understand its logic, and push back on claudes approach.
This was done to ensure the project matched the groups vision as closley as possible, while contemporarily,
ensuring that the whole team knows exactly how the code works. This ensured a group-wide comprehnsions of the programs why and how's.

### What Claude is

Claude is a large language model developed by Anthropic
(<https://www.anthropic.com>). We accessed it through the Claude Code
CLI (<https://claude.com/claude-code>), which lets the assistant read
files, run commands, and propose code edits inside a project directory
under the developer's supervision.

### A note on this file itself

The Setup Guide, README, QUICKSTART, and this AI Use Declaration were
drafted with Claude's help and then reviewed by the team before
submission. The factual claims about the project state (file sizes, row
counts, training metadata, dependency list) were verified by inspecting
the actual repository — we did not let Claude assert numbers without
checking the underlying data.

---

## Part 2 — Project Architecture Reference

The rest of this file is a compact but complete reference to the codebase,
data flow, and key formulas. It is what we would hand to a colleague who
needed to understand the project quickly.

### Commands

**Run the dashboard** (from `CS-project/`):
```bash
streamlit run app.py
```

**Run the simplified bare-bones version** (no live data, useful as an
environment smoke-test):
```bash
streamlit run app_simple.py
```

**Test all API integrations:**
```bash
python test_apis.py
```

**Install dependencies:**
```bash
pip install -r "READ ME FIRST – Setup & Installations/requirements.txt"
```

**Train the ETA predictor (optional — already trained):**
```bash
python train_eta_model.py --seed         # cold start: synthetic seed + full CV + hyperparam sweep
python train_eta_model.py --seed --no-cv # fast iteration (skip CV + sweep)
python train_eta_model.py                # real AIS data; refuses if <200 rows
```
Pipeline: 5-fold time-series CV → 27-cell hyperparam sweep → train final
q10/q50/q90 quantile boosters with the best config → SHAP backing data +
calibration plot. Writes everything under `models/`.

**Run the test suite:**
```bash
pytest tests/ -v   # 31 tests, ~8s
```

### Architecture

Streamlit-based shipping risk dashboard aggregating ~9 external APIs to
help shipping companies plan routes based on geopolitical risk, port
congestion, fuel costs, and weather.

### Data flow

```
app.py
  └── _load_core_data() [cached 15min]
        ├── sample_data.get_events_data()        → events_aggregator (GDELT-backed live feed)
        ├── APIClient.get_oil_price()            → FRED API
        ├── APIClient.get_shipping_index()       → FRED API
        └── APIClient.get_exchange_rates()       → ExchangeRate-API

  └── dynamic_status.py [each function cached separately]
        ├── compute_shipping_status(events_json) → GDELT events + NGA severity + AIS transit drop → route risk scores
        ├── compute_risk_summary(events_json)    → GDELT event proximity → regional risk table
        ├── compute_port_congestion(events_json) → live AIS queue + GDELT news + Open-Meteo marine → port scores
        └── get_news_feed()                      → Guardian API + NewsAPI → unified feed

  └── analytics.RiskAnalytics [pure computation, no API calls]
        ├── get_summary_metrics()  → KPI bar + alert banner
        └── calculate_cost_impact() → financial impact panel
```

### Critical caching pattern

All `dynamic_status.py` functions accept `events_df.to_json()` (a JSON
string) rather than a DataFrame directly. Streamlit's `@st.cache_data`
cannot hash DataFrames, so the JSON string is used as the cache key.
Always pass `.to_json()` when calling these functions, and reconstruct
with `pd.read_json(StringIO(json_str))` inside.

### Key files

| File | Role |
|---|---|
| `app.py` | Main entry point: page config, header, navigation, globe + status panels + tabs |
| `pages/0_Landing.py` | Static welcome page (no API calls; warms caches in the background) |
| `pages/1_Route_Planner.py` | 5-route chokepoint comparison + scenario simulator |
| `pages/2_Intel_Feed.py` | News feed + NGA warnings + multi-source threat watch |
| `pages/3_Market_Costs.py` | Live oil / freight / FX / bunker prices + fleet cost impact |
| `pages/4_MariNav_Router.py` | Flagship: H3 + NetworkX routing under 4 objectives + ML ETA |
| `pages/5_ETA_Quality.py` | ML accuracy dashboard: predicted-vs-actual scatter + drift KPIs |
| `maps.py` | Plotly orthographic globe: routes, ports, event markers, AIS, day/night |
| `marinav_router.py` | The routing engine: ocean graph build + Dijkstra + economics + 4 alternatives |
| `dynamic_status.py` | All live risk computations (shipping, ports, regions, news) |
| `analytics.py` | `RiskAnalytics` class — cost/delay/metric calculations (pure functions) |
| `components.py` | `filter_events()`, `generate_intel_brief()`, `render_comparison_table()` |
| `config.py` | Static constants: `MAJOR_SHIPPING_ROUTES`, `EVENT_TYPES`, `IMPACT_LEVELS` |
| `api_config.py` | API endpoints, cache TTLs, `STRAIT_COORDINATES`, `CRITICAL_PORTS`, `KEY_REGIONS` |
| `api_integrations.py` | `APIClient` static methods for every external API |
| `ais_consumer.py` | Live AISStream WebSocket consumer → SQLite (`.ais_positions.db`) |
| `eta_model.py` | XGBoost quantile ETA predictor — extract_transits + predict + SHAP explain |
| `train_eta_model.py` | Offline trainer: 5-fold CV + 27-cell sweep + SHAP + calibration plot |
| `eta_scheduler.py` | Background daemon that retrains the ETA model once per day |
| `eta_quality.py` | Live prediction-quality tracking: MAE, MAPE, coverage, drift |
| `vessel_physics.py` | Admiralty-coefficient fuel formula + Monte Carlo voyage simulation |
| `canal_tolls.py` | Suez + Panama toll lookup tables (indicative 2024–2025 USD) |
| `nga_warnings.py` | NGA maritime safety broadcast warnings fetcher + severity scoring |
| `news_classifier.py` | Optional Groq-based news deduplication + topic tagging |
| `events_aggregator.py` | GDELT DOC API → canonical events DataFrame |
| `port_baselines.py` | Static per-port baselines (berth counts, anchorage radius, turnaround days) |
| `data_loader.py` | Shared cached data loader (concurrent fan-out via ThreadPoolExecutor) |
| `disk_cache.py` | On-disk result cache that survives Streamlit restarts |
| `ui_helpers.py` | Shared CSS, header / nav / footer renderers, colour maps |
| `tests/` | pytest suite (31 tests, ~8s) |

### Risk score formulas

- **Chokepoint score (0–100):**
  `nga_sev × 45 + min(25, ais_drop_points) + critical_nearby × 25 +
   high_nearby × 10 + news_clusters_score × 6`
  See `dynamic_status.py:183-190`. `news_clusters_score` requires
  ≥2 distinct news domains and decays 0.5× after 24h. The per-chokepoint
  GDELT lookup uses a 7-day window.

- **Port congestion score (0–100):** delay-derived from
  `(queue / berths) × baseline_turnaround_days × weather_multiplier`,
  where `queue` is the live AIS at-anchor count (vessels with SOG < 0.5 kn
  inside the port anchorage), `weather_multiplier` comes from Open-Meteo
  marine (wave height + wind), and a batched GDELT news check provides a
  secondary congestion signal where AIS coverage is sparse.

- **Regional score:** `critical × 3 + high × 2 + other × 1` with
  thresholds at 2 / 4 / 6.

### APIs & keys

Keys are stored in `api_config.py` with `os.getenv()` fallbacks; the
actual values are loaded from `.env` at module import time. Keys we ship
in `.env`: `NEWSAPI_KEY`, `FRED_API_KEY`, `GUARDIAN_API_KEY`,
`OPENWEATHER_KEY`, `AISSTREAM_KEY`, `GROQ_API_KEY`.

APIs that need **no key**: GDELT, NOAA, World Bank, ExchangeRate-API,
NGA broadcast warnings, Ship & Bunker (scraped).

### Cache TTLs

| Data type | TTL | Source |
|---|---|---|
| News articles | 5 min | `CACHE_TTL_NEWS` |
| Events, shipping, ports, regions | 15 min | `CACHE_TTL_EVENTS` |
| Prices, exchange rates | 30 min | `CACHE_TTL_PRICES` |

### Live ML quality tracking

Every call to `predict_transit_minutes()` writes one row to the
`eta_predictions` table in `.ais_positions.db` with the inputs and
outputs. `eta_quality.match_open_predictions()` later joins each open
prediction to the realised entry/exit timestamps from `sightings` (same
bbox + gap-split logic as the trainer), filling in `actual_min`.
`compute_quality_metrics()` aggregates the closed-out pairs into rolling
MAE, MAPE, within-tolerance hit-rates (±15% / ±25%), p10–p90 interval
coverage, pinball loss at α=0.1/0.5/0.9, bias, and a per-chokepoint
drift flag (rolling MAE > 1.25× training MAE). The MariNav Router cards
show a composite 0–100 `Confidence: NN%` chip computed by
`compute_confidence_score()`.

The matcher is invoked at the top of `eta_scheduler.retrain_now()` so a
retrain always works against the freshest labels. **No deep learning
involved anywhere** — pure numpy + sqlite + pandas on top of the
existing XGBoost quantile artifact.

### Current tab structure of `app.py`

`app.py` renders four tabs at the bottom of the main dashboard:
- **Shipping & Ports** — chokepoint status + regional risk + port
  congestion
- **Analytics** — event-type / impact charts + 30-day timeline
- **Impact** — financial cost estimates
- **Fuel Calculator** — voyage cost estimator with live WTI crude + route
  risk surcharge

---

*End of CLAUDE.md.*
