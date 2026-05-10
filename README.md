# CS-project
CS project HSG (War Room)

## ML feature — Chokepoint ETA Predictor

The MariNav Router page surfaces an XGBoost-based prediction of how
many minutes a vessel will take to clear each chokepoint on a route
(Suez, Hormuz, Singapore Strait, Panama, Bosphorus, Bab el-Mandeb,
Malacca, Taiwan, English Channel). Three quantile regressors give a
p10 / p50 / p90 prediction interval, with SHAP-based per-prediction
explanations.

### Train the model

```bash
pip install -r requirements.txt
python train_eta_model.py --seed                # cold-start training with bundled synthetic seed
python train_eta_model.py --seed --no-cv        # fast iteration (skips CV + hyperparam sweep)
python train_eta_model.py                       # real AIS data only (auto when ≥200 rows exist)
```

The trainer runs:

1. **5-fold time-series cross-validation** over `entry_ts`-sorted rows
2. **27-cell hyperparameter sweep** (max_depth × n_estimators × learning_rate)
3. **Final training** with the best config (q10 / q50 / q90 quantile boosters)

It prints:

- Per-fold MAE / R² + mean ± std
- Top-5 hyperparameter configurations
- Final hold-out MAE / R² / per-chokepoint MAE

…and writes to `models/`:

- `eta_xgb.joblib` — three quantile boosters + encoder + meta
- `eta_meta.json` — n_train/n_test, MAE/R², CV folds, best HP, top-5 sweep
- `eta_feature_importance.png` — top-15 feature gains
- `eta_calibration.png` — predicted vs actual scatter on the hold-out
- `eta_shap_values.npy` + `eta_shap_X_test.npy` + `eta_shap_feature_names.json`
  — SHAP backing data for the dashboard's "Why this prediction?" UI

### Run the test suite

```bash
pytest tests/ -v                # 31 tests covering extraction, encoding, inference fallbacks, trainer
```

### Where it shows up

Run the dashboard, navigate to **MariNav Router**, calculate a route:

- Each route alternative card shows the ML ETA, a CSS interval bar
  for the p10–p90 band, and (when toggled) a side-by-side comparison
  with the heuristic baseline.
- The Chokepoints-on-Route panel shows per-chokepoint p50 with the
  p10–p90 spread and a `Why this prediction?` expander that lists
  the top SHAP contributions in minutes.
- The sidebar `🤖 ML diagnostics (ETA predictor)` expander shows
  CV metrics, best hyperparameters, feature importances, calibration
  plot, the hyperparameter-sweep top-5 table, per-chokepoint MAE,
  and a `Retrain now` button.

If the artifact is missing or SHAP isn't installed, both surfaces
gracefully fall back: predictions go through a calibrated per-chokepoint
heuristic (badge reads `(heuristic)`) and the SHAP expander shows a
"SHAP unavailable" caption.

### Auto-retrain scheduler

`eta_scheduler.start_eta_scheduler()` is called from `app.py` and runs
a daemon thread that wakes daily, retraining the model when ≥200 real
AIS rows have accumulated AND ≥24h have elapsed since the last train.
The synthetic seed phases out automatically once real_rows ≥ 300.
