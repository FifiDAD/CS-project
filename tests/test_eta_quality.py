"""Tests for eta_quality: prediction-log writes, matcher, metrics, confidence."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

import eta_model
import eta_quality
from eta_quality import (
    compute_confidence_score,
    compute_quality_metrics,
    live_features_for_chokepoint,
    match_open_predictions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_db(db: Path) -> None:
    """Create the schema for both sightings and eta_predictions in `db`.

    Mirrors ais_consumer._init_db() but without importing it (avoids
    websockets dependency at test time).
    """
    with sqlite3.connect(db) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS sightings (
                mmsi INTEGER, lat REAL, lon REAL, sog_kn REAL,
                ship_type INTEGER, ts REAL
            )"""
        )
        eta_model._ensure_predictions_table(con)


def _insert_prediction(
    db: Path,
    *,
    cp: str,
    predicted_at: float,
    mmsi: int | None,
    p10: int,
    p50: int,
    p90: int,
    actual: float | None = None,
    source: str = "model",
) -> str:
    import uuid
    # Give each test prediction a unique row id.
    pid = uuid.uuid4().hex
    with sqlite3.connect(db) as con:
        con.execute(
            """INSERT INTO eta_predictions (
                pred_id, predicted_at, chokepoint_id, mmsi, source,
                p10_min, p50_min, p90_min, actual_min
            ) VALUES (?,?,?,?,?, ?,?,?, ?)""",
            (pid, predicted_at, cp, mmsi, source, p10, p50, p90, actual),
        )
    return pid


def _insert_sighting(db: Path, *, mmsi: int, lat: float, lon: float, ts: float) -> None:
    with sqlite3.connect(db) as con:
        con.execute(
            "INSERT INTO sightings (mmsi, lat, lon, sog_kn, ship_type, ts) VALUES (?,?,?,?,?,?)",
            (mmsi, lat, lon, 10.0, 70, ts),
        )


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch) -> Path:
    db = tmp_path / "test.db"
    _seed_db(db)
    # Redirect both modules to the test database.
    monkeypatch.setattr(eta_quality, "DB_PATH", db)
    monkeypatch.setattr(eta_model, "_DB_PATH", db)
    monkeypatch.setattr(eta_model, "_PREDICTIONS_TABLE_READY", False)
    return db


# ---------------------------------------------------------------------------
# Prediction logging
# ---------------------------------------------------------------------------

def test_predict_transit_minutes_logs_row(fresh_db: Path):
    """Calling predict_transit_minutes once should write one row to eta_predictions."""
    eta_model.predict_transit_minutes(
        "Suez Canal",
        {"queue_depth": 10, "ship_type": "container", "entry_sog_kn": 12.0},
        mmsi=123456789,
    )
    with sqlite3.connect(fresh_db) as con:
        rows = con.execute(
            "SELECT chokepoint_id, mmsi, p50_min, source FROM eta_predictions"
        ).fetchall()
    assert len(rows) == 1
    cp, mmsi, p50, source = rows[0]
    assert cp == "Suez Canal"
    assert mmsi == 123456789
    assert p50 > 0
    assert source in {"model", "heuristic", "unseen_chokepoint"}


def test_predict_disable_log(fresh_db: Path):
    eta_model.predict_transit_minutes(
        "Suez Canal", {"queue_depth": 5}, log=False
    )
    with sqlite3.connect(fresh_db) as con:
        n = con.execute("SELECT COUNT(*) FROM eta_predictions").fetchone()[0]
    assert n == 0


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------

def test_match_open_predictions_fills_actual(fresh_db: Path):
    """A logged prediction followed by a sightings trail through Suez bbox gets matched."""
    t_pred = time.time() - 6 * 3600  # 6h ago
    t_entry = t_pred + 600  # 10 min after prediction
    t_exit = t_entry + 900 * 60  # 15h transit (long but inside cap)

    _insert_prediction(
        fresh_db, cp="Suez Canal", predicted_at=t_pred, mmsi=42,
        p10=600, p50=900, p90=1300,
    )
    # Prediction is followed by sightings from the same MMSI.
    # Two sightings inside Suez bbox (27..33 lat, 31..35 lon), separated
    # by 15h so the run is bounded by the lookback.
    _insert_sighting(fresh_db, mmsi=42, lat=30.0, lon=32.5, ts=t_entry)
    _insert_sighting(fresh_db, mmsi=42, lat=30.5, lon=32.7, ts=t_entry + 1800)  # 30min in
    # The vessel "leaves" — last sighting in bbox is more than 1h before now.
    _insert_sighting(fresh_db, mmsi=42, lat=30.7, lon=32.9, ts=t_entry + 50 * 60)

    counts = match_open_predictions()
    assert counts["matched"] >= 1
    with sqlite3.connect(fresh_db) as con:
        actual = con.execute(
            "SELECT actual_min, match_method FROM eta_predictions WHERE mmsi=42"
        ).fetchone()
    assert actual[0] is not None
    assert actual[1] == "mmsi_window"
    assert actual[0] >= 40  # at least 40 min (entry to last-in-bbox = 50min)


def test_match_expires_old_predictions(fresh_db: Path):
    """Prediction with no matching sighting and older than lookback → expired."""
    t_old = time.time() - 100 * 3600  # 100h ago, beyond 72h lookback
    _insert_prediction(
        fresh_db, cp="Bosphorus", predicted_at=t_old, mmsi=999,
        p10=80, p50=120, p90=200,
    )
    counts = match_open_predictions(lookback_h=72)
    assert counts["expired"] == 1
    with sqlite3.connect(fresh_db) as con:
        method = con.execute(
            "SELECT match_method FROM eta_predictions WHERE mmsi=999"
        ).fetchone()[0]
    assert method == "expired"


def test_match_anonymous_predictions_expire(fresh_db: Path):
    """Predictions logged without an MMSI cannot be matched; they expire eventually."""
    t_old = time.time() - 100 * 3600
    _insert_prediction(
        fresh_db, cp="Suez Canal", predicted_at=t_old, mmsi=None,
        p10=600, p50=900, p90=1300,
    )
    counts = match_open_predictions(lookback_h=72)
    assert counts["expired"] == 1


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_compute_quality_metrics_empty(fresh_db: Path):
    m = compute_quality_metrics()
    assert m["n_closed"] == 0
    assert m["rolling_mae_min"] == 0.0
    assert m["accuracy_pct_15"] == 0.0
    assert m["coverage_p10_p90"] == 0.0
    assert m["by_chokepoint"] == {}


def test_compute_quality_metrics_perfect_predictions(fresh_db: Path):
    """When p50 == actual for every row, MAE=0, accuracy=100%, coverage=1.0."""
    now = time.time()
    # Insert matched rows where prediction equals reality.
    for i in range(20):
        _insert_prediction(
            fresh_db, cp="Suez Canal", predicted_at=now - i * 3600,
            mmsi=i, p10=600, p50=900, p90=1300, actual=900.0,
        )
    m = compute_quality_metrics(window_days=30)
    assert m["n_closed"] == 20
    assert m["rolling_mae_min"] == pytest.approx(0.0, abs=0.1)
    assert m["accuracy_pct_15"] == pytest.approx(100.0)
    assert m["accuracy_pct_25"] == pytest.approx(100.0)
    assert m["coverage_p10_p90"] == pytest.approx(1.0)
    assert m["bias_min"] == pytest.approx(0.0, abs=0.1)


def test_compute_quality_metrics_per_chokepoint(fresh_db: Path):
    """Different chokepoints with different errors should appear separately."""
    now = time.time()
    # Suez: perfect
    for i in range(5):
        _insert_prediction(
            fresh_db, cp="Suez Canal", predicted_at=now - i * 3600,
            mmsi=i, p10=600, p50=900, p90=1300, actual=900.0,
        )
    # Bosphorus: 20% over
    for i in range(5):
        _insert_prediction(
            fresh_db, cp="Bosphorus", predicted_at=now - i * 3600,
            mmsi=1000 + i, p10=80, p50=120, p90=200, actual=100.0,  # under by 20min
        )
    m = compute_quality_metrics(window_days=30)
    assert set(m["by_chokepoint"].keys()) == {"Suez Canal", "Bosphorus"}
    suez = m["by_chokepoint"]["Suez Canal"]
    bos = m["by_chokepoint"]["Bosphorus"]
    assert suez["rolling_mae_min"] == pytest.approx(0.0, abs=0.1)
    assert bos["rolling_mae_min"] == pytest.approx(20.0, abs=0.1)


# ---------------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------------

def test_confidence_score_bounds():
    """Score is always clamped to [0, 100]."""
    pred_model = {"p10": 600, "p50": 900, "p90": 1100, "n_train": 10_000, "confidence": "model"}
    score, _ = compute_confidence_score("Suez Canal", pred_model)
    assert 0 <= score <= 100

    pred_unseen = {"p10": 10, "p50": 50, "p90": 200, "n_train": 0, "confidence": "unseen_chokepoint"}
    score, _ = compute_confidence_score("Mythical Strait", pred_unseen)
    assert 0 <= score <= 100


def test_confidence_score_monotonic_in_n_train():
    """More training data → higher confidence, all else equal."""
    base = {"p10": 600, "p50": 900, "p90": 1100, "confidence": "model"}
    low, _ = compute_confidence_score("Suez Canal", {**base, "n_train": 50})
    high, _ = compute_confidence_score("Suez Canal", {**base, "n_train": 5000})
    assert high > low


def test_confidence_score_source_ordering():
    """model > heuristic > unseen_chokepoint, all else equal."""
    base = {"p10": 600, "p50": 900, "p90": 1100, "n_train": 200}
    model, _ = compute_confidence_score("Suez Canal", {**base, "confidence": "model"})
    heur, _ = compute_confidence_score("Suez Canal", {**base, "confidence": "heuristic"})
    unseen, _ = compute_confidence_score("Suez Canal", {**base, "confidence": "unseen_chokepoint"})
    assert model > heur > unseen


def test_confidence_score_live_accuracy_bonus():
    """When live quality has good accuracy for this CP, score gets a bonus."""
    base = {"p10": 600, "p50": 900, "p90": 1100, "n_train": 200, "confidence": "model"}
    bad_quality = {"by_chokepoint": {"Suez Canal": {"n_closed": 10, "accuracy_pct_15": 10.0}}}
    good_quality = {"by_chokepoint": {"Suez Canal": {"n_closed": 10, "accuracy_pct_15": 90.0}}}
    bad, _ = compute_confidence_score("Suez Canal", base, bad_quality)
    good, _ = compute_confidence_score("Suez Canal", base, good_quality)
    assert good > bad


# ---------------------------------------------------------------------------
# Live feature snapshot
# ---------------------------------------------------------------------------

def test_live_features_for_chokepoint_returns_required_keys(fresh_db: Path):
    feats = live_features_for_chokepoint("Suez Canal")
    required = {
        "chokepoint_id", "ship_type", "entry_sog_kn", "queue_depth",
        "hour_of_day", "day_of_week", "month",
        "recent_throughput_24h", "bbox_diagonal_km",
    }
    assert required <= set(feats.keys())
    assert feats["chokepoint_id"] == "Suez Canal"
    assert 0 <= feats["hour_of_day"] <= 23
    assert 0 <= feats["day_of_week"] <= 6
    # Defaults match the historical signature so existing callers stay green.
    assert feats["ship_type"] == "container"
    assert feats["entry_sog_kn"] == 12.0

    # The vessel selectbox on the ETA Quality page overrides both kwargs;
    # the function must forward those values through to the feature row.
    overridden = live_features_for_chokepoint(
        "Suez Canal", ship_type="tanker", entry_sog_kn=15.5,
    )
    assert overridden["ship_type"] == "tanker"
    assert overridden["entry_sog_kn"] == 15.5


def test_live_features_for_unknown_chokepoint_returns_empty():
    assert live_features_for_chokepoint("Made-up Strait") == {}


def test_live_queue_snapshot_matches_training_window(tmp_path, monkeypatch):
    """The inference-time queue_depth helper must use the SAME ±5-min window
    that the trainer uses (eta_model._queue_depth_at, QUEUE_WINDOW_SEC=300).

    Without this, the model is fed 24-h aggregates (300+ vessels) where it
    was trained on 5-min snapshots (5-30 vessels) — out-of-distribution.
    """
    import ais_consumer
    db = tmp_path / "qs.db"
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE sightings (mmsi INTEGER, lat REAL, lon REAL, "
            "sog_kn REAL, ship_type INTEGER, ts REAL)"
        )
    monkeypatch.setattr(ais_consumer, "_DB_PATH", db)

    suez_bbox = [27.0, 31.0, 33.0, 35.0]
    now = time.time()
    with sqlite3.connect(db) as con:
        # 5 vessels inside the ±300s window  → snapshot should see them
        for i in range(5):
            con.execute(
                "INSERT INTO sightings VALUES (?,?,?,?,?,?)",
                (100 + i, 30.0, 32.5, 10.0, 70, now - 60 + i),
            )
        # 200 extra vessels inside the bbox but well *outside* ±300s
        # (placed 30 min ago) — these should NOT be counted by the snapshot.
        for i in range(200):
            con.execute(
                "INSERT INTO sightings VALUES (?,?,?,?,?,?)",
                (500 + i, 30.0, 32.5, 10.0, 70, now - 1800),
            )

    snap = ais_consumer.live_queue_snapshot(suez_bbox, window_sec=300)
    assert snap == 5, (
        f"snapshot expected 5 (only ±5-min vessels), got {snap}. "
        "The training distribution is ±300s; using a wider window here "
        "would reintroduce the feature drift this helper exists to fix."
    )

    # Same data through the 24-h transits helper should see all 205.
    full = ais_consumer.transits_24h(suez_bbox)
    assert full == 205

