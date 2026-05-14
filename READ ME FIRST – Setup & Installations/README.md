# TradeWatch — Shipping Route Intelligence Dashboard

**HSG CS Project · War Room team**

A live web dashboard that helps shipping companies pick the safest, fastest, or
cheapest sea route between any two major ports, based on what is actually
happening in the world right now — armed conflicts, port congestion, vessel
positions from satellite AIS, oil and bunker prices, weather, and official
maritime safety warnings.

---

## What you will see when you launch it

Seven pages, all navigable from the top bar:

1. **Landing** — a one-screen welcome with the project's mission, the
   four route objectives we support, and an "Open Main Dashboard" button.
2. **Main Dashboard** — a 3-D globe with the world's shipping lanes
   colour-coded by live risk, port-congestion markers, recent
   geopolitical events, live vessel positions, and a day-night overlay.
3. **Route Planner** — a side-by-side comparison of the five major
   shipping chokepoints (Suez, Hormuz, Malacca, Panama, English
   Channel) with a "what if Suez goes down" simulator.
4. **Intel Feed** — an automatically generated intelligence brief plus
   live news clustered by region, official NGA maritime warnings, and a
   multi-source threat watch.
5. **Market & Costs** — live WTI crude, IMF freight index, FX rates,
   live bunker (marine fuel) prices, and a fleet-wide cost-impact panel.
6. **MariNav Router** — *our flagship feature.* Pick an origin port,
   a destination, a vessel class, and click Calculate. You get FOUR
   ranked routes — Recommended, Fastest, Safest, Cheapest — each with
   full economics, an ML-based ETA with confidence intervals, a "why
   this route" explanation, and a per-leg breakdown.
7. **ETA Quality** — the report card for our machine-learning ETA
   predictor: how accurate it has been on real vessel transits, broken
   down by chokepoint, with drift detection.

---

## How to run it

The full step-by-step is in **`SETUP GUIDE.md`** (in this same folder).
TL;DR is in **`QUICKSTART.md`**.

Roughly:

```bash
cd "CS-project"
pip install -r "READ ME FIRST – Setup & Installations/requirements.txt"
streamlit run app.py
```

Then open <http://localhost:8501> in a browser.

---

## What's already included in this submission

You do **not** need to train any model, fetch any data, or register for any
API yourself. Everything is pre-bundled:

- **Trained ML model** at `models/eta_xgb.joblib` (XGBoost quantile
  regression, trained on 1,491 chokepoint transits).
- **Live AIS history** at `.ais_positions.db` (~380 MB SQLite file with
  millions of satellite AIS position rows + thousands of logged ETA
  predictions). This is what makes the ETA Quality page's
  "Predicted vs actual" scatter plot populate on first launch.
- **Pre-filled `.env`** with all six API keys we use (NewsAPI, FRED,
  OpenWeather, Guardian, AISStream, Groq).
- **Pre-built `.streamlit/`** config with the theme and server settings
  we use.

> ⚠️ **Do not delete** `.ais_positions.db`, `models/`, `.env`, or
> `.streamlit/`. They sit at the root of `CS-project/` and they ARE
> the project state. Without them the dashboard will boot but several
> pages (ETA Quality especially) will render empty.

---

## Files in this folder

- **`README.md`** — this file. The front door.
- **`SETUP GUIDE.md`** — exhaustive step-by-step setup. **Read this if
  the TL;DR doesn't work.**
- **`QUICKSTART.md`** — 5-line copy-paste run instructions.
- **`requirements.txt`** — Python dependencies. Install with
  `pip install -r "READ ME FIRST – Setup & Installations/requirements.txt"`.
- **`CLAUDE.md`** — AI Use Declaration: transparent record of how we
  used Claude (Anthropic's AI assistant) during this project. Also
  doubles as a project architecture reference.

---

## Questions, problems

If any page errors out, check the troubleshooting section near the
bottom of `SETUP GUIDE.md`. The most common cause is a missing Python
library — re-run the install command above.
