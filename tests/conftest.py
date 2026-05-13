"""Pytest fixtures for the ETA Predictor test suite.

Builds a temporary SQLite file with a controllable `sightings` table so
extract_transits can be exercised against synthetic vessel tracks
without touching the live `.ais_positions.db`.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

# Make the project root importable so tests can `from eta_model import ...`
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """A SQLite file with the sightings schema but no rows."""
    # Each test gets its own temporary AIS database.
    db = tmp_path / "test_ais.db"
    with sqlite3.connect(db) as con:
        con.execute(
            """CREATE TABLE sightings (
                mmsi      INTEGER,
                lat       REAL,
                lon       REAL,
                sog_kn    REAL,
                ship_type INTEGER,
                ts        REAL
            )"""
        )
    return db


@pytest.fixture
def make_track(empty_db):
    """Factory that appends a synthetic track for one MMSI to the DB.

    Usage:
        make_track(empty_db, mmsi=12345, points=[
            (lat, lon, sog_kn, ship_type, ts), ...
        ])
    """
    # Return a helper that inserts one synthetic vessel track.
    def _make(
        db: Path,
        mmsi: int,
        points: list[tuple[float, float, float | None, int | None, float]],
    ) -> None:
        with sqlite3.connect(db) as con:
            con.executemany(
                "INSERT INTO sightings (mmsi, lat, lon, sog_kn, ship_type, ts) VALUES (?,?,?,?,?,?)",
                [(mmsi, lat, lon, sog, st, ts) for (lat, lon, sog, st, ts) in points],
            )
    return _make


@pytest.fixture
def t0() -> float:
    """A stable reference timestamp the tests can build offsets from."""
    return 1_704_067_200.0  # 2024-01-01 UTC


# Suez bbox coords pulled from eta_model.CHOKEPOINT_BBOXES — used by tests
# to construct points known to be inside / outside the bbox.
SUEZ_BBOX = (27.0, 31.0, 33.0, 35.0)  # (lat_min, lon_min, lat_max, lon_max)


@pytest.fixture(autouse=True)
def _isolate_prediction_log(tmp_path_factory, monkeypatch):
    """Redirect eta_model's prediction-log DB to a tmp path for every test.

    Why: predict_transit_minutes() now writes one row per call to
    .ais_positions.db. Without this fixture, the existing tests would
    silently populate the live DB on every run.
    """
    import eta_model
    tmp_db = tmp_path_factory.mktemp("eta_log") / "eta_log.db"
    # Point prediction logging at a temp DB instead of the live app DB.
    monkeypatch.setattr(eta_model, "_DB_PATH", tmp_db)
    monkeypatch.setattr(eta_model, "_PREDICTIONS_TABLE_READY", False)
    yield tmp_db
