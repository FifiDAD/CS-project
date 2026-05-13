"""Background scheduler for the ETA Predictor.

Runs a daemon thread that wakes up every 24h and retrains the model
when (a) at least 24h have elapsed since the last training, AND (b) the
live AIS sightings table contains enough real transits to support a
retrain. Idempotent — `start_eta_scheduler()` only spawns the thread
the first time it is called per process.

Hook this from `app.py` alongside `start_consumer()` so the model
gradually phases over from synthetic seed to real data without manual
intervention.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import eta_model

_HERE = Path(__file__).resolve().parent
# Keep scheduler paths anchored to the project root so subprocess training
# works the same whether launched from Streamlit or the command line.
_TRAINER_SCRIPT = _HERE / "train_eta_model.py"
_META_PATH = _HERE / "models" / "eta_meta.json"

# Main scheduler tick — shadow predictions + matcher run on this cadence.
TICK_INTERVAL_SEC = 10 * 60   # 10 min
# Retrain check happens once per ~24h, not every tick.
RETRAIN_CHECK_INTERVAL_SEC = 24 * 3600
RETRAIN_COOLDOWN_SEC = 24 * 3600
N_MIN_REAL = 200  # mirrors train_eta_model.N_MIN_TOTAL — must be enough real rows

# Shadow-prediction tuning.
# An entry is "new" if the vessel had no in-bbox sighting in the prior 30 min.
SHADOW_ENTRY_GAP_SEC = 30 * 60
# Look for entries inside this trailing window each tick. Slightly bigger than
# the tick interval so we don't miss vessels straddling the boundary.
SHADOW_DETECT_WINDOW_SEC = 15 * 60
# Don't relog within this window for the same (mmsi, chokepoint).
SHADOW_DEDUP_SEC = 6 * 3600
# Drain anonymous (NULL-MMSI) router predictions after 1h. They can never match,
# so leaving them in flight just clutters the dashboard.
NULL_MMSI_DRAIN_H = 1
# Allow the matcher to look back this many seconds before predicted_at when
# pairing shadow predictions to realised entries (AIS sampling jitter).
MATCH_ENTRY_GRACE_SEC = 5 * 60

_started = False
_lock = threading.Lock()
# Module logger lets Streamlit keep running even when scheduler messages are noisy.
_log = logging.getLogger("eta_scheduler")


def _last_trained_at() -> float:
    """Return UNIX timestamp of last successful training (0.0 if missing)."""
    # Missing or unreadable metadata means "never trained" for cooldown purposes.
    if not _META_PATH.exists():
        return 0.0
    try:
        meta = json.loads(_META_PATH.read_text())
        return float(meta.get("trained_at", 0.0))
    except (json.JSONDecodeError, ValueError, KeyError):
        return 0.0


def _real_row_count() -> int:
    """Count commercial real-data transits currently extractable from AIS DB.

    Uses the same commercial-only filter as the trainer so the 200-row gate
    measures rows that will actually be used for training, not raw sightings.
    """
    try:
        from ais_consumer import _DB_PATH
    except Exception:  # noqa: BLE001
        return 0
    try:
        df = eta_model.extract_transits(_DB_PATH, commercial_only=True)
        return int(len(df))
    except Exception:  # noqa: BLE001
        return 0


def retrain_now(use_seed_fallback: bool = True, fast: bool = False) -> tuple[bool, str]:
    """Invoke the trainer in a subprocess. Returns (success, message).

    Runs train_eta_model.py with --no-cv for fast subprocess turn-around (CV
    is the slow part; the calibration/ SHAP /metrics still write). If
    `use_seed_fallback=True` and there aren't enough real rows yet, the
    --seed flag is added so the trainer succeeds.
    """
    # Close out any open predictions first so the dashboard's live MAE
    # picks up the most recent transits, and so any future training
    # extension that pulls from eta_predictions sees up-to-date labels.
    # Skipped in fast mode — the matcher does a per-prediction sqlite scan.
    if not fast:
        try:
            from eta_quality import match_open_predictions
            match_open_predictions()
        except Exception as exc:  # noqa: BLE001  matcher failure must not block retrain
            _log.warning("eta_scheduler: pre-retrain match failed: %s", exc)

    # Run the trainer out-of-process so model imports, native libraries, and
    # memory use cannot destabilize the Streamlit app process.
    args = [sys.executable, str(_TRAINER_SCRIPT), "--no-cv"]
    if use_seed_fallback:
        args.append("--seed")
    if fast:
        args.append("--fast")
    try:
        proc = subprocess.run(
            args,
            cwd=str(_HERE),
            capture_output=True,
            text=True,
            timeout=10 * 60,  # 10 min hard cap
        )
    except subprocess.TimeoutExpired:
        return False, "Trainer subprocess timed out after 10 minutes."
    except Exception as exc:  # noqa: BLE001
        return False, f"Trainer subprocess failed to launch: {exc}"

    if proc.returncode != 0:
        # Keep only the tail so UI/log messages stay readable after long trainer output.
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
        return False, "Trainer exited with code "\
                      f"{proc.returncode}. Tail: " + " | ".join(tail)

    # Bust caches — both module-level lru_cache and downstream callers.
    try:
        eta_model.load_artifact.cache_clear()
        eta_model._shap_explainer.cache_clear()
    except AttributeError:
        pass
    return True, f"Retrained successfully ({_real_row_count()} real rows in DB)."


def next_retrain_eta() -> dict:
    """Return a dict describing the time-to-next-retrain check (for the UI)."""
    # The UI uses this same status object to explain why an automatic retrain
    # will or will not happen at the next scheduler tick.
    last = _last_trained_at()
    real_n = _real_row_count()
    enough_data = real_n >= N_MIN_REAL
    cooldown_elapsed = (time.time() - last) >= RETRAIN_COOLDOWN_SEC
    will_retrain = enough_data and cooldown_elapsed
    seconds_until = max(0.0, RETRAIN_COOLDOWN_SEC - (time.time() - last)) if last else 0.0
    return {
        "last_trained_at": last,
        "real_rows": real_n,
        "enough_data": enough_data,
        "cooldown_elapsed": cooldown_elapsed,
        "will_retrain_at_next_check": will_retrain,
        "seconds_until_cooldown_clears": seconds_until,
    }


def _detect_new_entries(
    con: sqlite3.Connection,
    cp: str,
    bbox: list[float],
    detect_window_sec: float,
    entry_gap_sec: float,
) -> list[tuple[int, float]]:
    """Vessels whose first in-bbox sighting in `detect_window_sec` follows a
    ≥`entry_gap_sec` absence — i.e. "just entered" rather than "still here".

    Returns [(mmsi, first_sighting_ts), ...]. Empty list on any error.
    """
    now = time.time()
    window_start = now - detect_window_sec
    gap_start = window_start - entry_gap_sec
    lat_min, lon_min, lat_max, lon_max = bbox
    try:
        # All distinct MMSIs sighted in the bbox within the detect window.
        candidates = con.execute(
            """SELECT mmsi, MIN(ts)
               FROM sightings
               WHERE ts >= ?
                 AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
               GROUP BY mmsi""",
            (window_start, lat_min, lat_max, lon_min, lon_max),
        ).fetchall()
    except sqlite3.Error:
        return []
    out: list[tuple[int, float]] = []
    for mmsi, first_ts in candidates:
        if mmsi is None:
            continue
        # Was this vessel inside the bbox in the prior gap window? If yes,
        # it's a continuing transit, not a new entry.
        try:
            prior = con.execute(
                """SELECT 1 FROM sightings
                   WHERE mmsi = ? AND ts >= ? AND ts < ?
                     AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                   LIMIT 1""",
                (mmsi, gap_start, window_start, lat_min, lat_max, lon_min, lon_max),
            ).fetchone()
        except sqlite3.Error:
            continue
        if prior is None:
            out.append((int(mmsi), float(first_ts)))
    return out


def _has_recent_shadow(
    con: sqlite3.Connection, mmsi: int, cp: str, dedup_sec: float
) -> bool:
    """True if an open prediction for (mmsi, cp) was logged in the last `dedup_sec`."""
    cutoff = time.time() - dedup_sec
    try:
        row = con.execute(
            """SELECT 1 FROM eta_predictions
               WHERE mmsi = ? AND chokepoint_id = ? AND predicted_at >= ?
               LIMIT 1""",
            (mmsi, cp, cutoff),
        ).fetchone()
    except sqlite3.Error:
        return True  # fail safe — don't double-log on a sqlite hiccup
    return row is not None


def _shadow_predict_tick() -> dict:
    """Log shadow predictions for vessels just entering watched chokepoints.

    For each chokepoint, finds MMSIs whose first sighting in the trailing
    detect window was *after* a ≥30-min absence (real entries, not
    continuing transits). For each, builds the feature vector the trainer
    would have, calls `predict_transit_minutes(..., mmsi=mmsi, log=True)`,
    and lets the row land in `eta_predictions` with a concrete MMSI so the
    matcher can later close it out.

    Returns {logged, skipped_dedup, skipped_features, cp_counts}.
    """
    try:
        from ais_consumer import _DB_PATH, CHOKEPOINT_BBOXES, transits_24h, live_queue_snapshot
        from eta_model import predict_transit_minutes, ship_type_bin, BBOX_DIAGONAL_KM
    except Exception as exc:  # noqa: BLE001
        _log.warning("shadow_tick: imports unavailable: %s", exc)
        return {"logged": 0, "skipped_dedup": 0, "skipped_features": 0, "cp_counts": {}}

    if not _DB_PATH.exists():
        return {"logged": 0, "skipped_dedup": 0, "skipped_features": 0, "cp_counts": {}}

    logged = skipped_dedup = skipped_features = 0
    cp_counts: dict[str, int] = {}
    now_dt = datetime.now(timezone.utc)

    try:
        with sqlite3.connect(_DB_PATH, timeout=5.0) as con:
            for cp, bbox in CHOKEPOINT_BBOXES.items():
                entries = _detect_new_entries(
                    con, cp, bbox, SHADOW_DETECT_WINDOW_SEC, SHADOW_ENTRY_GAP_SEC
                )
                cp_logged = 0
                for mmsi, entry_ts in entries:
                    if _has_recent_shadow(con, mmsi, cp, SHADOW_DEDUP_SEC):
                        skipped_dedup += 1
                        continue
                    # Pull the vessel's current state from positions; bail if
                    # we can't construct a sane feature vector.
                    pos = con.execute(
                        "SELECT sog_kn, ship_type FROM positions WHERE mmsi = ?",
                        (mmsi,),
                    ).fetchone()
                    if pos is None:
                        skipped_features += 1
                        continue
                    sog_kn = float(pos[0]) if pos[0] is not None else 12.0
                    if sog_kn < 0.5:
                        # Anchored / drifting — don't predict transit for it.
                        skipped_features += 1
                        continue
                    feats = {
                        "chokepoint_id":         cp,
                        "ship_type":             ship_type_bin(pos[1]),
                        "entry_sog_kn":          sog_kn,
                        "queue_depth":           int(live_queue_snapshot(bbox, 300)) or 1,
                        "hour_of_day":           now_dt.hour,
                        "day_of_week":           now_dt.weekday(),
                        "month":                 now_dt.month,
                        "recent_throughput_24h": int(transits_24h(bbox)) or 1,
                        "bbox_diagonal_km":      float(BBOX_DIAGONAL_KM.get(cp, 300.0)),
                    }
                    try:
                        predict_transit_minutes(cp, feats, mmsi=mmsi, log=True)
                        logged += 1
                        cp_logged += 1
                    except Exception as exc:  # noqa: BLE001  one bad vessel must not abort the tick
                        _log.debug("shadow_tick: predict failed for %s/%s: %s", mmsi, cp, exc)
                        skipped_features += 1
                if cp_logged:
                    cp_counts[cp] = cp_logged
    except sqlite3.Error as exc:
        _log.warning("shadow_tick: sqlite error: %s", exc)

    return {
        "logged": logged,
        "skipped_dedup": skipped_dedup,
        "skipped_features": skipped_features,
        "cp_counts": cp_counts,
    }


def _scheduler_loop() -> None:
    """Daemon body — every TICK_INTERVAL_SEC runs the shadow tick + matcher,
    and once per RETRAIN_CHECK_INTERVAL_SEC checks whether to retrain.

    The shadow tick gives the matcher MMSI-attributed predictions to close
    against; the matcher converts those into rolling accuracy / drift signals
    on the ETA Quality page. The retrain check stays on its daily cadence.
    """
    last_retrain_check = 0.0
    while True:
        try:
            # 1) Shadow predictions for live vessels just entering chokepoints.
            shadow = _shadow_predict_tick()
            if shadow["logged"]:
                _log.info(
                    "eta_scheduler: shadow tick logged=%s skipped_dedup=%s skipped_features=%s cps=%s",
                    shadow["logged"], shadow["skipped_dedup"],
                    shadow["skipped_features"], shadow["cp_counts"],
                )

            # 2) Close out completed transits + drain anonymous router preds.
            try:
                from eta_quality import match_open_predictions
                counts = match_open_predictions(
                    null_mmsi_lookback_h=NULL_MMSI_DRAIN_H,
                    entry_grace_sec=MATCH_ENTRY_GRACE_SEC,
                )
                if counts["matched"] or counts["expired"]:
                    _log.info(
                        "eta_scheduler: matcher matched=%s expired=%s still_open=%s",
                        counts["matched"], counts["expired"], counts["still_open"],
                    )
            except Exception as exc:  # noqa: BLE001
                _log.warning("eta_scheduler: matcher tick failed: %s", exc)

            # 3) Retrain check — only fires once a day.
            now = time.monotonic()
            if now - last_retrain_check >= RETRAIN_CHECK_INTERVAL_SEC:
                last_retrain_check = now
                status = next_retrain_eta()
                if status["enough_data"] and status["cooldown_elapsed"]:
                    _log.info("eta_scheduler: triggering retrain (real_rows=%s)", status["real_rows"])
                    ok, msg = retrain_now(use_seed_fallback=False)
                    _log.info("eta_scheduler: retrain finished — ok=%s msg=%s", ok, msg)
                else:
                    _log.debug(
                        "eta_scheduler: retrain skipped (real_rows=%s, cooldown_elapsed=%s)",
                        status["real_rows"], status["cooldown_elapsed"],
                    )
        except Exception as exc:  # noqa: BLE001  must never kill the daemon thread
            _log.warning("eta_scheduler: tick failed: %s", exc)
        time.sleep(TICK_INTERVAL_SEC)


def start_eta_scheduler() -> bool:
    """Spawn the scheduler thread once per process. Returns True if running."""
    global _started
    # Guard against Streamlit reruns spawning duplicate daily scheduler threads.
    with _lock:
        if _started:
            return True
        _started = True
    threading.Thread(target=_scheduler_loop, daemon=True, name="eta_scheduler").start()
    return True
