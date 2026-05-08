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
    """Persist an incoming AIS message into SQLite.

    Two message types are accepted:

    - **PositionReport** (Type 1/2/3): carries lat/lon/sog/cog and a name.
      Does NOT carry ship type — that field doesn't exist on these
      messages, so we never try to read it here.
    - **ShipStaticData** (Type 5): carries the ITU-R ship type code (and
      a more authoritative name). Does NOT carry position data, so we
      only update `ship_type` and `name` for the existing row, leaving
      lat/lon/sog/cog/ts untouched.

    `ship_type` therefore populates gradually as Type 5 messages flow in
    (every ~6 min per vessel). Until then the column stays NULL and
    downstream code treats unknown vessels as commercial-by-default.
    """
    body = msg.get("Message", {}) or {}
    meta = msg.get("MetaData", {}) or {}

    pos_msg = body.get("PositionReport") or {}
    static_msg = body.get("ShipStaticData") or {}

    if pos_msg:
        mmsi = meta.get("MMSI") or pos_msg.get("UserID")
        lat = pos_msg.get("Latitude")
        lon = pos_msg.get("Longitude")
        if not (mmsi and lat is not None and lon is not None):
            return
        now = time.time()
        con.execute(
            """INSERT INTO positions (mmsi, lat, lon, sog_kn, cog_deg, name, ship_type, ts)
               VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
               ON CONFLICT(mmsi) DO UPDATE SET
                  lat=excluded.lat, lon=excluded.lon,
                  sog_kn=excluded.sog_kn, cog_deg=excluded.cog_deg,
                  name=excluded.name, ts=excluded.ts""",
            (
                mmsi, lat, lon,
                pos_msg.get("Sog"), pos_msg.get("Cog"),
                (meta.get("ShipName") or "").strip(),
                now,
            ),
        )
        con.execute(
            "INSERT INTO sightings (mmsi, lat, lon, ts) VALUES (?,?,?,?)",
            (mmsi, lat, lon, now),
        )
        return

    if static_msg:
        mmsi = meta.get("MMSI") or static_msg.get("UserID")
        ship_type = static_msg.get("Type")
        if not mmsi or ship_type is None:
            return
        name = (static_msg.get("Name") or meta.get("ShipName") or "").strip()
        # Static-only update: never touch position fields here. If the row
        # doesn't exist yet (no PositionReport seen), insert a placeholder
        # so the next PositionReport simply updates lat/lon/ts.
        con.execute(
            """INSERT INTO positions (mmsi, lat, lon, sog_kn, cog_deg, name, ship_type, ts)
               VALUES (?, NULL, NULL, NULL, NULL, ?, ?, 0)
               ON CONFLICT(mmsi) DO UPDATE SET
                  ship_type=excluded.ship_type,
                  name=CASE WHEN excluded.name != '' THEN excluded.name ELSE positions.name END""",
            (mmsi, name, ship_type),
        )
        return


async def _run() -> None:
    if not (websockets and AISSTREAM_KEY):
        return
    _init_db()
    # AISStream expects each box as [[lat_min, lon_min], [lat_max, lon_max]]
    boxes_pairs = [[[b[0], b[1]], [b[2], b[3]]] for b in WATCH_BOXES]
    sub = json.dumps({
        "APIKey": AISSTREAM_KEY,
        "BoundingBoxes": boxes_pairs,
        # Subscribe to PositionReport (lat/lon/sog/cog) AND ShipStaticData
        # (ship type code + canonical name). Without ShipStaticData,
        # `ship_type` is forever NULL — and the port-congestion metric
        # ends up counting every yacht/ferry/fishing boat as "queue".
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
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
