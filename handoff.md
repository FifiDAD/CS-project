# Handoff to the next Claude session

You are picking up work mid-task on the TradeWatch / MariNav Router
shipping-risk dashboard. The user is a CS student preparing a class
presentation on the project's ML system. This document captures
everything you need to continue without re-deriving context.

**Working directory:** `/Users/alexanderovsyannikov/Downloads/CS PROJECT/CS-project`
**Active plan file:** `/Users/alexanderovsyannikov/.claude/plans/hey-claude-check-the-floating-crab.md` — **read this first.**
**Streamlit URL when running:** `http://localhost:8501`
**Python interpreter:** `"/Users/alexanderovsyannikov/Downloads/CS PROJECT/venv/bin/python"` (note: venv lives one level UP from CS-project, not at `.venv/`)
**Pytest entrypoint:** `"/Users/alexanderovsyannikov/Downloads/CS PROJECT/venv/bin/pytest"`

## Hard constraints (do not violate)

- **No deep learning.** XGBoost is OK (gradient boosting on trees); torch / tensorflow / keras are forbidden. Verify with `grep -RIn "torch\|tensorflow\|keras" --include="*.py" .` (must return zero).
- **Plain-English dashboard copy.** The user (and their audience) is non-technical. Technical terms (`XGBoost`, `q10/q50/q90`, `MAE`, `R²`, `SHAP`, `pinball`, `one-hot`, `heuristic`) must stay confined to the collapsed "🤖 ML diagnostics" expander in `pages/4_MariNav_Router.py:295-417`. Everywhere else, use the vocabulary table in the plan file.
- **The ETA does NOT assume a tanker.** Default vessel is "Panamax bulker"; the sidebar selectbox at `pages/4_MariNav_Router.py:269` drives the model's `ship_type` input. Make this visibility obvious — the in-flight task is to add "Vessel assumed: {vessel} at {speed} kn" on every prediction surface.
- **Prediction logging is best-effort.** Never let logging failure crash inference. `_log_prediction` in `eta_model.py` is wrapped in try/except for a reason.
- **WAL is on.** `.ais_positions.db` is in `journal_mode=WAL` (set by `ais_consumer._init_db()` and `eta_model._ensure_predictions_table()`). Do not remove these pragmas.
- **Feature parity training ↔ inference.** `queue_depth` is a ±5-min snapshot via `ais_consumer.live_queue_snapshot()`. `recent_throughput_24h` is a 24h count via `transits_24h()`. These two were swapped before and broke ETA accuracy — see plan history. There is a test pinning the ±300s window (`tests/test_eta_quality.py::test_live_queue_snapshot_matches_training_window`).

## What has been done across recent sessions

1. **ETA Quality system built**: prediction logging table `eta_predictions` in `.ais_positions.db`, matcher in `eta_quality.py`, live KPI metrics, composite 0–100 confidence chip on route cards, new page `pages/5_ETA_Quality.py`. SHAP explainer + worked example added under "Why this prediction?" expander.
2. **SQLite lock-contention fix**: WAL mode on the AIS DB + short timeout (`0.25s`) on `_log_prediction` + `log=False` on the pre-routing optimization-only predict calls in MariNav (`pages/4_MariNav_Router.py:498-510`). This unstuck the Calculate Route button.
3. **Feature drift fix**: added `live_queue_snapshot()` and swapped the two feature definitions so inference matches training. Real ML-accuracy fix, not cosmetic.
4. **Per-chokepoint "Show calculation" expander** + ETA-Δ-vs-baseline chip on the chokepoint status row + recent-predictions audit section (4b) on the ETA Quality page.
5. **In progress: plain-English pass** — described in the active plan file. Started but not finished. See task list below.

## Current task list

```
#20 [in_progress] Surface vessel + speed on route cards
#21 [pending]     Plain-English route card ML line + confidence tooltip
#22 [pending]     Rewrite 'Why this prediction?' expander
#23 [pending]     Rewrite 'Show calculation' expander labels
#24 [pending]     Rewrite the ETA Quality page
#25 [pending]     Vessel dropdown on Live Feature Inspector
#26 [pending]     Audience caption on deep-dive expander
#27 [pending]     Update tests, run suite, restart streamlit
```

Run `TaskList` to confirm before continuing. Tasks 1–19 are completed
and document the prior sessions.

### What's done inside task 20 (verify before moving on)

In `pages/4_MariNav_Router.py`:
- Route-alternatives subtitle block (~line 609-628): rewritten to say
  `Predicted for {vessel} at {speed} kn — pattern-finding model trained on …`.
  The badge `XGBoost q10/q50/q90` is gone from this subtitle. Audience-facing.
- Chokepoint card (~line 1198-1255): `n_str` was `, n=2,248` and `badge`
  was `XGBoost`/`heuristic`. Replaced with `source_str` (plain English:
  `learned from N past transits` or `fallback formula (no past transits
  for this vessel/chokepoint combo)`), and a new line below the predicted
  transit reads `Vessel assumed: {vessel} at {speed} kn`.

You can verify by re-reading those two ranges. If the strings I described
are present, mark task 20 complete and move to task 21.

## What's still pending (tasks 21-27 in order)

### Task 21 — Route card ML line + confidence chip tooltip
The card-rendering block at `pages/4_MariNav_Router.py:719-780` (the alt
cards in the "Route alternatives" grid) still uses `XGBoost`/`heuristic`
in `_badge`, and the confidence chip tooltip uses
`"model, n=200, live 60%"`. Apply the vocabulary table from the plan.
Suggested tooltip: `"Pattern-finding model · {n} past transits seen · {acc}% within ±15% on recent live predictions"`.

### Task 22 — Rewrite "Why this prediction?" expander
At `pages/4_MariNav_Router.py:1320-1394`. The existing "How to read this"
panel uses "SHAP values" / "expected value" / "baseline q50". Replace with
the plain-language copy in the plan: header `What pushed this ETA up or
down`. The worked example numbers stay; only the wording changes.

### Task 23 — Rewrite "Show calculation" expander labels
At `pages/4_MariNav_Router.py:1396-1467`. Two `pd.DataFrame` tables with
"Feature/Value" and "Field/Value" headers. Replace `p10 (min / h)` with
`Fastest likely (min / h)`, `p50` → `Most likely`, `p90` → `Slowest
likely`. `Branch` → `Source`. `n_train` → `Past transits the model has
seen`. Keep `chokepoint_id` etc. but with plain-English row labels
(see vocabulary table).

### Task 24 — Rewrite the ETA Quality page
`pages/5_ETA_Quality.py` end-to-end. Heavy text rewrite. The model
description in section 1 must drop `XGBoost quantile regression` /
`gradient boosting on decision trees` / `α=0.1/0.5/0.9` /
`one-hot encoding`. Section 3 KPI tiles (lines ~197-238): the help text
and metric labels still use `MAPE`, `p10–p90 coverage`, `MAE`. Section
4b table headers use `p10_min`/`p50_min`/`p90_min`/`actual_min`/`mmsi` —
rewrite per the vocabulary table. Section 5 table: same. Section 6 drift
banners: plain English.

### Task 25 — Vessel dropdown on Live Feature Inspector
`eta_quality.live_features_for_chokepoint()` at `eta_quality.py:401-432`
hardcodes `ship_type="container"` and `entry_sog_kn=12.0`. Change
signature to accept `ship_type: str = "container"` and
`entry_sog_kn: float = 12.0` kwargs (keep defaults to stay
backwards-compatible). On `pages/5_ETA_Quality.py:131-189`, add a
`st.selectbox` for the vessel that mirrors the router's selectbox.
Map vessel → bin using the same `_vessel_to_ship_type_bin` logic (move
the helper into a shared module OR just inline it on the page).

### Task 26 — Audience caption on deep-dive expander
One-line caption at the top of the `🤖 ML diagnostics (ETA predictor)`
expander (`pages/4_MariNav_Router.py:295`):
> Technical detail for the project advisor / developer. Everyday users can ignore this section.

### Task 27 — Tests + verify
1. Add an assertion in `tests/test_eta_quality.py::test_live_features_for_chokepoint_returns_required_keys` that the new kwargs override defaults. **Do not change the test count** — the plan promises 47 passed.
2. Run pytest:
   ```bash
   "/Users/alexanderovsyannikov/Downloads/CS PROJECT/venv/bin/pytest" tests/ -q
   ```
3. Jargon grep:
   ```bash
   grep -nE "XGBoost|q10|q50|q90|SHAP|pinball|MAE|MAPE|R²|heuristic|one-hot|quantile" pages/4_MariNav_Router.py pages/5_ETA_Quality.py
   ```
   Hits must all be inside the deep-dive expander block (lines 295-417 of MariNav) OR inside Python comments. Anywhere else = remaining jargon to scrub.
4. Restart streamlit (it's already running — kill first):
   ```bash
   pkill -f "streamlit run app.py"; sleep 2
   "/Users/alexanderovsyannikov/Downloads/CS PROJECT/venv/bin/streamlit" run app.py --server.headless true
   ```

## Critical files (read before editing)

| Path | What it does |
|---|---|
| `pages/4_MariNav_Router.py` | The big page. Route calculation + chokepoint cards + SHAP/Show-calculation expanders + ML diagnostics expander. 1700+ lines. |
| `pages/5_ETA_Quality.py` | The audit dashboard. 6 sections + 4b. |
| `eta_model.py` | XGBoost quantile regressor + heuristic fallback + `predict_transit_minutes` + `_log_prediction` + SHAP `explain_prediction`. |
| `eta_quality.py` | Matcher + metrics + confidence score + `live_features_for_chokepoint` + `recent_predictions`. |
| `ais_consumer.py` | AISStream WebSocket consumer + `live_queue_snapshot` (±5 min) + `transits_24h` (24h). WAL pragma in `_init_db`. |
| `eta_scheduler.py` | Background daemon for retrains; `retrain_now()` calls the matcher first. |
| `train_eta_model.py` | Offline trainer (CV + HP sweep + 80/20 + SHAP + calibration plot). Not in the active task scope. |
| `tests/conftest.py` | Has an autouse `_isolate_prediction_log` fixture that redirects `eta_model._DB_PATH` to a tmp file per test. Don't remove. |
| `CLAUDE.md` | Project conventions doc. The "ML quality tracking" paragraph was added in an earlier session. |

## Things to know before touching code

- **Vessel mapping** (`pages/4_MariNav_Router.py:67-75`): `_vessel_to_ship_type_bin(name)` maps the sidebar selection to `{tanker, bulker, container, other}`. The 5 sidebar options are `Panamax bulker`, `Suezmax tanker`, `VLCC tanker`, `ULCV container`, `MR product tanker`. Default index 0 = Panamax bulker.
- **Heuristic fallback formula** (`eta_model.py:642-655`): `p50 = base × (1 + 0.10 × (queue/10 − 1))`, `p10 = p50 × 0.75`, `p90 = p50 × 1.30`. Don't rename or change this. Plain-English the *labels*, not the math.
- **DB schema for `eta_predictions`**: defined twice for safety — in `ais_consumer._init_db()` and `eta_model._ensure_predictions_table()`. Keep them in sync if you ever change it.
- **The 245 MB `.ais_positions.db` file** is gitignored. The WAL sidecars (`.ais_positions.db-wal`, `-shm`) are normal and indicate WAL is active.
- **Streamlit caches**: `@st.cache_resource` for loading the joblib bundle; `@st.cache_data(ttl=120)` for `_eta_quality_metrics_cached`. After significant code changes, the existing streamlit process needs to be killed for `@st.cache_resource` to reload.
- **Git state right now**: branch `main` at `8bc00b2`. Working tree has uncommitted changes across `CLAUDE.md`, `ais_consumer.py`, `eta_model.py`, `eta_scheduler.py`, `pages/4_MariNav_Router.py`, `tests/conftest.py`, plus untracked `eta_quality.py`, `pages/5_ETA_Quality.py`, `tests/test_eta_quality.py`. The user has NOT asked for a commit. Do not commit unless they say so.

## How to start

1. Read the plan file: `/Users/alexanderovsyannikov/.claude/plans/hey-claude-check-the-floating-crab.md`.
2. Run `TaskList` to confirm the task statuses.
3. Verify task 20 is complete by reading the two ranges I described above.
4. Continue with task 21. Work tasks sequentially through 27.
5. Ask the user for confirmation before running `git commit`, force-push, killing processes the user owns, or anything otherwise destructive.

## Style reminders (from project memory and earlier feedback)

- The user prefers terse, concrete responses. No multi-paragraph summaries.
- Don't restate the plan back to them when invoking ExitPlanMode — that tool is the plan-approval signal.
- Use task tracking. Mark in_progress before starting, completed when done — don't batch.
- Test against the real shipping-domain values; never make up vessel names, port names, or chokepoint coordinates.
- If a streamlit page suddenly stops working, suspect SQLite lock contention or feature-distribution drift before suspecting a model issue. We've already been bitten by both.

Good luck.
