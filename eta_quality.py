"""ETA model live-quality tracking.

This module closes the loop on `eta_model.predict_transit_minutes()`. Every
prediction is logged to `eta_predictions` at call time; once the same
vessel finishes transiting the chokepoint bbox, the matcher fills in the
actual transit duration. From the (predicted, actual) pairs we compute
live accuracy, interval coverage, and drift metrics.

No machine learning happens here. The matcher walks `sightings`, the
metrics are simple aggregates, and the confidence score is a small
weighted blend. Pandas + numpy + sqlite only.

Public surface:
    match_open_predictions(db_path, lookback_h) -> dict counts
    compute_quality_metrics(db_path, window_days, chokepoint_id) -> dict
    compute_confidence_score(chokepoint_id, pred, quality) -> (int, str)
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from eta_model import CHOKEPOINT_BBOXES, _ensure_predictions_table

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
DB_PATH = _HERE / ".ais_positions.db"
META_PATH = _HERE / "models" / "eta_meta.json"

# Gap (sec) inside a bbox that ends a run — mirrors eta_model.GAP_MIN.
_RUN_GAP_SEC = 60 * 60
# Min plausible transit duration before we'll record an actual_min.
_MIN_TRANSIT_MIN = 5.0
# Drift threshold — rolling MAE this much above training MAE triggers a flag.
_DRIFT_RATIO = 1.25


# ---------------------------------------------------------------------------
# Matching predicted -> actual
# ---------------------------------------------------------------------------

def _find_next_transit(
    con: sqlite3.Connection,
    mmsi: int,
    chokepoint_id: str,
    after_ts: float,
    lookback_sec: float,
    now_ts: float,
    entry_grace_sec: float = 0.0,
) -> tuple[float, float] | None:
    """Find the next entry/exit pair for `mmsi` inside the chokepoint bbox
    that starts after `after_ts` and within `lookback_sec`.

    `entry_grace_sec` widens the lower bound by that many seconds — useful
    for shadow predictions logged at the moment of detected entry, where
    the actual first sighting can be slightly *before* predicted_at due to
    sampling cadence (10-min scheduler tick vs ~sec-level AIS updates).

    Returns (entry_ts, exit_ts) or None. A run is bounded either by a
    >1h gap in sightings or, if the last sighting is >1h ago and within
    the lookback window, by that last sighting (treated as the exit).
    """
    bbox = CHOKEPOINT_BBOXES.get(chokepoint_id)
    if not bbox:
        return None
    lat_min, lon_min, lat_max, lon_max = bbox
    rows = con.execute(
        """SELECT ts FROM sightings
           WHERE mmsi = ? AND ts >= ? AND ts <= ?
             AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
           ORDER BY ts""",
        (mmsi, after_ts - entry_grace_sec, after_ts + lookback_sec,
         lat_min, lat_max, lon_min, lon_max),
    ).fetchall()
    if len(rows) < 2:
        return None

    entry_ts = rows[0][0]
    prev = entry_ts
    for (t,) in rows[1:]:
        if t - prev > _RUN_GAP_SEC:
            # End of the first run inside the bbox.
            return (entry_ts, prev) if (prev - entry_ts) / 60.0 >= _MIN_TRANSIT_MIN else None
        prev = t

    # No gap encountered. Either the vessel is still in the bbox or it has
    # gone silent. If the last sighting is >1h ago we consider the run closed.
    if now_ts - prev > _RUN_GAP_SEC and (prev - entry_ts) / 60.0 >= _MIN_TRANSIT_MIN:
        return (entry_ts, prev)
    return None


def match_open_predictions(
    db_path: Path | str | None = None,
    lookback_h: int = 72,
    null_mmsi_lookback_h: int | None = None,
    entry_grace_sec: float = 0.0,
) -> dict:
    """Match predictions with NULL actual_min to their realised transits.

    Walks every row where `actual_min IS NULL`. For each, looks for the
    next transit of the same MMSI through the same chokepoint after
    predicted_at, within `lookback_h` hours. Predictions older than
    lookback with no match are marked 'expired'. Predictions without an
    MMSI cannot be matched and are likewise expired once old.

    `null_mmsi_lookback_h` overrides the expiry window for NULL-MMSI rows
    (anonymous router predictions that can never match). Defaults to the
    main `lookback_h`; pass 1 from the periodic scheduler tick to drain
    them within minutes instead of letting them clog the dashboard.

    `entry_grace_sec` widens the lower time bound when looking for the
    realised transit — see `_find_next_transit`. Used by the shadow-prediction
    scheduler tick where predicted_at can lag the actual entry by a few minutes.

    Returns counts {matched, expired, still_open}.
    """
    db = Path(db_path) if db_path is not None else DB_PATH
    if not db.exists():
        return {"matched": 0, "expired": 0, "still_open": 0}

    now_ts = time.time()
    lookback_sec = lookback_h * 3600
    null_lookback_sec = (null_mmsi_lookback_h if null_mmsi_lookback_h is not None else lookback_h) * 3600
    matched = expired = still_open = 0

    with sqlite3.connect(db, timeout=5.0) as con:
        _ensure_predictions_table(con)
        # If sightings doesn't exist (eg. tests built only the eta_predictions
        # table), there's nothing to match against — just expire stale rows.
        has_sightings = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sightings'"
        ).fetchone() is not None

        open_rows = con.execute(
            """SELECT pred_id, predicted_at, chokepoint_id, mmsi
               FROM eta_predictions
               WHERE actual_min IS NULL
               ORDER BY predicted_at"""
        ).fetchall()

        for pred_id, predicted_at, cp, mmsi in open_rows:
            age_sec = now_ts - float(predicted_at)
            if mmsi is None or not has_sightings:
                if age_sec > null_lookback_sec:
                    con.execute(
                        "UPDATE eta_predictions SET match_method=?, matched_at=? WHERE pred_id=?",
                        ("expired", now_ts, pred_id),
                    )
                    expired += 1
                else:
                    still_open += 1
                continue

            transit = _find_next_transit(
                con, int(mmsi), cp, float(predicted_at), lookback_sec, now_ts,
                entry_grace_sec=entry_grace_sec,
            )
            if transit:
                entry_ts, exit_ts = transit
                actual_min = (exit_ts - entry_ts) / 60.0
                con.execute(
                    """UPDATE eta_predictions
                       SET actual_min=?, actual_entry_ts=?, actual_exit_ts=?,
                           matched_at=?, match_method=?
                       WHERE pred_id=?""",
                    (actual_min, entry_ts, exit_ts, now_ts, "mmsi_window", pred_id),
                )
                matched += 1
            elif age_sec > lookback_sec:
                con.execute(
                    "UPDATE eta_predictions SET match_method=?, matched_at=? WHERE pred_id=?",
                    ("expired", now_ts, pred_id),
                )
                expired += 1
            else:
                still_open += 1

    return {"matched": matched, "expired": expired, "still_open": still_open}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _training_meta() -> dict[str, Any]:
    """Read models/eta_meta.json or return {} when missing."""
    if not META_PATH.exists():
        return {}
    try:
        return json.loads(META_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _read_closed_predictions(
    db: Path, window_days: int, chokepoint_id: str | None
) -> pd.DataFrame:
    """Pull closed-out predictions (with actual_min set) inside the window."""
    if not db.exists():
        return pd.DataFrame()
    cutoff = time.time() - window_days * 86400
    sql = (
        "SELECT chokepoint_id, predicted_at, source, p10_min, p50_min, p90_min, "
        "actual_min, actual_entry_ts, actual_exit_ts, mmsi "
        "FROM eta_predictions "
        "WHERE actual_min IS NOT NULL AND predicted_at >= ?"
    )
    params: list[Any] = [cutoff]
    if chokepoint_id:
        sql += " AND chokepoint_id = ?"
        params.append(chokepoint_id)
    try:
        with sqlite3.connect(db, timeout=5.0) as con:
            _ensure_predictions_table(con)
            return pd.read_sql_query(sql, con, params=params)
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


def _open_counts(db: Path) -> tuple[int, int]:
    """(n_open, n_expired) — useful for the dashboard's match-health tile."""
    if not db.exists():
        return (0, 0)
    try:
        with sqlite3.connect(db, timeout=5.0) as con:
            _ensure_predictions_table(con)
            n_open = con.execute(
                "SELECT COUNT(*) FROM eta_predictions WHERE actual_min IS NULL "
                "AND (match_method IS NULL OR match_method != 'expired')"
            ).fetchone()[0]
            n_exp = con.execute(
                "SELECT COUNT(*) FROM eta_predictions WHERE actual_min IS NULL "
                "AND match_method = 'expired'"
            ).fetchone()[0]
            return (int(n_open), int(n_exp))
    except sqlite3.Error:
        return (0, 0)


def _pinball_loss(actual: np.ndarray, pred: np.ndarray, alpha: float) -> float:
    diff = actual - pred
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def _row_metrics(df: pd.DataFrame) -> dict[str, float]:
    """Per-group (per-chokepoint or overall) summary stats."""
    if df.empty:
        return {
            "n_closed": 0,
            "rolling_mae_min": 0.0,
            "mape_pct": 0.0,
            "accuracy_pct_15": 0.0,
            "accuracy_pct_25": 0.0,
            "coverage_p10_p90": 0.0,
            "bias_min": 0.0,
            "pinball_p10": 0.0,
            "pinball_p50": 0.0,
            "pinball_p90": 0.0,
        }
    actual = df["actual_min"].to_numpy(dtype=float)
    p10 = df["p10_min"].to_numpy(dtype=float)
    p50 = df["p50_min"].to_numpy(dtype=float)
    p90 = df["p90_min"].to_numpy(dtype=float)
    abs_err = np.abs(p50 - actual)
    # Cap pct error denominator to avoid blow-up on near-zero actuals (which
    # shouldn't happen given the 5-min floor, but belt-and-braces).
    denom = np.maximum(actual, 1.0)
    pct_err = np.abs(p50 - actual) / denom
    return {
        "n_closed": int(len(df)),
        "rolling_mae_min": float(np.mean(abs_err)),
        "mape_pct": float(np.mean(pct_err) * 100.0),
        "accuracy_pct_15": float(np.mean(pct_err <= 0.15) * 100.0),
        "accuracy_pct_25": float(np.mean(pct_err <= 0.25) * 100.0),
        "coverage_p10_p90": float(np.mean((actual >= p10) & (actual <= p90))),
        "bias_min": float(np.mean(p50 - actual)),
        "pinball_p10": _pinball_loss(actual, p10, 0.10),
        "pinball_p50": _pinball_loss(actual, p50, 0.50),
        "pinball_p90": _pinball_loss(actual, p90, 0.90),
    }


def compute_quality_metrics(
    db_path: Path | str | None = None,
    window_days: int = 30,
    chokepoint_id: str | None = None,
) -> dict[str, Any]:
    """Aggregate live-prediction quality metrics from `eta_predictions`.

    See module docstring for the shape of the returned dict.
    """
    db = Path(db_path) if db_path is not None else DB_PATH
    df = _read_closed_predictions(db, window_days, chokepoint_id)
    overall = _row_metrics(df)

    by_cp: dict[str, dict[str, float]] = {}
    if not df.empty:
        for cp, group in df.groupby("chokepoint_id"):
            by_cp[str(cp)] = _row_metrics(group)

    by_day: list[dict[str, Any]] = []
    if not df.empty:
        df_day = df.assign(
            day=pd.to_datetime(df["predicted_at"], unit="s").dt.floor("D")
        )
        for day, group in df_day.groupby("day"):
            metrics = _row_metrics(group)
            by_day.append(
                {"day": day.date().isoformat(), **metrics}
            )

    meta = _training_meta()
    training_mae = float(meta.get("mae_minutes", 0.0) or 0.0)
    drift_flag = (
        overall["n_closed"] >= 10
        and training_mae > 0
        and overall["rolling_mae_min"] > _DRIFT_RATIO * training_mae
    )

    n_open, n_expired = _open_counts(db)

    return {
        **overall,
        "n_open": n_open,
        "n_expired": n_expired,
        "by_chokepoint": by_cp,
        "by_day": by_day,
        "training_mae_min": training_mae,
        "drift_flag": bool(drift_flag),
        "window_days": int(window_days),
    }


# ---------------------------------------------------------------------------
# Recent prediction log (audit trail)
# ---------------------------------------------------------------------------

def recent_predictions(
    limit: int = 50,
    chokepoint_id: str | None = None,
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    """Return the most-recently-logged predictions, newest first.

    Read-only audit view of the `eta_predictions` table. Columns include
    inputs (queue_depth, recent_throughput_24h, etc.), outputs (p10/p50/p90),
    and the realised `actual_min` if the matcher has closed it out.
    """
    db = Path(db_path) if db_path is not None else DB_PATH
    if not db.exists():
        return pd.DataFrame()
    sql = (
        "SELECT predicted_at, chokepoint_id, mmsi, source, "
        "ship_type, entry_sog_kn, queue_depth, recent_throughput_24h, "
        "p10_min, p50_min, p90_min, actual_min, match_method "
        "FROM eta_predictions"
    )
    params: list[Any] = []
    if chokepoint_id:
        sql += " WHERE chokepoint_id = ?"
        params.append(chokepoint_id)
    sql += " ORDER BY predicted_at DESC LIMIT ?"
    params.append(int(limit))
    try:
        with sqlite3.connect(db, timeout=5.0) as con:
            from eta_model import _ensure_predictions_table as _ensure
            _ensure(con)
            df = pd.read_sql_query(sql, con, params=params)
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()
    if not df.empty:
        df["predicted_at"] = pd.to_datetime(df["predicted_at"], unit="s")
    return df


# ---------------------------------------------------------------------------
# Live feature snapshot (for the page's "Feature inspector" panel)
# ---------------------------------------------------------------------------

def live_features_for_chokepoint(
    chokepoint_id: str,
    db_path: Path | str | None = None,
    now_ts: float | None = None,
    ship_type: str = "container",
    entry_sog_kn: float = 12.0,
) -> dict[str, Any]:
    """Compute the feature row a prediction *would* use right now.

    Mirrors the features the trainer extracts at entry time, but anchored
    at `now_ts` (default: time.time()) instead of a transit's entry
    timestamp. Used by the ETA Quality page's "How is this ETA computed
    right now?" panel — read-only, no DB writes.

    `ship_type` and `entry_sog_kn` default to a typical container vessel
    at 12 kn so existing callers stay backwards-compatible; the ETA
    Quality page's vessel selectbox overrides both.
    """
    from eta_model import BBOX_DIAGONAL_KM, QUEUE_WINDOW_SEC

    now_ts = now_ts if now_ts is not None else time.time()
    bbox = CHOKEPOINT_BBOXES.get(chokepoint_id)
    if not bbox:
        return {}
    lat_min, lon_min, lat_max, lon_max = bbox
    db = Path(db_path) if db_path is not None else DB_PATH
    queue = 0
    throughput = 0
    if db.exists():
        try:
            with sqlite3.connect(db, timeout=5.0) as con:
                row = con.execute(
                    """SELECT COUNT(DISTINCT mmsi) FROM sightings
                       WHERE ts BETWEEN ? AND ?
                         AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?""",
                    (now_ts - QUEUE_WINDOW_SEC, now_ts + QUEUE_WINDOW_SEC,
                     lat_min, lat_max, lon_min, lon_max),
                ).fetchone()
                queue = int(row[0]) if row else 0
                row = con.execute(
                    """SELECT COUNT(DISTINCT mmsi) FROM sightings
                       WHERE ts BETWEEN ? AND ?
                         AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?""",
                    (now_ts - 86400.0, now_ts,
                     lat_min, lat_max, lon_min, lon_max),
                ).fetchone()
                throughput = int(row[0]) if row else 0
        except sqlite3.Error:
            pass

    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    return {
        "chokepoint_id": chokepoint_id,
        "ship_type": str(ship_type),
        "entry_sog_kn": float(entry_sog_kn),
        "queue_depth": queue,
        "hour_of_day": dt.hour,
        "day_of_week": dt.weekday(),
        "month": dt.month,
        "recent_throughput_24h": throughput,
        "bbox_diagonal_km": float(BBOX_DIAGONAL_KM.get(chokepoint_id, 300.0)),
    }


# ---------------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------------

def compute_confidence_score(
    chokepoint_id: str,
    pred: dict[str, Any],
    quality: dict[str, Any] | None = None,
) -> tuple[int, str]:
    """Composite 0-100 confidence score with a one-line justification.

    Blend:
      • Source weight:    model=60, heuristic=25, unseen_chokepoint=10
      • n_train scaling:  +0..20 from min(n_train/500, 1) × 20
      • Recent accuracy:  +0..15 from accuracy_pct_15 / 100 × 15
      • Interval tightness: +0..5 inversely with (p90-p10)/p50
    Clamped to [0, 100]. The justification echoes the four contributions
    so the UI can show "model+n=180+live60%" or similar.
    """
    source = str(pred.get("confidence", "heuristic"))
    n_train = int(pred.get("n_train", 0) or 0)
    p10 = float(pred.get("p10", 0) or 0)
    p50 = float(pred.get("p50", 0) or 0)
    p90 = float(pred.get("p90", 0) or 0)

    source_weight = {"model": 60.0, "heuristic": 25.0, "unseen_chokepoint": 10.0}.get(source, 10.0)
    n_train_pts = min(n_train / 500.0, 1.0) * 20.0

    live_pts = 0.0
    live_label = ""
    if quality and isinstance(quality.get("by_chokepoint"), dict):
        cp_q = quality["by_chokepoint"].get(chokepoint_id)
        if cp_q and cp_q.get("n_closed", 0) >= 5:
            acc15 = float(cp_q.get("accuracy_pct_15", 0.0) or 0.0)
            live_pts = (acc15 / 100.0) * 15.0
            live_label = f", live {acc15:.0f}%"

    tightness_pts = 0.0
    if p50 > 0:
        # Heuristic band is by construction ~73% of p50 wide. Anything tighter
        # than 50% wide gets the full 5 pts; wider gets less.
        width_ratio = max(0.0, (p90 - p10) / max(p50, 1.0))
        tightness_pts = max(0.0, min(5.0, 5.0 * (1.0 - min(width_ratio / 1.0, 1.0))))

    score = source_weight + n_train_pts + live_pts + tightness_pts
    score = int(round(max(0.0, min(100.0, score))))
    justification = f"{source}, n={n_train}{live_label}"
    return score, justification
