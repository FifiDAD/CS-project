"""AISStream.io WebSocket consumer.

Spawns a single background thread per process. Subscribes to bounding boxes
around the major chokepoints + critical ports, persists the latest position
per MMSI to a SQLite file, and exposes `latest_positions()` for Streamlit.

Streamlit reruns import this module repeatedly — `start_consumer()` is
idempotent (only the first call actually opens the WebSocket).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path

import pandas as pd

try:
    import websockets
except ImportError:
    websockets = None

from api_config import AISSTREAM_WS_URL
from app_secrets import AISSTREAM_KEY
from port_baselines import bounding_boxes as _port_boxes

_DB_PATH = Path(__file__).resolve().parent / ".ais_positions.db"

# Per-port AIS bounding boxes (auto-derived from port_baselines anchorage radii)
# plus the strategic chokepoints. Keys match STRAIT_COORDINATES in api_config.
CHOKEPOINT_BBOXES: dict[str, list[float]] = {
    # [lat_min, lon_min, lat_max, lon_max]
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
_CHOKEPOINT_BOXES: list[list[float]] = list(CHOKEPOINT_BBOXES.values())

WATCH_BOXES: list[list[float]] = _CHOKEPOINT_BOXES + _port_boxes()

_started = False
_lock = threading.Lock()


def _init_db() -> None:
    with sqlite3.connect(_DB_PATH) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS positions (
                mmsi      INTEGER PRIMARY KEY,
                lat       REAL,
                lon       REAL,
                sog_kn    REAL,
                cog_deg   REAL,
                name      TEXT,
                ship_type INTEGER,
                ts        REAL
            )"""
        )
        # Append-only history of (mmsi, ts) sightings — fuels transit counts
        # and 7-day baselines without needing PortWatch. 1 row per AIS message.
        con.execute(
            """CREATE TABLE IF NOT EXISTS sightings (
                mmsi INTEGER,
                lat  REAL,
                lon  REAL,
                ts   REAL
            )"""
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_sightings_ts ON sightings(ts)")


def _upsert(con: sqlite3.Connection, msg: dict) -> None:
    meta = msg.get("MetaData", {}) or {}
    pos_msg = (msg.get("Message", {}) or {}).get("PositionReport", {}) or {}
    mmsi = meta.get("MMSI") or pos_msg.get("UserID")
    lat = pos_msg.get("Latitude")
    lon = pos_msg.get("Longitude")
    if not (mmsi and lat is not None and lon is not None):
        return
    now = time.time()
    con.execute(
        """INSERT INTO positions (mmsi, lat, lon, sog_kn, cog_deg, name, ship_type, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(mmsi) DO UPDATE SET
              lat=excluded.lat, lon=excluded.lon,
              sog_kn=excluded.sog_kn, cog_deg=excluded.cog_deg,
              name=excluded.name, ts=excluded.ts""",
        (
            mmsi, lat, lon,
            pos_msg.get("Sog"), pos_msg.get("Cog"),
            (meta.get("ShipName") or "").strip(),
            pos_msg.get("ShipType"),
            now,
        ),
    )
    con.execute(
        "INSERT INTO sightings (mmsi, lat, lon, ts) VALUES (?,?,?,?)",
        (mmsi, lat, lon, now),
    )


async def _run() -> None:
    if not (websockets and AISSTREAM_KEY):
        return
    _init_db()
    # AISStream expects each box as [[lat_min, lon_min], [lat_max, lon_max]]
    boxes_pairs = [[[b[0], b[1]], [b[2], b[3]]] for b in WATCH_BOXES]
    sub = json.dumps({
        "APIKey": AISSTREAM_KEY,
        "BoundingBoxes": boxes_pairs,
        "FilterMessageTypes": ["PositionReport"],
    })
    while True:
        try:
            async with websockets.connect(AISSTREAM_WS_URL, ping_interval=30) as ws:
                await ws.send(sub)
                with sqlite3.connect(_DB_PATH) as con:
                    async for raw in ws:
                        try:
                            _upsert(con, json.loads(raw))
                            con.commit()
                        except (json.JSONDecodeError, sqlite3.Error):
                            continue
        except Exception:  # noqa: BLE001  network flakiness; reconnect
            await asyncio.sleep(5)


def start_consumer() -> bool:
    """Spawn the background WS thread once per process. Returns True if running."""
    global _started
    if not (websockets and AISSTREAM_KEY):
        return False
    with _lock:
        if _started:
            return True
        _started = True
    threading.Thread(target=lambda: asyncio.run(_run()), daemon=True).start()
    return True


def latest_positions(max_age_sec: int = 600) -> pd.DataFrame:
    """Return positions seen within the last `max_age_sec` seconds."""
    if not _DB_PATH.exists():
        return pd.DataFrame()
    cutoff = time.time() - max_age_sec
    try:
        with sqlite3.connect(_DB_PATH) as con:
            return pd.read_sql_query(
                "SELECT mmsi, lat, lon, sog_kn, cog_deg, name, ship_type, ts "
                "FROM positions WHERE ts > ?",
                con,
                params=(cutoff,),
            )
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


def transits_24h(bbox: list[float]) -> int:
    """Count distinct vessels (MMSIs) sighted inside `bbox` in the last 24h.

    bbox = [lat_min, lon_min, lat_max, lon_max].
    Returns 0 if the DB doesn't exist yet (consumer hasn't received messages).
    """
    if not _DB_PATH.exists() or not bbox or len(bbox) != 4:
        return 0
    cutoff = time.time() - 86400
    lat_min, lon_min, lat_max, lon_max = bbox
    try:
        with sqlite3.connect(_DB_PATH) as con:
            row = con.execute(
                """SELECT COUNT(DISTINCT mmsi) FROM sightings
                   WHERE ts > ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?""",
                (cutoff, lat_min, lat_max, lon_min, lon_max),
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def last_sighting_age_sec() -> float | None:
    """Seconds since the freshest row in `sightings`, or None if empty/missing.

    Powers the AIS pipeline panel's "last sighting" indicator. The websocket
    consumer can stall silently — this is the single signal that tells the UI
    whether the stream is actually live.
    """
    if not _DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(_DB_PATH) as con:
            row = con.execute("SELECT MAX(ts) FROM sightings").fetchone()
    except sqlite3.Error:
        return None
    if not row or row[0] is None:
        return None
    return max(0.0, time.time() - float(row[0]))


def total_distinct_vessels(window_sec: int = 86400) -> int:
    """Distinct MMSI count seen across all watched bboxes in `window_sec`."""
    if not _DB_PATH.exists():
        return 0
    cutoff = time.time() - max(0, int(window_sec))
    try:
        with sqlite3.connect(_DB_PATH) as con:
            row = con.execute(
                "SELECT COUNT(DISTINCT mmsi) FROM sightings WHERE ts > ?",
                (cutoff,),
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def live_queue_snapshot(bbox: list[float], window_sec: int = 300) -> int:
    """Distinct MMSI inside `bbox` over the last `window_sec` seconds.

    bbox = [lat_min, lon_min, lat_max, lon_max]. Mirrors the queue-depth
    feature the trainer extracts at vessel entry time, so per-card live
    predictions see in-distribution values.
    """
    if not _DB_PATH.exists() or not bbox or len(bbox) != 4:
        return 0
    cutoff = time.time() - max(0, int(window_sec))
    lat_min, lon_min, lat_max, lon_max = bbox
    try:
        with sqlite3.connect(_DB_PATH) as con:
            row = con.execute(
                """SELECT COUNT(DISTINCT mmsi) FROM sightings
                   WHERE ts > ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?""",
                (cutoff, lat_min, lat_max, lon_min, lon_max),
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def transits_baseline(bbox: list[float], days: int = 7) -> float | None:
    """Median daily distinct-MMSI count over the last `days` days inside `bbox`.

    Returns None until ≥3 days of history exist — comparing 24h transits to a
    1-day baseline produces noise, so the caller skips the AIS term in that case.
    """
    if not _DB_PATH.exists() or not bbox or len(bbox) != 4:
        return None
    now = time.time()
    cutoff = now - days * 86400
    lat_min, lon_min, lat_max, lon_max = bbox
    try:
        with sqlite3.connect(_DB_PATH) as con:
            # Group sightings into 24h buckets and count distinct MMSIs in each.
            rows = con.execute(
                """SELECT CAST((? - ts) / 86400 AS INTEGER) AS day,
                          COUNT(DISTINCT mmsi) AS n
                   FROM sightings
                   WHERE ts > ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                   GROUP BY day
                   HAVING day < ?""",
                (now, cutoff, lat_min, lat_max, lon_min, lon_max, days),
            ).fetchall()
    except sqlite3.Error:
        return None
    if len(rows) < 3:
        return None
    counts = sorted(r[1] for r in rows)
    mid = len(counts) // 2
    return float(counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2)
