"""Chokepoint ETA Predictor — ML inference + training-data extraction.

The model predicts how many minutes a vessel will take to clear a maritime
chokepoint (Suez, Hormuz, Singapore Strait, etc.) given current queue
depth, ship type, and time-of-day. Three quantile XGBoost regressors
(p10 / p50 / p90) provide a prediction interval rather than a point
estimate.

Public surface:
    extract_transits(db_path)    → DataFrame of labeled transits from AIS history
    build_feature_matrix(df)     → (X, y, encoder, feature_names) for training
    predict_transit_minutes(cp, features)  → {p10, p50, p90, n_train, confidence}

The inference path always returns a dict — when the artifact is missing
or the chokepoint was unseen at training time, it falls back to a
per-chokepoint heuristic so the UI never blanks. xgboost / joblib are
lazy-imported inside load_artifact() so app_simple.py and other lean
import paths remain functional in environments without ML libs.
"""

from __future__ import annotations

import functools
import math
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_ARTIFACT_PATH = _HERE / "models" / "eta_xgb.joblib"

# Per-chokepoint bounding boxes — kept in sync with ais_consumer.CHOKEPOINT_BBOXES.
# Re-declared here (rather than imported) so eta_model has no runtime
# dependency on the AIS consumer; the trainer imports both, but inference
# only needs this dict.
CHOKEPOINT_BBOXES: dict[str, list[float]] = {
    "Suez Canal":        [27.0,  31.0,  33.0,  35.0],
    "Bab el-Mandeb":     [11.0,  41.0,  17.0,  45.0],
    "Strait of Hormuz":  [24.0,  54.0,  28.0,  58.0],
    "Bosphorus":         [40.5,  28.0,  41.7,  30.0],
    "Strait of Malacca": [ 0.5, 100.0,   5.5, 103.5],
    "Singapore Strait":  [ 0.8, 103.3,   1.7, 104.5],
    "Taiwan Strait":     [22.0, 117.5,  26.5, 121.5],
    "Panama Canal":      [ 7.5, -80.5,  10.5, -78.5],
    "English Channel":   [49.5,  -2.5,  51.5,   2.0],
}

# Per-chokepoint floor on entry→exit straight-line distance. Vessels that
# dip into the bbox and exit the same side without crossing aren't real
# transits — typical for anchored vessels near coastal terminals.
# Loosened ~30% from initial values: bbox geographic discipline + speed
# filter already exclude anchored vessels, the floor was belt-and-braces.
MIN_TRANSIT_DIST_KM: dict[str, float] = {
    "Suez Canal":        100.0,
    "Bab el-Mandeb":      55.0,
    "Strait of Hormuz":   70.0,
    "Bosphorus":          18.0,
    "Strait of Malacca":  70.0,
    "Singapore Strait":   35.0,
    "Taiwan Strait":     100.0,
    "Panama Canal":       30.0,
    "English Channel":    55.0,
}

# bbox diagonal (km) — feature value used at training and inference time.
BBOX_DIAGONAL_KM: dict[str, float] = {
    "Suez Canal":        700.0,
    "Bab el-Mandeb":     650.0,
    "Strait of Hormuz":  500.0,
    "Bosphorus":         180.0,
    "Strait of Malacca": 650.0,
    "Singapore Strait":  150.0,
    "Taiwan Strait":     550.0,
    "Panama Canal":      400.0,
    "English Channel":   400.0,
}

# Heuristic fallback (mean transit minutes at moderate queue depth).
# Used when the artifact is missing or the chokepoint wasn't seen during
# training. Calibrated to public references — same numbers seed_eta.py uses.
HEURISTIC_MEAN_MIN: dict[str, float] = {
    "Suez Canal":        840.0,
    "Panama Canal":      540.0,
    "Strait of Hormuz":  240.0,
    "Bab el-Mandeb":     180.0,
    "Strait of Malacca": 480.0,
    "Singapore Strait":  480.0,
    "Bosphorus":         135.0,
    "Taiwan Strait":     660.0,
    "English Channel":   420.0,
}

# Splits AIS Type-5 ship_type integer codes (0–99) into broad categories.
# Reference: ITU-R M.1371-5 Annex 8 Table 53.
def ship_type_bin(code: int | float | None) -> str:
    if code is None or (isinstance(code, float) and math.isnan(code)):
        return "unknown"
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "unknown"
    if 70 <= c <= 79:
        return "container"  # Cargo
    if 80 <= c <= 89:
        return "tanker"
    if 30 <= c <= 39 or 60 <= c <= 69:
        return "other"  # Fishing / passenger
    return "other"


SHIP_TYPE_BINS = ["tanker", "bulker", "container", "other", "unknown"]

# AIS Type-5 codes the model should ignore for trade-route ETA learning.
# Reference: ITU-R M.1371-5 Annex 8 Table 53.
EXCLUDED_SHIP_TYPES: tuple[int, ...] = (
    30,  # Fishing
    33,  # Dredging / underwater ops
    34,  # Diving ops
    35,  # Military ops
    36,  # Sailing
    37,  # Pleasure craft
)

FEATURE_NAMES = [
    "chokepoint_id",
    "ship_type",
    "entry_sog_kn",
    "queue_depth",
    "hour_of_day",
    "day_of_week",
    "month",
    "recent_throughput_24h",
    "bbox_diagonal_km",
]
NUMERIC_FEATURES = [
    "entry_sog_kn", "queue_depth", "hour_of_day", "day_of_week",
    "month", "recent_throughput_24h", "bbox_diagonal_km",
]
CATEGORICAL_FEATURES = ["chokepoint_id", "ship_type"]

MODEL_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Training-data extraction from the live AIS sightings table
# ---------------------------------------------------------------------------

# Tuning knobs for the transit detector.
GAP_MINUTES = 60          # Split into separate transits if in-bbox sightings >60 min apart
MIN_ENTRY_SOG = 0.5       # Entry SoG floor (kn). Lowered from 1.0 to keep more real transits;
                          # anchored vessels still cluster near 0 and are dropped.
MIN_MEDIAN_SPEED = 0.5    # Median speed across transit must exceed this
MIN_DURATION_MIN = 5.0
MAX_DURATION_MIN = 60 * 72  # 72h hard cap
QUEUE_WINDOW_SEC = 300      # ±5 min around entry to compute queue_depth


def extract_transits(db_path: str | Path, commercial_only: bool = True) -> pd.DataFrame:
    """Walk the sightings table and return one row per completed transit.

    Each row carries the feature vector at entry time plus the observed
    transit duration. Drops anchored vessels, in-progress transits, and
    bbox dips that don't cross the chokepoint corridor.

    When ``commercial_only`` is True (default), AIS ship_type codes in
    ``EXCLUDED_SHIP_TYPES`` (fishing, sailing, pleasure, military, etc.)
    are filtered out at SQL level so the model trains on trade-route
    traffic. NULL ship_type rows are kept — they're often commercial
    vessels whose Type-5 ShipStaticData hasn't arrived yet — and get
    downweighted at training time.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return pd.DataFrame(columns=FEATURE_NAMES + ["transit_minutes", "entry_ts", "_synthetic"])

    with sqlite3.connect(db_path) as con:
        # Tolerate older DBs that pre-date the sog_kn / ship_type columns.
        cols = {r[1] for r in con.execute("PRAGMA table_info(sightings)")}
        select_cols = ["mmsi", "lat", "lon"]
        select_cols.append("sog_kn" if "sog_kn" in cols else "NULL AS sog_kn")
        select_cols.append("ship_type" if "ship_type" in cols else "NULL AS ship_type")
        select_cols.append("ts")
        where_clause = ""
        if commercial_only and "ship_type" in cols:
            excluded_csv = ",".join(str(c) for c in EXCLUDED_SHIP_TYPES)
            where_clause = (
                f" WHERE ship_type IS NULL OR ship_type NOT IN ({excluded_csv})"
            )
        sightings = pd.read_sql_query(
            f"SELECT {', '.join(select_cols)} FROM sightings"
            f"{where_clause} ORDER BY mmsi, ts",
            con,
        )

    if sightings.empty:
        return pd.DataFrame(columns=FEATURE_NAMES + ["transit_minutes", "entry_ts", "_synthetic"])

    rows: list[dict] = []
    for cp, bbox in CHOKEPOINT_BBOXES.items():
        rows.extend(_transits_for_chokepoint(sightings, cp, bbox))

    if not rows:
        return pd.DataFrame(columns=FEATURE_NAMES + ["transit_minutes", "entry_ts", "_synthetic"])

    df = pd.DataFrame(rows)
    df["_synthetic"] = False
    return df


def _derive_speed_kn(grp: pd.DataFrame) -> np.ndarray:
    """Compute instantaneous speed (kn) for each row from haversine to the next sighting.

    The last row in a group has no successor — it's filled with the previous
    row's derived speed (or NaN if the group has only one row). Used as a
    fallback when sog_kn from AIS is NULL (legacy sightings predate the
    sog_kn column being persisted).
    """
    if len(grp) < 2:
        return np.array([np.nan] * len(grp))
    lat = grp["lat"].to_numpy()
    lon = grp["lon"].to_numpy()
    ts  = grp["ts"].to_numpy()
    speeds = np.full(len(grp), np.nan, dtype=float)
    for i in range(len(grp) - 1):
        dt_h = (ts[i+1] - ts[i]) / 3600.0
        if dt_h <= 0:
            continue
        d_km = _haversine_km(lat[i], lon[i], lat[i+1], lon[i+1])
        # 1 km / 1.852 = nautical miles; divide by hours = knots
        speeds[i] = (d_km / 1.852) / dt_h
    speeds[-1] = speeds[-2] if len(grp) > 1 and not np.isnan(speeds[-2]) else np.nan
    return speeds


def _transits_for_chokepoint(sightings: pd.DataFrame, cp: str, bbox: list[float]) -> list[dict]:
    """Detect entry/exit edges per MMSI inside one chokepoint bbox."""
    inside = (
        (sightings["lat"] >= bbox[0]) & (sightings["lat"] <= bbox[2])
        & (sightings["lon"] >= bbox[1]) & (sightings["lon"] <= bbox[3])
    )
    cp_sightings = sightings[inside].copy()
    if cp_sightings.empty:
        return []

    out: list[dict] = []
    min_dist = MIN_TRANSIT_DIST_KM.get(cp, 50.0)
    diag = BBOX_DIAGONAL_KM.get(cp, 300.0)

    for mmsi, grp in cp_sightings.groupby("mmsi", sort=False):
        grp = grp.sort_values("ts").reset_index(drop=True)
        # Fill missing sog_kn from haversine/Δt — most legacy rows have NULL.
        derived = _derive_speed_kn(grp)
        sog_eff = grp["sog_kn"].astype(float).to_numpy().copy()
        nan_mask = np.isnan(sog_eff)
        sog_eff[nan_mask] = derived[nan_mask]
        # Cap unrealistic derived speeds (AIS gaps over open ocean can produce
        # spuriously high "speeds" if a vessel teleports across a gap).
        sog_eff = np.clip(sog_eff, 0.0, 35.0)
        grp = grp.assign(sog_eff=sog_eff)

        ts = grp["ts"].to_numpy()
        # Split into runs of consecutive sightings <= GAP_MINUTES apart.
        gaps = np.diff(ts) > GAP_MINUTES * 60.0
        run_ids = np.concatenate([[0], np.cumsum(gaps)])
        for run_id in np.unique(run_ids):
            mask = run_ids == run_id
            run = grp.iloc[mask]
            if len(run) < 2:
                continue

            entry = run.iloc[0]
            exit_ = run.iloc[-1]
            duration_min = (exit_["ts"] - entry["ts"]) / 60.0
            if duration_min < MIN_DURATION_MIN or duration_min > MAX_DURATION_MIN:
                continue

            # Use sog_eff (real or derived) for the entry-speed filter.
            entry_sog = float(entry["sog_eff"]) if not pd.isna(entry["sog_eff"]) else float("nan")
            if pd.isna(entry_sog) or entry_sog < MIN_ENTRY_SOG:
                continue

            run_speeds = run["sog_eff"].dropna()
            if not run_speeds.empty and float(run_speeds.median()) < MIN_MEDIAN_SPEED:
                continue

            dist_km = _haversine_km(entry["lat"], entry["lon"], exit_["lat"], exit_["lon"])
            if dist_km < min_dist:
                continue

            queue_depth = _queue_depth_at(sightings, bbox, entry["ts"], exclude_mmsi=int(mmsi))
            recent_throughput = _recent_throughput(sightings, bbox, entry["ts"])

            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(float(entry["ts"]), tz=timezone.utc)

            out.append({
                "chokepoint_id":         cp,
                "ship_type":             ship_type_bin(entry.get("ship_type")),
                "entry_sog_kn":          float(entry_sog),
                "queue_depth":           int(queue_depth),
                "hour_of_day":           int(dt.hour),
                "day_of_week":           int(dt.weekday()),
                "month":                 int(dt.month),
                "recent_throughput_24h": int(recent_throughput),
                "bbox_diagonal_km":      float(diag),
                "transit_minutes":       float(duration_min),
                "entry_ts":              float(entry["ts"]),
            })
    return out


def _queue_depth_at(
    sightings: pd.DataFrame, bbox: list[float], ts: float, exclude_mmsi: int
) -> int:
    """Distinct MMSIs (excluding the subject) inside bbox at ts ± QUEUE_WINDOW_SEC."""
    lo = ts - QUEUE_WINDOW_SEC
    hi = ts + QUEUE_WINDOW_SEC
    mask = (
        (sightings["ts"] >= lo) & (sightings["ts"] <= hi)
        & (sightings["mmsi"] != exclude_mmsi)
        & (sightings["lat"].between(bbox[0], bbox[2]))
        & (sightings["lon"].between(bbox[1], bbox[3]))
    )
    return int(sightings.loc[mask, "mmsi"].nunique())


def _recent_throughput(sightings: pd.DataFrame, bbox: list[float], entry_ts: float) -> int:
    """Distinct MMSIs in the 24h window ending at entry_ts."""
    lo = entry_ts - 86400.0
    mask = (
        (sightings["ts"] >= lo) & (sightings["ts"] <= entry_ts)
        & (sightings["lat"].between(bbox[0], bbox[2]))
        & (sightings["lon"].between(bbox[1], bbox[3]))
    )
    return int(sightings.loc[mask, "mmsi"].nunique())


# ---------------------------------------------------------------------------
# Feature matrix
# ---------------------------------------------------------------------------

def build_feature_matrix(
    df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, Any, list[str]]:
    """Encode categoricals and stack with numerics. Returns (X, y, encoder, names).

    The encoder is fit on the union of categories present in df. It must
    be persisted alongside the model so inference applies an identical
    transform.
    """
    from sklearn.preprocessing import OneHotEncoder

    # OneHotEncoder API changed between sklearn 1.1 and 1.2 (sparse → sparse_output).
    try:
        encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    except TypeError:  # pragma: no cover — sklearn < 1.2
        encoder = OneHotEncoder(sparse=False, handle_unknown="ignore")

    cat_arr = encoder.fit_transform(df[CATEGORICAL_FEATURES].astype(str))
    num_arr = df[NUMERIC_FEATURES].to_numpy(dtype=float)
    X = np.hstack([cat_arr, num_arr])

    cat_names = list(encoder.get_feature_names_out(CATEGORICAL_FEATURES))
    feature_names = cat_names + list(NUMERIC_FEATURES)

    y = df["transit_minutes"].to_numpy(dtype=float)
    return X, y, encoder, feature_names


def encode_inference_row(features: dict[str, Any], encoder) -> np.ndarray:
    """Encode a single inference example using a fitted encoder."""
    cat_df = pd.DataFrame(
        [[str(features.get("chokepoint_id", "")), str(features.get("ship_type", "unknown"))]],
        columns=CATEGORICAL_FEATURES,
    )
    cat_arr = encoder.transform(cat_df)
    num_row = np.array(
        [[float(features.get(name, 0.0) or 0.0) for name in NUMERIC_FEATURES]], dtype=float
    )
    return np.hstack([cat_arr, num_row])


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def load_artifact() -> dict | None:
    """Load the trained joblib bundle. Returns None if missing or unloadable.

    The bundle is a dict {q10, q50, q90, encoder, meta} produced by
    train_eta_model.py. xgboost and joblib are imported lazily so that
    environments without these libraries can still import eta_model and
    use the heuristic fallback.
    """
    if not _ARTIFACT_PATH.exists():
        return None
    try:
        import joblib  # noqa: F401  lazy
    except ImportError:
        return None
    try:
        import joblib
        bundle = joblib.load(_ARTIFACT_PATH)
        if not isinstance(bundle, dict) or "q50" not in bundle:
            return None
        return bundle
    except Exception:  # noqa: BLE001  malformed artifact must not crash UI
        return None


def predict_transit_minutes(
    chokepoint_id: str,
    features: dict[str, Any],
) -> dict[str, Any]:
    """Predict transit time for one chokepoint. Always returns a populated dict.

    Returns:
        {
            "p10": int,         # 10th percentile minutes
            "p50": int,         # median estimate
            "p90": int,         # 90th percentile minutes
            "n_train": int,     # rows used to train the model (0 for heuristic)
            "confidence": str,  # "model" | "heuristic" | "unseen_chokepoint"
        }

    `features` should include: ship_type (str bin or int code), entry_sog_kn,
    queue_depth, hour_of_day, day_of_week, month, recent_throughput_24h.
    Missing keys default to safe averages.
    """
    cp = chokepoint_id
    feats = dict(features)
    feats.setdefault("chokepoint_id", cp)
    feats.setdefault("bbox_diagonal_km", BBOX_DIAGONAL_KM.get(cp, 300.0))
    # Coerce ship_type: accept either an integer AIS code or a pre-binned string.
    st = feats.get("ship_type", "unknown")
    if not isinstance(st, str):
        st = ship_type_bin(st)
    elif st not in SHIP_TYPE_BINS:
        st = "unknown"
    feats["ship_type"] = st

    bundle = load_artifact()
    if bundle is None:
        return _heuristic_prediction(cp, feats, confidence="heuristic")

    encoder = bundle["encoder"]
    # Detect unseen chokepoints — if the encoder hasn't seen this category,
    # transform yields an all-zero block for that column group, which the
    # model would silently extrapolate from. Catch that and fall back.
    known_cps = set()
    for name in encoder.get_feature_names_out(CATEGORICAL_FEATURES):
        if name.startswith("chokepoint_id_"):
            known_cps.add(name[len("chokepoint_id_"):])
    if cp not in known_cps:
        return _heuristic_prediction(cp, feats, confidence="unseen_chokepoint")

    try:
        X = encode_inference_row(feats, encoder)
        p10 = float(bundle["q10"].predict(X)[0])
        p50 = float(bundle["q50"].predict(X)[0])
        p90 = float(bundle["q90"].predict(X)[0])
    except Exception:  # noqa: BLE001  belt-and-braces — never blank the UI
        return _heuristic_prediction(cp, feats, confidence="heuristic")

    # Quantile regressors trained independently can occasionally cross.
    # Sort and clip to a sensible range.
    pts = sorted([p10, p50, p90])
    p10, p50, p90 = pts
    p10 = max(MIN_DURATION_MIN, p10)
    p90 = min(MAX_DURATION_MIN, p90)

    n_train = int((bundle.get("meta") or {}).get("n_train", 0))
    return {
        "p10": int(round(p10)),
        "p50": int(round(p50)),
        "p90": int(round(p90)),
        "n_train": n_train,
        "confidence": "model",
    }


def _heuristic_prediction(cp: str, feats: dict, confidence: str) -> dict[str, Any]:
    base = HEURISTIC_MEAN_MIN.get(cp, 360.0)
    queue = float(feats.get("queue_depth", 10) or 10)
    # Linear queue penalty — same shape as the trainer learns.
    p50 = base * (1.0 + 0.10 * (queue / 10.0 - 1.0))
    p10 = p50 * 0.75
    p90 = p50 * 1.30
    return {
        "p10": int(round(p10)),
        "p50": int(round(p50)),
        "p90": int(round(p90)),
        "n_train": 0,
        "confidence": confidence,
    }


def predict_total_for_route(
    chokepoints: list[str],
    features_per_chokepoint: dict[str, dict] | None = None,
    default_features: dict | None = None,
    force_heuristic: bool = False,
) -> dict[str, Any]:
    """Sum predicted transit times across all chokepoints in a route.

    Returns the aggregate dict with summed p10/p50/p90 (in minutes) plus a
    `confidence` field set to the weakest prediction in the chain — if any
    chokepoint falls back to heuristic, the whole route is heuristic.

    When `force_heuristic=True`, every chokepoint goes through the
    heuristic path, bypassing the trained artifact even if loaded. Used
    by the UI's "Compare ML vs heuristic" toggle.
    """
    features_per_chokepoint = features_per_chokepoint or {}
    default_features = default_features or {}
    if not chokepoints:
        return {"p10": 0, "p50": 0, "p90": 0, "n_train": 0, "confidence": "model"}

    total_p10 = total_p50 = total_p90 = 0
    n_trains: list[int] = []
    confidences: list[str] = []
    for cp in chokepoints:
        feats = {**default_features, **features_per_chokepoint.get(cp, {})}
        if force_heuristic:
            pred = _heuristic_prediction(cp, feats, confidence="heuristic")
        else:
            pred = predict_transit_minutes(cp, feats)
        total_p10 += pred["p10"]
        total_p50 += pred["p50"]
        total_p90 += pred["p90"]
        n_trains.append(pred["n_train"])
        confidences.append(pred["confidence"])

    # Worst-case confidence in the chain wins (model > heuristic > unseen).
    if "unseen_chokepoint" in confidences:
        overall = "unseen_chokepoint"
    elif "heuristic" in confidences:
        overall = "heuristic"
    else:
        overall = "model"

    return {
        "p10": int(total_p10),
        "p50": int(total_p50),
        "p90": int(total_p90),
        "n_train": min(n_trains) if n_trains else 0,
        "confidence": overall,
    }


# ---------------------------------------------------------------------------
# SHAP explanations
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _shap_explainer():
    """Return (TreeExplainer, feature_names) or (None, None) if unavailable.

    Uses the q50 model from the loaded artifact. Lazy import — never crashes
    the module if shap isn't installed.
    """
    try:
        import shap  # type: ignore[import-untyped]
    except ImportError:
        return None, None
    bundle = load_artifact()
    if bundle is None or "q50" not in bundle:
        return None, None
    try:
        return shap.TreeExplainer(bundle["q50"]), (bundle.get("meta") or {}).get("feature_names") or FEATURE_NAMES
    except Exception:  # noqa: BLE001
        return None, None


def explain_prediction(
    features: dict[str, Any],
    top_k: int = 3,
) -> list[tuple[str, float]]:
    """Return the top-k SHAP feature contributions for one inference row.

    Each tuple is (feature_label, contribution_in_minutes). Returns an empty
    list if shap is unavailable or the model artifact isn't loaded —
    callers should treat empty as "no explanation available" and surface a
    fallback message in the UI.

    Feature labels are humanised: "queue_depth (12)" / "ship_type (tanker)" /
    "chokepoint_id (Suez Canal)" so the UI can render them directly.
    """
    explainer, feature_names = _shap_explainer()
    if explainer is None or not feature_names:
        return []
    bundle = load_artifact()
    if bundle is None:
        return []
    try:
        X_row = encode_inference_row(features, bundle["encoder"])
        shap_vals = explainer.shap_values(X_row)
        contributions = np.asarray(shap_vals).ravel()
    except Exception:  # noqa: BLE001
        return []

    # Aggregate one-hot columns back to their parent categorical features so
    # the UI shows "ship_type (tanker)" rather than "ship_type_tanker".
    pairs: list[tuple[str, float]] = []
    used = set()
    for cat in CATEGORICAL_FEATURES:
        prefix = f"{cat}_"
        cat_total = 0.0
        cat_idxs = [i for i, n in enumerate(feature_names) if n.startswith(prefix)]
        for i in cat_idxs:
            cat_total += float(contributions[i])
            used.add(i)
        cat_value = features.get(cat, "?")
        pairs.append((f"{cat} ({cat_value})", cat_total))
    for i, name in enumerate(feature_names):
        if i in used:
            continue
        v = features.get(name, "?")
        pairs.append((f"{name} ({v})", float(contributions[i])))

    pairs.sort(key=lambda kv: -abs(kv[1]))
    return pairs[:top_k]
