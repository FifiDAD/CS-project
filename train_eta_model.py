"""Train the Chokepoint ETA Predictor (XGBoost quantile regression).

Reads labeled transits from the live AIS sightings table (`.ais_positions.db`)
and/or the bundled synthetic seed CSV, runs 5-fold time-series cross-
validation + hyperparameter sweep, trains three quantile XGBoost regressors
(p10, p50, p90) on the best configuration, and persists the bundle to
models/eta_xgb.joblib alongside SHAP backing data and a calibration plot.

Usage:
    python train_eta_model.py                  # real AIS data; refuses if <200 rows
    python train_eta_model.py --seed           # add bundled synthetic rows
    python train_eta_model.py --no-cv          # skip CV+hyperparam sweep (fast iteration)
    python train_eta_model.py --db custom.db   # alternate AIS DB path
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from eta_model import (
    MODEL_VERSION,
    build_feature_matrix,
    extract_transits,
)

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / ".ais_positions.db"
SEED_CSV = HERE / "data" / "eta_seed_transits.csv"
MODELS_DIR = HERE / "models"
ARTIFACT_PATH = MODELS_DIR / "eta_xgb.joblib"
META_PATH = MODELS_DIR / "eta_meta.json"
IMPORTANCE_PNG = MODELS_DIR / "eta_feature_importance.png"
CALIBRATION_PNG = MODELS_DIR / "eta_calibration.png"
SHAP_VALUES_NPY = MODELS_DIR / "eta_shap_values.npy"
SHAP_X_TEST_NPY = MODELS_DIR / "eta_shap_X_test.npy"
SHAP_FEATURE_NAMES_JSON = MODELS_DIR / "eta_shap_feature_names.json"

N_MIN_TOTAL = 200
N_MIN_PER_CP = 25
# Synthetic data is a cold-start aid only; once real AIS volume is adequate
# the model should learn from live observations alone.
SEED_PHASEOUT_THRESHOLD = N_MIN_TOTAL  # drop synthetic the moment real data clears the floor

# Sample-weight schedule keyed off ship_type bin (see eta_model.ship_type_bin).
# Trade-route core (cargo + tanker) trains at full weight; passenger and
# unknown vessels contribute less; synthetic seed rows contribute least
# and only matter at cold start, before SEED_PHASEOUT_THRESHOLD is met.
WEIGHT_BY_BIN = {
    "container": 1.0,
    "tanker":    1.0,
    "bulker":    1.0,   # legacy seed bin; treat as cargo-equivalent
    "other":     0.7,
    "unknown":   0.5,
}
SYNTHETIC_WEIGHT = 0.3

# Hyperparam grid for the sweep — 3³ = 27 combinations.
HP_GRID = {
    "max_depth":     [3, 5, 7],
    "n_estimators":  [200, 300, 500],
    "learning_rate": [0.05, 0.08, 0.12],
}


@dataclass
class FoldResult:
    fold: int
    mae: float
    r2: float
    n_train: int
    n_test: int


# ---------------------------------------------------------------------------
# Data loading / validation
# ---------------------------------------------------------------------------

def _load_data(db_path: Path, use_seed: bool) -> pd.DataFrame:
    # Extract only commercial AIS transits so leisure/fishing/military tracks
    # do not distort chokepoint ETA estimates for shipping routes.
    real = extract_transits(db_path, commercial_only=True)
    real_n = len(real)
    print(f"Real transits extracted from {db_path.name}: {real_n} (commercial only)")
    if real_n > 0:
        per_cp = real["chokepoint_id"].value_counts().to_dict()
        breakdown = " · ".join(f"{cp}={n}" for cp, n in sorted(per_cp.items(), key=lambda kv: -kv[1]))
        print(f"  per-chokepoint: {breakdown}")
        per_bin = real["ship_type"].value_counts().to_dict()
        bin_breakdown = " · ".join(
            f"{b}={per_bin.get(b, 0)}" for b in ["container", "tanker", "other", "unknown"]
        )
        print(f"  vessel mix: {bin_breakdown}")
        # Diagnostic: how many rows the SQL filter dropped this run.
        try:
            unfiltered_n = len(extract_transits(db_path, commercial_only=False))
            excluded_n = max(0, unfiltered_n - real_n)
            if excluded_n:
                print(f"  excluded: {excluded_n} fishing/pleasure/military transits skipped")
        except Exception:  # noqa: BLE001  diagnostic only
            pass

    if not use_seed:
        return real

    # Determine which chokepoints still need synthetic top-up (below per-cp floor).
    if real_n == 0:
        sparse_cps: list[str] = []  # everything is sparse — load full seed below
    else:
        per_cp = real["chokepoint_id"].value_counts().to_dict()
        sparse_cps = [cp for cp, n in per_cp.items() if n < N_MIN_PER_CP]
        # Also flag chokepoints that have *zero* real rows so we top those up too.
        all_cps_in_seed: set[str] = set()
        if SEED_CSV.exists():
            try:
                all_cps_in_seed = set(pd.read_csv(SEED_CSV, usecols=["chokepoint_id"])["chokepoint_id"].unique())
            except Exception:  # noqa: BLE001
                all_cps_in_seed = set()
        sparse_cps += [cp for cp in all_cps_in_seed if cp not in per_cp]

    if real_n >= SEED_PHASEOUT_THRESHOLD and not sparse_cps:
        print(
            f"  Real data sufficient ({real_n} ≥ {SEED_PHASEOUT_THRESHOLD}) and every "
            "chokepoint clears the per-CP floor — training on real AIS only, "
            "synthetic seed dropped."
        )
        return real

    if not SEED_CSV.exists():
        print(f"ERROR: seed CSV missing — run scripts/seed_eta.py first ({SEED_CSV})")
        sys.exit(1)
    seed = pd.read_csv(SEED_CSV)
    seed["_synthetic"] = True
    if real_n == 0:
        print(f"  cold start — using full seed: {len(seed)} synthetic rows")
        return seed
    # Targeted top-up: only the sparse chokepoints get synthetic rows. The
    # already-covered chokepoints train on real data alone, so synthetic
    # never dominates those that already have AIS coverage.
    seed_subset = seed[seed["chokepoint_id"].isin(sparse_cps)]
    df = pd.concat([real, seed_subset], ignore_index=True)
    print(
        f"  topping up sparse chokepoints {sorted(set(sparse_cps))} with "
        f"{len(seed_subset)} synthetic rows (real-only chokepoints train without seed)"
    )
    return df


def _check_thresholds(df: pd.DataFrame) -> None:
    # Guard against training a model that would look valid but be too sparse
    # for reliable chokepoint-level predictions.
    if len(df) < N_MIN_TOTAL:
        print(
            f"\nERROR: need ≥{N_MIN_TOTAL} transits to train, have {len(df)}.\n"
            f"  Run the dashboard with the AIS consumer for 24-48h to accumulate real\n"
            f"  data, OR re-run with --seed to use the bundled synthetic dataset."
        )
        sys.exit(1)
    counts = df["chokepoint_id"].value_counts()
    weak = counts[counts < N_MIN_PER_CP]
    if len(weak):
        print(f"\nERROR: chokepoints below {N_MIN_PER_CP}-row floor: {weak.to_dict()}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Modelling helpers
# ---------------------------------------------------------------------------

def _make_quantile(alpha: float, max_depth: int, n_estimators: int, learning_rate: float):
    # XGBoost's quantile objective gives direct p10/p50/p90 ETA estimates
    # instead of fitting a single mean prediction and guessing uncertainty later.
    from xgboost import XGBRegressor
    return XGBRegressor(
        objective="reg:quantileerror",
        quantile_alpha=alpha,
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=0.85,
        colsample_bytree=0.85,
        tree_method="hist",
        random_state=42,
        verbosity=0,
    )


def _train_quantile(X_train, y_train, alpha: float, hp: dict, sample_weight=None):
    # Sample weights are optional so the same helper works for both weighted
    # production training and lightweight experiments.
    m = _make_quantile(
        alpha=alpha,
        max_depth=hp["max_depth"],
        n_estimators=hp["n_estimators"],
        learning_rate=hp["learning_rate"],
    )
    if sample_weight is not None:
        m.fit(X_train, y_train, sample_weight=sample_weight)
    else:
        m.fit(X_train, y_train)
    return m


def _build_sample_weights(df: pd.DataFrame) -> np.ndarray:
    """Per-row training weight based on ship_type bin + synthetic flag.

    Aligns to ``df`` row order; caller is responsible for preserving the
    ordering between weights and the feature matrix.
    """
    bin_w = df["ship_type"].map(WEIGHT_BY_BIN).fillna(WEIGHT_BY_BIN["unknown"])
    if "_synthetic" in df.columns:
        synth_mask = df["_synthetic"].fillna(False).astype(bool)
        bin_w = bin_w.where(~synth_mask, SYNTHETIC_WEIGHT)
    return bin_w.to_numpy(dtype=float)


def _mae(pred, y) -> float:
    # MAE is easy for operators to read because the target is minutes.
    return float(np.mean(np.abs(pred - y)))


def _r2(pred, y) -> float:
    # R2 complements MAE by showing whether the model beats a flat mean baseline.
    ss_res = float(np.sum((pred - y) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot else float("nan")


def _per_chokepoint_mae(df_test: pd.DataFrame, preds: np.ndarray) -> dict[str, float]:
    out: dict[str, float] = {}
    df = df_test.copy().reset_index(drop=True)
    df["pred"] = preds
    for cp, grp in df.groupby("chokepoint_id"):
        mae = float(np.abs(grp["pred"] - grp["transit_minutes"]).mean())
        out[str(cp)] = round(mae, 1)
    return out


# ---------------------------------------------------------------------------
# Cross-validation + hyperparameter sweep
# ---------------------------------------------------------------------------

def _cv_score_q50(X_sorted, y_sorted, hp: dict, n_splits: int,
                  sample_weight=None) -> tuple[float, list[FoldResult]]:
    """Return (mean MAE across folds, per-fold results) for the q50 model.

    Caps n_estimators at 300 during the sweep to keep runtime bounded; the
    final retrain uses the user's chosen value.
    """
    from sklearn.model_selection import TimeSeriesSplit

    capped_hp = {**hp, "n_estimators": min(hp["n_estimators"], 300)}
    splitter = TimeSeriesSplit(n_splits=n_splits)
    folds: list[FoldResult] = []
    for k, (tr, te) in enumerate(splitter.split(X_sorted), start=1):
        X_tr, X_te = X_sorted[tr], X_sorted[te]
        y_tr, y_te = y_sorted[tr], y_sorted[te]
        w_tr = sample_weight[tr] if sample_weight is not None else None
        m = _train_quantile(X_tr, y_tr, alpha=0.5, hp=capped_hp,
                            sample_weight=w_tr)
        p = m.predict(X_te)
        folds.append(FoldResult(
            fold=k, mae=_mae(p, y_te), r2=_r2(p, y_te),
            n_train=len(tr), n_test=len(te),
        ))
    return float(np.mean([f.mae for f in folds])), folds


def _hyperparameter_sweep(
    X_sorted, y_sorted, n_splits: int, sample_weight=None,
) -> tuple[dict, list[dict], list[FoldResult]]:
    """Grid-search over HP_GRID. Returns (best_hp, top_5 list of dicts, best_folds)."""
    grid = list(itertools.product(*HP_GRID.values()))
    keys = list(HP_GRID.keys())
    print(f"\nHyperparameter sweep: {len(grid)} configurations × {n_splits} folds")
    print(f"  Grid: {dict(HP_GRID)}")
    results: list[dict] = []
    for i, combo in enumerate(grid):
        hp = dict(zip(keys, combo))
        mean_mae, _ = _cv_score_q50(X_sorted, y_sorted, hp, n_splits=n_splits,
                                    sample_weight=sample_weight)
        results.append({**hp, "cv_mae": round(mean_mae, 2)})
        if (i + 1) % 5 == 0 or i == len(grid) - 1:
            print(f"  [{i+1:>2}/{len(grid)}] {hp} → CV MAE {mean_mae:.1f}")
    results.sort(key=lambda r: r["cv_mae"])
    print("\nTop-5 configurations (by mean CV MAE):")
    print(f"  {'rank':>4}  {'max_depth':>10}  {'n_est':>6}  {'lr':>5}  {'CV MAE':>8}")
    for rank, r in enumerate(results[:5], start=1):
        print(
            f"  {rank:>4}  {r['max_depth']:>10}  {r['n_estimators']:>6}  "
            f"{r['learning_rate']:>5}  {r['cv_mae']:>7.1f} m"
        )
    best = results[0]
    best_hp = {k: best[k] for k in keys}
    # The sweep capped n_estimators at 300; re-run CV with the chosen full
    # n_estimators so the reported folds reflect the actual final model.
    final_mean, final_folds = _cv_score_q50(X_sorted, y_sorted, best_hp,
                                            n_splits=n_splits,
                                            sample_weight=sample_weight)
    print(
        f"\nBest config (final, n_estimators={best_hp['n_estimators']}): "
        f"CV MAE {final_mean:.1f} min ± {np.std([f.mae for f in final_folds]):.1f}"
    )
    return best_hp, results[:5], final_folds


# ---------------------------------------------------------------------------
# Plots & SHAP
# ---------------------------------------------------------------------------

def _save_feature_importance(model, feature_names: list[str], path: Path) -> None:
    # Persist a static PNG so the dashboard can show explainability without
    # importing plotting libraries at page-render time.
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib unavailable — skipping feature importance plot)")
        return
    importances = model.feature_importances_
    order = np.argsort(importances)[::-1][:15]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(
        [feature_names[i] for i in order][::-1],
        [importances[i] for i in order][::-1],
        color="#3b82f6",
    )
    ax.set_xlabel("Gain importance")
    ax.set_title("ETA Predictor — top features (median quantile)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _save_calibration_plot(y_true, y_pred, path: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib unavailable — skipping calibration plot)")
        return
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(y_true, y_pred, alpha=0.5, s=18, color="#3b82f6")
    lo = float(min(y_true.min(), y_pred.min()))
    hi = float(max(y_true.max(), y_pred.max()))
    ax.plot([lo, hi], [lo, hi], color="#ef4444", lw=1.5, ls="--", label="y = x (perfect)")
    ax.set_xlabel("Actual transit (minutes)")
    ax.set_ylabel("Predicted transit (minutes)")
    ax.set_title("ETA Predictor — calibration on hold-out (q50)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _save_shap_values(model, X_test, feature_names: list[str]) -> bool:
    """Compute and persist SHAP TreeExplainer values for the q50 model.

    Returns True on success, False if shap is unavailable. Failure does
    not abort training — the dashboard's SHAP UI degrades gracefully.
    """
    try:
        import shap  # type: ignore[import-untyped]
    except ImportError:
        print("  (shap unavailable — skipping SHAP backend; dashboard will hide the 'Why?' expander)")
        return False
    try:
        explainer = shap.TreeExplainer(model)
        # Sample to keep file size reasonable for large training sets.
        n = min(len(X_test), 1000)
        X_sample = X_test[:n]
        shap_vals = explainer.shap_values(X_sample)
        np.save(SHAP_VALUES_NPY, shap_vals)
        np.save(SHAP_X_TEST_NPY, X_sample)
        SHAP_FEATURE_NAMES_JSON.write_text(json.dumps(feature_names))
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  (shap computation failed: {e}; skipping)")
        return False


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _fmt_path(p: Path) -> str:
    # Prefer repo-relative paths in CLI output so logs are stable across machines.
    try:
        return str(p.relative_to(HERE))
    except ValueError:
        return str(p)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the chokepoint ETA predictor.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to .ais_positions.db")
    parser.add_argument("--seed", action="store_true", help="Augment with bundled synthetic seed")
    parser.add_argument(
        "--no-cv", action="store_true",
        help="Skip CV + hyperparam sweep (use default config). Faster for iteration.",
    )
    parser.add_argument("--cv-splits", type=int, default=5, help="Number of time-series CV folds")
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db)

    df = _load_data(db_path, use_seed=args.seed)
    if df.empty:
        print("ERROR: no training rows found. Use --seed for cold start.")
        sys.exit(1)
    _check_thresholds(df)

    # Sort once; everything below operates on entry_ts-sorted rows.
    df_sorted = df.sort_values("entry_ts").reset_index(drop=True)
    X_full, y_full, encoder, feat_names = build_feature_matrix(df_sorted)
    n = len(y_full)

    # Per-row training weights — keep aligned with df_sorted.
    sample_weight_full = _build_sample_weights(df_sorted)
    weight_summary = {
        "schedule": {**WEIGHT_BY_BIN, "_synthetic": SYNTHETIC_WEIGHT},
        "vessel_mix": (
            df_sorted["ship_type"].value_counts().to_dict()
            if "ship_type" in df_sorted.columns else {}
        ),
        "synthetic_rows": int(df_sorted.get("_synthetic", pd.Series(dtype=bool)).fillna(False).sum()),
        "real_rows": int((~df_sorted.get("_synthetic", pd.Series([False] * n)).fillna(False)).sum()),
    }
    print(
        f"Sample-weight schedule: "
        f"container/tanker=1.0 · other=0.7 · unknown=0.5 · synthetic=0.3"
    )

    # ── CV + hyperparam sweep ───────────────────────────────────────────────
    cv_folds: list[FoldResult] = []
    cv_summary: dict | None = None
    hp_search: list[dict] = []
    if args.no_cv or n // args.cv_splits < 50:
        if not args.no_cv:
            print(
                f"Note: only {n} rows / {args.cv_splits} folds < 50 per fold — "
                "skipping CV. Use --cv-splits=3 to force."
            )
        best_hp = {"max_depth": 5, "n_estimators": 300, "learning_rate": 0.08}
        print(f"Using default config: {best_hp}")
    else:
        best_hp, hp_search, cv_folds = _hyperparameter_sweep(
            X_full, y_full, n_splits=args.cv_splits,
            sample_weight=sample_weight_full,
        )
        cv_summary = {
            "n_splits": args.cv_splits,
            "mean_mae": round(float(np.mean([f.mae for f in cv_folds])), 2),
            "std_mae":  round(float(np.std([f.mae for f in cv_folds])),  2),
            "mean_r2":  round(float(np.mean([f.r2  for f in cv_folds])), 4),
            "folds": [
                {"fold": f.fold, "mae": round(f.mae, 2), "r2": round(f.r2, 4),
                 "n_train": f.n_train, "n_test": f.n_test}
                for f in cv_folds
            ],
        }
        print("\nPer-fold metrics with best HP:")
        print(f"  {'fold':>4}  {'n_train':>8}  {'n_test':>7}  {'MAE':>7}  {'R²':>6}")
        for f in cv_folds:
            print(f"  {f.fold:>4}  {f.n_train:>8}  {f.n_test:>7}  {f.mae:>6.1f}m  {f.r2:>6.3f}")
        print(
            f"  {'mean':>4}  {'':>8}  {'':>7}  "
            f"{cv_summary['mean_mae']:>6.1f}m  {cv_summary['mean_r2']:>6.3f}  "
            f"(± {cv_summary['std_mae']:.1f}m)"
        )

    # ── Final 80/20 split for hold-out metrics + calibration plot ───────────
    split_idx = int(n * 0.8)
    X_train, X_test = X_full[:split_idx], X_full[split_idx:]
    y_train, y_test = y_full[:split_idx], y_full[split_idx:]
    w_train = sample_weight_full[:split_idx]
    test_df = df_sorted.iloc[split_idx:].reset_index(drop=True)

    print(
        f"\nFinal training (80/20 hold-out): "
        f"train={len(y_train)} rows, test={len(y_test)} rows"
    )
    print("Training quantile regressors (q10 / q50 / q90)...")
    q10 = _train_quantile(X_train, y_train, alpha=0.1, hp=best_hp, sample_weight=w_train)
    q50 = _train_quantile(X_train, y_train, alpha=0.5, hp=best_hp, sample_weight=w_train)
    q90 = _train_quantile(X_train, y_train, alpha=0.9, hp=best_hp, sample_weight=w_train)

    p50_pred = q50.predict(X_test)
    final_mae = _mae(p50_pred, y_test)
    final_r2  = _r2(p50_pred, y_test)
    per_cp = _per_chokepoint_mae(test_df, p50_pred)

    print(f"\nHold-out median model — MAE: {final_mae:.1f} min  R²: {final_r2:.3f}  (n_test={len(y_test)})")
    print("Per-chokepoint MAE on hold-out:")
    for cp, m in sorted(per_cp.items(), key=lambda kv: -kv[1]):
        print(f"  {cp:22s}  {m:>6.1f} min")

    if "_synthetic" in df.columns:
        synth_n = int(df_sorted["_synthetic"].fillna(False).sum())
        real_n = len(df_sorted) - synth_n
        print(f"\nTraining mix — real: {real_n}, synthetic: {synth_n}")

    # ── Persist ─────────────────────────────────────────────────────────────
    bundle = {
        "q10": q10,
        "q50": q50,
        "q90": q90,
        "encoder": encoder,
        "meta": {
            "model_version": MODEL_VERSION,
            "trained_at": time.time(),
            "n_train": int(len(y_train)),
            "n_test": int(len(y_test)),
            "mae_minutes": round(final_mae, 2),
            "r2": round(final_r2, 4),
            "per_chokepoint_mae": per_cp,
            "feature_names": feat_names,
            "real_rows": int((~df_sorted["_synthetic"].fillna(False)).sum())
                         if "_synthetic" in df_sorted.columns else int(len(df_sorted)),
            "synthetic_rows": int(df_sorted["_synthetic"].fillna(False).sum())
                              if "_synthetic" in df_sorted.columns else 0,
            "best_hp": best_hp,
            "hp_search_top5": hp_search,
            "cv_summary": cv_summary,
            "vessel_mix": weight_summary["vessel_mix"],
            "sample_weight_schedule": weight_summary["schedule"],
            "used_synthetic": weight_summary["synthetic_rows"] > 0,
            "commercial_only": True,
        },
    }

    import joblib
    joblib.dump(bundle, ARTIFACT_PATH)
    META_PATH.write_text(json.dumps(bundle["meta"], indent=2, default=str))
    _save_feature_importance(q50, feat_names, IMPORTANCE_PNG)
    _save_calibration_plot(y_test, p50_pred, CALIBRATION_PNG)
    shap_ok = _save_shap_values(q50, X_test, feat_names)

    size_kb = ARTIFACT_PATH.stat().st_size // 1024
    print(f"\nSaved {_fmt_path(ARTIFACT_PATH)} ({size_kb} KB)")
    print(f"Saved {_fmt_path(META_PATH)}")
    if IMPORTANCE_PNG.exists():
        print(f"Saved {_fmt_path(IMPORTANCE_PNG)}")
    if CALIBRATION_PNG.exists():
        print(f"Saved {_fmt_path(CALIBRATION_PNG)}")
    if shap_ok:
        print(f"Saved {_fmt_path(SHAP_VALUES_NPY)} + X_test + feature_names")


if __name__ == "__main__":
    main()
