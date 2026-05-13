# Setup & Installation Guide
## Maritime Risk Dashboard — Local Development

Everything you need to get the app running at 100%, including the ML predictor,
live AIS vessel tracking, MariNav routing, and SHAP explanations.

---

## 1. Prerequisites

The app runs on **Anaconda Python** (already installed on this machine at `/opt/anaconda3`).
All commands below use the Anaconda pip/python — do NOT use the system Python
(`/Library/Developer/CommandLineTools/...`), it is missing almost every package.

```bash
# Always verify you are using the right Python before installing anything
/opt/anaconda3/bin/python --version
# Should print: Python 3.x.x (not 2.x)

which streamlit
# Should print: /opt/anaconda3/bin/streamlit
```

---

## 2. Install All Dependencies at Once

From inside the project folder:

```bash
cd "/Users/manuelantezza/Desktop/CS PROJECT/CS-project"
/opt/anaconda3/bin/pip install -r requirements.txt
```

This installs every library the app needs. If you have a fresh Anaconda install,
this single command is enough to get the core dashboard working.

---

## 3. Packages That Must Be Installed Individually

Some packages are **not always pulled in** by `requirements.txt` in certain Anaconda
environments. Install each one explicitly if the app misbehaves.

### 3.1 xgboost — ML ETA Predictor

Needed for: the chokepoint transit-time predictions on the MariNav Router page.
Without this, the app falls back to the simple per-chokepoint rule of thumb and
shows the red warning banner:
> "Predictor: using fallback formula only — no trained model loaded."

```bash
/opt/anaconda3/bin/pip install xgboost
```

Verify:
```bash
/opt/anaconda3/bin/python -c "import xgboost; print(xgboost.__version__)"
```

### 3.2 h3 — MariNav Hex-Grid Routing

Needed for: the MariNav Router page (page 4). h3 is Uber's hexagonal geographic
indexing library used to build the routing graph over the ocean. Without it the
router cannot generate waypoints and the page will throw an ImportError.

```bash
/opt/anaconda3/bin/pip install h3
```

Verify:
```bash
/opt/anaconda3/bin/python -c "import h3; print(h3.__version__)"
```

### 3.3 shap — "Why this prediction?" Explanations

Needed for: the per-chokepoint SHAP explanation expanders on MariNav Router
("Why this prediction?"). Without shap the expanders still appear but show
"No explanation available" instead of the top-3 feature contributions.

```bash
/opt/anaconda3/bin/pip install shap
```

Verify:
```bash
/opt/anaconda3/bin/python -c "import shap; print(shap.__version__)"
```

### 3.4 requests-cache — API Response Caching

Needed for: caching external API responses (GDELT, ACLED, FRED, etc.) so the
app does not hammer rate-limited APIs on every refresh. Without it some API
methods fall back to uncached requests and you may hit rate limits faster.

```bash
/opt/anaconda3/bin/pip install requests-cache
```

Verify:
```bash
/opt/anaconda3/bin/python -c "import requests_cache; print(requests_cache.__version__)"
```

### 3.5 feedparser — Maritime RSS News Feed

Needed for: the maritime industry RSS feeds (gCaptain, Maritime Executive,
Splash247, The Maritime Standard) that populate the news section. Without this
the RSS feeds return empty and only Guardian/NewsAPI articles appear.

```bash
/opt/anaconda3/bin/pip install feedparser
```

Verify:
```bash
/opt/anaconda3/bin/python -c "import feedparser; print(feedparser.__version__)"
```

---

## 4. Install Everything Missing in One Shot

If you want to install all the above at once:

```bash
/opt/anaconda3/bin/pip install xgboost h3 shap requests-cache feedparser
```

---

## 5. Train the ML ETA Predictor

After installing xgboost and shap, you need a trained model artifact.
The file `models/eta_xgb.joblib` must exist and be valid for the green
predictor chip to appear on MariNav Router.

### Option A — Seed with synthetic data (instant, no AIS history needed)

```bash
cd "/Users/manuelantezza/Desktop/CS PROJECT/CS-project"
/opt/anaconda3/bin/python train_eta_model.py --seed --no-cv
```

This generates ~3,000 synthetic vessel transits and trains the model in under
a minute. Good enough to test all ML features.

### Option B — Full training with CV and hyperparam sweep (slower, best accuracy)

```bash
/opt/anaconda3/bin/python train_eta_model.py --seed
```

Runs 5-fold time-series cross-validation + a 27-cell hyperparameter sweep before
training the final quantile models. Takes 2–5 minutes. Writes:
- `models/eta_xgb.joblib` — the model artifact
- `models/eta_meta.json` — training metadata
- `models/eta_feature_importance.png` — feature importance chart
- `models/eta_calibration.png` — calibration plot
- `models/eta_shap_values.npy` — SHAP backing data

After training, restart the Streamlit app — the predictor chip will turn green.

---

## 6. Run the App

```bash
cd "/Users/manuelantezza/Desktop/CS PROJECT/CS-project"
/opt/anaconda3/bin/streamlit run app.py
```

Opens at: **http://localhost:8501**

To stop: `Ctrl + C` in the terminal.

---

## 7. API Keys (Optional but Recommended)

The dashboard works with zero keys — it falls back to free APIs automatically.
Adding keys unlocks better data quality and higher rate limits.

Keys are set in the `.env` file (already present in the project folder):

```
# .env
NEWSAPI_KEY=your_key_here
FRED_API_KEY=your_key_here
GUARDIAN_API_KEY=your_key_here
OPENWEATHER_KEY=your_key_here
AISSTREAM_KEY=your_key_here
```

Where to get each key (all free tiers):

| Key | Where to get it | What it unlocks |
|---|---|---|
| `NEWSAPI_KEY` | https://newsapi.org — "Get API Key" | Breaking news feed |
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/fred-api.html | Live oil prices + shipping index |
| `GUARDIAN_API_KEY` | https://open-platform.theguardian.com | Guardian news articles |
| `OPENWEATHER_KEY` | https://openweathermap.org/api — free tier | Port weather alerts |
| `AISSTREAM_KEY` | https://aisstream.io — free tier | Live vessel position WebSocket feed |

APIs that need **no key** and work immediately:
- ACLED (conflict events)
- GDELT (global event intelligence)
- NOAA (weather alerts)
- World Bank (trade data)
- Exchange Rates API

---

## 8. Verify Everything Is Working

Run the built-in API test script:

```bash
cd "/Users/manuelantezza/Desktop/CS PROJECT/CS-project"
/opt/anaconda3/bin/python test_apis.py
```

Run the test suite:

```bash
/opt/anaconda3/bin/python -m pytest tests/ -v
```

All 31 tests should pass. If xgboost or shap are missing some tests will skip
or fail — install them (section 3 above) and re-run.

Quick package check — paste this in Terminal to see what is and is not installed:

```bash
/opt/anaconda3/bin/python -c "
pkgs = {
    'streamlit': 'Core UI',
    'xgboost': 'ML ETA predictor',
    'h3': 'MariNav hex routing',
    'shap': 'SHAP explanations',
    'requests_cache': 'API caching',
    'feedparser': 'Maritime RSS feeds',
    'joblib': 'Model serialization',
    'sklearn': 'ML preprocessing',
    'plotly': 'Charts and globe',
    'pandas': 'Data processing',
    'websockets': 'Live AIS stream',
}
for pkg, desc in pkgs.items():
    try:
        m = __import__(pkg)
        v = getattr(m, '__version__', 'ok')
        print(f'  OK   {pkg} ({v}) — {desc}')
    except ImportError:
        print(f'  MISS {pkg} — {desc}  <-- needs pip install {pkg}')
"
```

---

## 9. Troubleshooting

**Red warning banner on MariNav Router ("no trained model loaded")**
→ xgboost is not installed, or the model artifact is missing.
→ Run: `/opt/anaconda3/bin/pip install xgboost` then retrain (section 5).

**MariNav Router page crashes or shows ImportError**
→ h3 is not installed.
→ Run: `/opt/anaconda3/bin/pip install h3`

**"Why this prediction?" expander shows no data**
→ shap is not installed.
→ Run: `/opt/anaconda3/bin/pip install shap` and restart the app.

**News section shows fewer articles than expected**
→ feedparser is not installed (no RSS feeds) or NEWSAPI_KEY is missing.
→ Run: `/opt/anaconda3/bin/pip install feedparser`

**API calls fail or return no data on every refresh**
→ requests-cache is not installed (no caching).
→ Run: `/opt/anaconda3/bin/pip install requests-cache`

**App opens but map is blank**
→ Usually a plotly or pandas version mismatch.
→ Run: `/opt/anaconda3/bin/pip install --upgrade plotly pandas`

**"wrong" Python (system Python) is being used**
→ Always prefix commands with `/opt/anaconda3/bin/` as shown above.
→ Or activate the conda base environment: `conda activate base`
