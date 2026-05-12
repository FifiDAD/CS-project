"""Tests for eta_model.py — extraction, encoding, and inference paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from eta_model import (
    BBOX_DIAGONAL_KM,
    HEURISTIC_MEAN_MIN,
    build_feature_matrix,
    extract_transits,
    encode_inference_row,
    predict_total_for_route,
    predict_transit_minutes,
    ship_type_bin,
)


# ---------------------------------------------------------------------------
# extract_transits — edge cases
# ---------------------------------------------------------------------------

def test_extract_transits_empty_db(empty_db):
    df = extract_transits(empty_db)
    assert df.empty
    assert "transit_minutes" in df.columns


def test_extract_transits_simple_pass(empty_db, make_track, t0):
    """One vessel cleanly enters Suez at ~28°N, traverses ~3° north, exits."""
    points = []
    for i in range(8):
        # 8 sightings spaced 30 min apart, vessel moves north through Suez
        lat = 28.0 + i * 0.4
        lon = 33.0
        ts = t0 + i * 1800
        points.append((lat, lon, 12.0, 70, ts))
    make_track(empty_db, mmsi=1001, points=points)

    df = extract_transits(empty_db)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["chokepoint_id"] == "Suez Canal"
    assert row["ship_type"] == "container"  # type 70 → cargo → container bin
    assert row["transit_minutes"] == pytest.approx(7 * 30, abs=1)  # 8 sightings × 30 min - first sighting
    assert row["entry_sog_kn"] == 12.0
    assert row["bbox_diagonal_km"] == BBOX_DIAGONAL_KM["Suez Canal"]


def test_extract_transits_anchored_filtered(empty_db, make_track, t0):
    """Vessel with entry SoG = 0.3 kn must be dropped (anchored)."""
    points = [
        (28.0, 33.0, 0.3, 70, t0),
        (29.5, 33.0, 0.4, 70, t0 + 1800),
        (31.0, 33.0, 0.2, 70, t0 + 3600),
        (32.5, 33.0, 0.5, 70, t0 + 5400),
    ]
    make_track(empty_db, mmsi=2002, points=points)
    df = extract_transits(empty_db)
    assert len(df) == 0


def test_extract_transits_gap_split(empty_db, make_track, t0):
    """A 90-minute gap inside the bbox must split one MMSI into two runs.

    Both runs must independently satisfy the distance floor (≥150 km for
    Suez). We craft two well-separated sub-tracks: one covering the south
    half of the bbox, then a 90-min gap, then a north half.
    """
    # First run: south half (28.0 → 30.0°N), then gap, then north half (31.0 → 32.5°N)
    points_south = [
        (28.0, 33.0, 12.0, 70, t0 + i * 1200) for i in range(5)
    ]
    points_north = [
        (31.0, 33.0, 12.0, 70, t0 + 5 * 1200 + 90 * 60 + i * 1200)
        for i in range(5)
    ]
    # Pad south run distance: spread south run more
    points_south = [
        (28.0 + i * 0.5, 33.0, 12.0, 70, t0 + i * 1200) for i in range(5)
    ]
    points_north = [
        (31.0 + i * 0.4, 33.0, 12.0, 70, t0 + 5 * 1200 + 90 * 60 + i * 1200)
        for i in range(5)
    ]
    make_track(empty_db, mmsi=3003, points=points_south + points_north)

    df = extract_transits(empty_db)
    # We expect each run that survives the distance floor to be a separate row.
    # Each run covers ~2° latitude ≈ 220 km > 150 km floor.
    assert len(df) == 2


def test_extract_transits_distance_floor(empty_db, make_track, t0):
    """A vessel that dips into the bbox and exits in nearly the same spot must drop."""
    # 10 sightings in a tight cluster (~10 km area) inside Suez bbox
    points = [
        (28.0 + i * 0.005, 33.0, 12.0, 70, t0 + i * 600)
        for i in range(10)
    ]
    make_track(empty_db, mmsi=4004, points=points)
    df = extract_transits(empty_db)
    # Distance covered ~= 5 km << 150 km Suez floor → dropped
    assert len(df) == 0


def test_extract_transits_too_short_duration(empty_db, make_track, t0):
    """Two sightings 2 minutes apart cannot be a valid transit."""
    points = [
        (28.0, 33.0, 12.0, 70, t0),
        (32.5, 33.0, 12.0, 70, t0 + 120),
    ]
    make_track(empty_db, mmsi=5005, points=points)
    df = extract_transits(empty_db)
    assert len(df) == 0  # duration < MIN_DURATION_MIN (5 min)


def test_extract_transits_outside_bbox_ignored(empty_db, make_track, t0):
    """A vessel never inside any chokepoint bbox produces no rows."""
    points = [(0.0, 0.0, 12.0, 70, t0 + i * 1800) for i in range(5)]
    make_track(empty_db, mmsi=6006, points=points)
    df = extract_transits(empty_db)
    assert len(df) == 0


def test_extract_transits_filters_non_commercial(empty_db, make_track, t0):
    """commercial_only=True drops fishing/pleasure/military rows; default keeps NULL ship_type."""
    # Cargo (ship_type=70) — commercial, should appear in both modes.
    cargo_pts = [(28.0 + i * 0.4, 33.0, 12.0, 70, t0 + i * 1800) for i in range(8)]
    make_track(empty_db, mmsi=1001, points=cargo_pts)

    # Fishing vessel (ship_type=30) — must drop in commercial-only mode.
    fishing_pts = [(28.0 + i * 0.4, 33.05, 12.0, 30, t0 + 100_000 + i * 1800) for i in range(8)]
    make_track(empty_db, mmsi=1002, points=fishing_pts)

    # Pleasure craft (ship_type=37) — also dropped.
    pleasure_pts = [(28.0 + i * 0.4, 33.1, 12.0, 37, t0 + 200_000 + i * 1800) for i in range(8)]
    make_track(empty_db, mmsi=1003, points=pleasure_pts)

    # NULL ship_type — kept in commercial mode (likely cargo, type-5 not arrived).
    nulltype_pts = [(28.0 + i * 0.4, 33.15, 12.0, None, t0 + 300_000 + i * 1800) for i in range(8)]
    make_track(empty_db, mmsi=1004, points=nulltype_pts)

    all_df = extract_transits(empty_db, commercial_only=False)
    commercial_df = extract_transits(empty_db, commercial_only=True)

    assert len(all_df) == 4, f"unfiltered should keep all 4 vessels, got {len(all_df)}"
    assert set(commercial_df["ship_type"]) == {"container", "unknown"}, (
        f"commercial-only should keep cargo + unknown, got {sorted(commercial_df['ship_type'].unique())}"
    )
    assert len(commercial_df) == 2


def test_extract_transits_legacy_db_without_sog(tmp_path):
    """An older sightings schema (no sog_kn / ship_type) must not crash extract_transits."""
    import sqlite3
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE sightings (mmsi INTEGER, lat REAL, lon REAL, ts REAL)"
        )
        con.executemany(
            "INSERT INTO sightings VALUES (?,?,?,?)",
            [(1, 28.0, 33.0, 1.7e9 + i * 1800) for i in range(5)],
        )
    df = extract_transits(db)
    # Should run without error; rows may all be filtered (no sog → fails entry_sog floor).
    assert isinstance(df, pd.DataFrame)


# ---------------------------------------------------------------------------
# build_feature_matrix
# ---------------------------------------------------------------------------

def _sample_training_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"chokepoint_id": "Suez Canal", "ship_type": "container",
         "entry_sog_kn": 11.0, "queue_depth": 10, "hour_of_day": 12,
         "day_of_week": 2, "month": 5, "recent_throughput_24h": 30,
         "bbox_diagonal_km": 700.0, "transit_minutes": 840.0,
         "entry_ts": 1_704_067_200.0},
        {"chokepoint_id": "Strait of Hormuz", "ship_type": "tanker",
         "entry_sog_kn": 12.0, "queue_depth": 8, "hour_of_day": 8,
         "day_of_week": 4, "month": 7, "recent_throughput_24h": 25,
         "bbox_diagonal_km": 500.0, "transit_minutes": 240.0,
         "entry_ts": 1_704_153_600.0},
    ])


def test_build_feature_matrix_shape():
    df = _sample_training_df()
    X, y, encoder, names = build_feature_matrix(df)
    # 2 rows × (one-hot for chokepoint + ship_type + 7 numeric)
    assert X.shape[0] == 2
    assert y.shape == (2,)
    assert len(names) == X.shape[1]


def test_build_feature_matrix_encoder_round_trip():
    """The encoder fit on training data must transform an unseen inference row
    to a vector with the same column count, with handle_unknown='ignore'."""
    df = _sample_training_df()
    _, _, encoder, _ = build_feature_matrix(df)
    row = encode_inference_row(
        {"chokepoint_id": "Suez Canal", "ship_type": "container",
         "entry_sog_kn": 11, "queue_depth": 10, "hour_of_day": 12,
         "day_of_week": 2, "month": 5, "recent_throughput_24h": 30,
         "bbox_diagonal_km": 700.0},
        encoder,
    )
    assert row.shape[0] == 1
    # Same number of columns as the original X
    X, _, _, _ = build_feature_matrix(df)
    assert row.shape[1] == X.shape[1]


def test_build_feature_matrix_unseen_category_zero_block():
    """A chokepoint not seen at fit time must produce a zero block in the
    one-hot region (handle_unknown='ignore')."""
    df = _sample_training_df()
    _, _, encoder, _ = build_feature_matrix(df)
    row = encode_inference_row(
        {"chokepoint_id": "Atlantis Strait", "ship_type": "container",
         "entry_sog_kn": 11, "queue_depth": 10, "hour_of_day": 12,
         "day_of_week": 2, "month": 5, "recent_throughput_24h": 30,
         "bbox_diagonal_km": 700.0},
        encoder,
    )
    # Get the one-hot column count from the encoder
    cat_n = sum(len(c) for c in encoder.categories_)
    # All categorical columns should be 0 for an unseen chokepoint AND unseen ship_type — but
    # ship_type 'container' was seen, so only chokepoint columns should be all zero.
    cp_n = len(encoder.categories_[0])
    assert row[0, :cp_n].sum() == 0  # chokepoint block all zero


# ---------------------------------------------------------------------------
# ship_type_bin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    (None,  "unknown"),
    (70,    "container"),
    (75,    "container"),
    (79,    "container"),
    (80,    "tanker"),
    (85,    "tanker"),
    (89,    "tanker"),
    (30,    "other"),  # fishing
    (60,    "other"),  # passenger
    (99,    "other"),
    ("nope", "unknown"),
])
def test_ship_type_bin_aliases(code, expected):
    assert ship_type_bin(code) == expected


def test_ship_type_bin_nan():
    assert ship_type_bin(float("nan")) == "unknown"


# ---------------------------------------------------------------------------
# predict_transit_minutes — three confidence paths
# ---------------------------------------------------------------------------

def test_predict_heuristic_when_no_artifact():
    """When load_artifact returns None, prediction must use the heuristic."""
    with patch("eta_model.load_artifact", return_value=None):
        # Clear the lru_cache so the patch takes effect.
        from eta_model import load_artifact as la
        la.cache_clear() if hasattr(la, "cache_clear") else None
        p = predict_transit_minutes("Suez Canal", {"queue_depth": 10})
    assert p["confidence"] == "heuristic"
    assert p["n_train"] == 0
    # Should be in the right ballpark
    assert HEURISTIC_MEAN_MIN["Suez Canal"] * 0.5 < p["p50"] < HEURISTIC_MEAN_MIN["Suez Canal"] * 1.5


def test_predict_unseen_chokepoint_falls_back_to_heuristic():
    """An unseen chokepoint must trigger the unseen_chokepoint fallback even
    when the model artifact is loaded."""
    p = predict_transit_minutes("Bermuda Triangle", {"queue_depth": 5})
    assert p["confidence"] in ("unseen_chokepoint", "heuristic")
    assert p["p50"] > 0
    assert p["p10"] <= p["p50"] <= p["p90"]


def test_predict_returns_populated_dict_on_garbage_input():
    """Even with mostly-empty features, prediction should return a valid dict."""
    p = predict_transit_minutes("Suez Canal", {})
    assert isinstance(p, dict)
    assert all(k in p for k in ("p10", "p50", "p90", "n_train", "confidence"))
    assert p["p10"] > 0


# ---------------------------------------------------------------------------
# predict_total_for_route — confidence cascade
# ---------------------------------------------------------------------------

def test_predict_total_for_route_empty():
    t = predict_total_for_route([])
    assert t == {"p10": 0, "p50": 0, "p90": 0, "n_train": 0, "confidence": "model"}


def test_predict_total_for_route_aggregates_minutes():
    chokepoints = ["Suez Canal", "Bab el-Mandeb"]
    t = predict_total_for_route(
        chokepoints,
        default_features={"queue_depth": 10, "ship_type": "container", "entry_sog_kn": 12,
                           "hour_of_day": 12, "day_of_week": 2, "month": 5,
                           "recent_throughput_24h": 30},
    )
    # Sum is greater than each individual contribution
    suez = predict_transit_minutes("Suez Canal", {"queue_depth": 10, "ship_type": "container",
                                                   "entry_sog_kn": 12, "hour_of_day": 12,
                                                   "day_of_week": 2, "month": 5,
                                                   "recent_throughput_24h": 30})
    bab = predict_transit_minutes("Bab el-Mandeb", {"queue_depth": 10, "ship_type": "container",
                                                     "entry_sog_kn": 12, "hour_of_day": 12,
                                                     "day_of_week": 2, "month": 5,
                                                     "recent_throughput_24h": 30})
    assert t["p50"] == suez["p50"] + bab["p50"]


def test_predict_total_for_route_confidence_cascade_unseen_dominates():
    """If any chokepoint is unseen, the route confidence must reflect the worst."""
    t = predict_total_for_route(
        ["Suez Canal", "Bermuda Triangle"],
        default_features={"queue_depth": 10},
    )
    # If artifact loaded, Suez is "model" and Bermuda is "unseen_chokepoint" → overall unseen
    # If artifact missing, both are "heuristic" → overall heuristic
    assert t["confidence"] in ("unseen_chokepoint", "heuristic")


# ---------------------------------------------------------------------------
# explain_prediction — humanised SHAP labels
# ---------------------------------------------------------------------------

def test_explain_prediction_returns_humanised_labels():
    """The SHAP rows must use plain-English labels and never `?` when the
    caller passes a complete feature row. Regression test for the bug where
    `_eta_features_per_chokepoint()` was dropping `chokepoint_id` and
    `bbox_diagonal_km`, so every chokepoint card's "Why this prediction?"
    expander showed `(?)`."""
    from eta_model import explain_prediction

    feats = {
        "chokepoint_id": "Suez Canal",
        "ship_type": "bulker",
        "entry_sog_kn": 14.0,
        "queue_depth": 12,
        "hour_of_day": 10,
        "day_of_week": 2,
        "month": 5,
        "recent_throughput_24h": 30,
        "bbox_diagonal_km": BBOX_DIAGONAL_KM["Suez Canal"],
    }
    rows = explain_prediction(feats, top_k=6)
    if not rows:
        # No artifact or shap unavailable — nothing to assert.
        pytest.skip("Model artifact or shap library unavailable in this environment")

    labels = [label for label, _ in rows]
    # Every label is a non-empty string with no `?` placeholder for the value.
    assert all(isinstance(lab, str) and lab for lab in labels)
    assert not any("(?)" in lab for lab in labels)
    # No raw feature-name prefixes leak through (e.g. "ship_type_tanker").
    assert not any(lab.startswith("ship_type_") for lab in labels)
    assert not any(lab.startswith("chokepoint_id_") for lab in labels)
    # Plain-English labels are present.
    assert any(lab.startswith("Chokepoint (") for lab in labels)
    assert any(lab.startswith("Chokepoint size (") for lab in labels)
    # bbox value is rendered with "km across".
    assert any("km across" in lab for lab in labels)
