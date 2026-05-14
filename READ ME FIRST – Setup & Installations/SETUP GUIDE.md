# Setup & Installation Guide
## TradeWatch — Maritime Risk Dashboard

This is the complete, step-by-step guide for getting the dashboard running on
your own computer **exactly as we have it** — with the trained machine
learning model, the live AIS database, and all the API keys already set up.

If anything in this guide fails, scroll down to the **Troubleshooting** section
near the end.

---

## TL;DR (5 commands, if you trust the defaults)

```bash
unzip "<our submission zip>"
cd "CS PROJECT/CS-project" (or just `cd CS-project`) #if you opened the CS PROJECT folder in VSCode
pip install -r "READ ME FIRST – Setup & Installations/requirements.txt"
streamlit run app.py
# then open http://localhost:8501 in your browser
```

Read on for the full version.

---

## 1. What you're about to install

TradeWatch is a Python / Streamlit web app. When you run it, it:

- Starts a local web server on your computer (default port 8501).
- Opens a 3-D globe with live shipping routes, port congestion, geopolitical
  events, and live satellite AIS vessel positions.
- Lets you plan a sea voyage between any two major ports and see four ranked
  alternatives with full economics (fuel, OPEX, canal tolls, war-risk
  surcharge, CO₂).
- Predicts how long each vessel will take to clear each chokepoint using a
  trained XGBoost machine-learning model — with confidence intervals.

Everything runs locally. Nothing is uploaded anywhere.

---

## 2. Prerequisites

You need:

- **Python 3.9 or later** — check with `python --version` or `python3 --version`.
  Download from <https://www.python.org/downloads/> if missing.
- **pip** — comes bundled with Python.
- A **terminal**:
  - macOS: Terminal.app or iTerm2
  - Windows: PowerShell or Command Prompt
  - Linux: any shell
- About **1 GB free disk space** (the project + dependencies).
- Internet connection (for the live data feeds; the trained model and the
  AIS history are local and work offline).

We recommend installing inside a virtual environment to avoid polluting your
system Python, but it is not strictly required:

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows (PowerShell)
venv\Scripts\Activate.ps1
```

---

## 3. Unzip the submission and `cd` into the project

After unzipping you should have a top-level folder structure like:

```
CS PROJECT/
└── CS-project/                  ← the actual project root, cd into this
    ├── app.py
    ├── .env                     ← API keys, already filled in
    ├── .ais_positions.db        ← ~380 MB AIS history (DO NOT DELETE)
    ├── models/                  ← trained ML model (DO NOT DELETE)
    ├── pages/                   ← the 6 dashboard pages
    ├── .streamlit/              ← theme + server config
    └── READ ME FIRST – Setup & Installations/
        ├── README.md
        ├── SETUP GUIDE.md       ← this file
        ├── QUICKSTART.md
        ├── requirements.txt
        └── CLAUDE.md
```

From a terminal:

```bash
cd "<wherever you unzipped>/CS PROJECT/CS-project"
```

Everything else in this guide assumes you are sitting inside `CS-project/`.

---

## 4. Install Python dependencies

There is **one** combined requirements file. Run:

```bash
pip install -r "READ ME FIRST – Setup & Installations/requirements.txt"
```

That single command installs every library the app needs.

If you get a permission error on macOS / Linux, try:

```bash
pip install --user -r "READ ME FIRST – Setup & Installations/requirements.txt"
```

---

## 5. Packages that sometimes need explicit reinstall

`pip install -r requirements.txt` covers everything, but on some systems
specific packages don't always install cleanly. If the dashboard launches but
a page errors out, install these individually and try again.

### 5.1 xgboost — the ETA prediction model

Without this the dashboard still works, but the ML ETA prediction falls back
to a simple per-chokepoint heuristic and you'll see a banner that says
*"Predictor: using fallback formula only"*.

```bash
pip install xgboost
python -c "import xgboost; print(xgboost.__version__)"
```

### 5.2 h3 — the maritime routing grid

Uber's hexagonal geographic indexing library. The MariNav Router page builds
its routing graph on H3 — without it, that page throws ImportError.

```bash
pip install h3
python -c "import h3; print(h3.__version__)"
```

### 5.3 shap — the "Why this prediction?" explanations

Used by the SHAP top-K contributions expander on each route card. Without
shap the expander just says "No explanation available".

```bash
pip install shap
python -c "import shap; print(shap.__version__)"
```

### 5.4 requests-cache — API response caching

Caches GDELT / FRED / NewsAPI responses to a local SQLite file so the app
doesn't hammer the rate-limited APIs on every refresh.

```bash
pip install requests-cache
python -c "import requests_cache; print(requests_cache.__version__)"
```

### 5.5 feedparser — Maritime RSS news feeds

Parses the gCaptain / Maritime Executive / Splash247 / Maritime Standard RSS
feeds that show up in the Intel Feed page.

```bash
pip install feedparser
python -c "import feedparser; print(feedparser.__version__)"
```

### Install all of the above in one shot

```bash
pip install xgboost h3 shap requests-cache feedparser
```

---

## 6. Files already included with this submission — *do not delete*

These ship inside the zip and are what makes the dashboard look "alive" the
moment you launch it. They live at the root of `CS-project/`.

| Path | Size | What it does | Safe to delete? |
|---|---|---|---|
| `.env` | tiny | All six API keys we use. **We filled this in for you**, so every live feed works the moment you launch. | NO |
| `.ais_positions.db` | ~380 MB | Local SQLite database of live AIS satellite vessel-position data we collected. Contains ~4.77 million sightings and ~3,230 logged ETA predictions. **This is what populates the ETA Quality page's plotly scatter on first launch.** | NO |
| `models/eta_xgb.joblib` | 357 KB | Trained XGBoost quantile regression model (p10 / p50 / p90 transit time per chokepoint). Already trained on 1,491 transits (674 real + 1,190 synthetic seed). | NO |
| `models/eta_meta.json` | small | Training metadata: feature names, best hyperparameters, per-chokepoint MAE, etc. Used by the ML diagnostics expander. | NO |
| `models/eta_feature_importance.png` | small | Top-15 feature importance chart shown in the diagnostics expander. | NO |
| `models/eta_calibration.png` | small | Predicted-vs-actual calibration plot. | NO |
| `models/eta_shap_values.npy` + `eta_shap_X_test.npy` + `eta_shap_feature_names.json` | small | SHAP backing data for the per-prediction "Why this prediction?" expanders. | NO |
| `.streamlit/config.toml` | tiny | Theme + server settings (port, headless mode flags). | NO |

If any of these go missing, the corresponding feature falls back gracefully
(or shows an empty state) — nothing crashes — but the dashboard won't look
the way it does for us.

---

## 7. API keys — *we already filled them in for you*

The dashboard depends on six external services. Their keys live in the
`.env` file at the root of `CS-project/`. **We have already populated `.env`
with our keys**, so you do not need to register for anything.

The six keys in `.env`:

| Variable | Provider | Used for |
|---|---|---|
| `NEWSAPI_KEY` | newsapi.org | Breaking news feed (Intel Feed page) |
| `FRED_API_KEY` | St. Louis Fed | WTI oil price + IMF freight index (Market & Costs page) |
| `OPENWEATHER_KEY` | openweathermap.org | Port weather alerts (Port Congestion panel) |
| `GUARDIAN_API_KEY` | The Guardian Open Platform | Guardian newspaper articles (Intel Feed) |
| `AISSTREAM_KEY` | aisstream.io | Live satellite AIS vessel position WebSocket (Main Dashboard) |
| `GROQ_API_KEY` | console.groq.com | Optional: news-deduplication LLM |

If you want to swap in your own keys for any reason, just edit `.env` in any
text editor — the dashboard reloads it on the next launch.

APIs that need **no key** and work out of the box:

- **GDELT** — global event intelligence + armed conflict reporting
- **NOAA** — weather alerts
- **World Bank** — trade data
- **ExchangeRate-API** — currency rates
- **NGA** — official US maritime safety broadcast warnings
- **Ship & Bunker** — live marine fuel prices (we scrape their public website)

---

## 8. Run the dashboard

From inside `CS-project/`:

```bash
streamlit run app.py
```

Streamlit will print something like:

```
You can now view your Streamlit app in your browser.
Local URL:  http://localhost:8501
```

Open the **Local URL** in any modern browser (Chrome, Safari, Firefox, Edge).

To stop the dashboard later: press `Ctrl + C` in the terminal.

---

## 9. What you should see on first launch

The first page that opens is the **Landing** page — a static welcome screen
with the project mission. While you read it, a background thread quietly
warms up all the slow data caches, so the *next* page you open is instant.

Click **"Open Main Dashboard →"** and you'll land on the live globe.

Page-by-page, here is what should appear:

### Main Dashboard
- Globe centred on the world ocean.
- Five shipping routes drawn in colour-coded lines (green = operational,
  red = critical).
- Eight port markers with colour-coded congestion scores.
- Event markers (red/orange dots) for recent geopolitical events.
- Live vessel positions appear within ~30 seconds as AIS data streams in.
- Day-night terminator overlay across the globe.
- Right panel: "Route Status" with one expandable row per route and "Live
  Events" with the five most recent.
- Bottom: a "Data Freshness" strip showing the age of each feed.

### Route Planner
- A 5-route comparison table (Suez / Hormuz / Malacca / Panama / English
  Channel) with risk score, status, expected delay, cost impact.
- A "Simulate route failure" dropdown for what-if scenarios.
- A regional risk summary table.
- A 30-day event-activity area chart.

### Intel Feed
- "Intelligence Brief" auto-generated bullet points at the top.
- Left column: regional risk table, **NGA maritime warnings** (a red list
  of official safety broadcasts), recommended actions, multi-source threat
  watch, event-type bar chart.
- Right column: live news feed grouped into expandable region sections
  (Suez / Hormuz / Malacca / Panama / Bosphorus / English Channel / Other).
- Topic filter buttons (All / conflict / shipping / trade / weather / other).

### Market & Costs
- Seven market cards along the top (WTI crude, IMF freight index, four
  currency pairs, Singapore VLSFO bunker price).
- Live bunker prices table for VLSFO / IFO380 / MGO across major bunker ports.
- Financial Impact panel: daily and monthly cost impact estimate with
  active multipliers.
- Chokepoint Delays & Costs table.

### MariNav Router (the flagship)
- Two dropdowns at the top: Origin Port + Destination Port.
- Click **Calculate Route**. The router will:
  1. Build an H3 + NetworkX graph of the world ocean
  2. Run Dijkstra's algorithm 4 times under 4 different objectives
  3. Compute economics + ML ETA + Monte Carlo confidence bands for each
- You get FOUR cards: **Recommended / Fastest / Safest / Cheapest**, each
  with distance, days, max risk, fuel use, CO₂, ML ETA with p10–p90 bar,
  and a confidence chip.
- A Plotly globe below shows all four routes drawn at once.
- A per-leg breakdown table for the selected route.
- A "Why this prediction?" SHAP expander per chokepoint.

### ETA Quality
- Section 1: "How the ETA is calculated" — model card.
- Section 2: live feature inspector (pick a chokepoint + vessel, see what
  the model predicts right now and the top SHAP factors).
- Section 3: four big KPI numbers (within ±15%, within ±25%, reality inside
  range, average error).
- Section 4: **the Predicted-vs-Actual plotly scatter plot** — one dot per
  matched prediction, with a y=x dashed reference line. This populates
  immediately from the included `.ais_positions.db`.
- Section 5: per-chokepoint accuracy table.
- Section 6: drift detection + "Retrain now" button.

---

## 10. Optional — run the test suite

We ship 31 pytest tests covering the routing math, the ETA model, the
training pipeline, and the data extraction logic. They take ~8 seconds.

```bash
python -m pytest tests/ -v
```

Should print `31 passed`.

---

## 11. Optional — retrain the ML model from scratch

The trained model is already included. You only need this if you want to
verify the training pipeline yourself or rebuild from fresh data.

```bash
# Fast path: synthetic seed + skip cross-validation (~30 seconds)
python train_eta_model.py --seed --no-cv

# Full path: 5-fold time-series CV + 27-cell hyperparam sweep (~2-5 minutes)
python train_eta_model.py --seed

# Real AIS data only — refuses to train if <200 real rows exist
python train_eta_model.py
```

The trainer overwrites everything in `models/`. To revert, re-extract the
`models/` folder from our submission zip.

---

## 12. Troubleshooting

### "ModuleNotFoundError: No module named 'xgboost'" (or similar)
A required package didn't install. Re-run:
```bash
pip install -r "READ ME FIRST – Setup & Installations/requirements.txt"
```
If that doesn't fix it, install the specific module from Section 5 above.

### "Address already in use" on launch
Port 8501 is occupied. Either close the other process or run on a different
port:
```bash
streamlit run app.py --server.port=8502
```

### "Predictor: using fallback formula only" warning banner
Either xgboost isn't installed, or `models/eta_xgb.joblib` is missing /
corrupted. Re-install xgboost and confirm the file exists in `models/`.

### Page 5 (ETA Quality) plotly scatter is empty
`.ais_positions.db` is missing from the project root. Re-extract it from
our submission zip. The dashboard cannot reconstruct this — it carries
real AIS data we collected over several days.

### "Live event feed unavailable" warning
GDELT is rate-limiting or briefly offline. Wait a minute and refresh — the
feed retries automatically. Other pages keep working in the meantime.

### Globe is blank / no routes drawn
Hard-refresh the browser (Cmd+Shift+R / Ctrl+F5). Plotly sometimes caches
old WebGL state.

### Vessels never appear on the map
The AIS WebSocket needs ~30 seconds to start streaming after launch. Check
the data-freshness strip at the bottom of the Main Dashboard — it shows
"AIS streaming (Xs ago)" once the feed is live.

### Anything else
Run the built-in API health-check from inside `CS-project/`:
```bash
python test_apis.py
```
It prints OK / FAIL for every external service and points at any specific
breakage.

---

## Architecture cheat sheet

See **`CLAUDE.md`** in this same folder for the full architecture diagram,
data-flow chart, key-files table, risk-score formulas, and cache TTL
reference. (`CLAUDE.md` doubles as our AI-use declaration and project
overview.)
