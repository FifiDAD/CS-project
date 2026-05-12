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
import subprocess
import sys
import threading
import time
from pathlib import Path

import eta_model

_HERE = Path(__file__).resolve().parent
_TRAINER_SCRIPT = _HERE / "train_eta_model.py"
_META_PATH = _HERE / "models" / "eta_meta.json"

CHECK_INTERVAL_SEC = 24 * 3600  # daily wake-up
RETRAIN_COOLDOWN_SEC = 24 * 3600  # don't retrain more than once a day
N_MIN_REAL = 200  # mirrors train_eta_model.N_MIN_TOTAL — must be enough real rows

_started = False
_lock = threading.Lock()
_log = logging.getLogger("eta_scheduler")


def _last_trained_at() -> float:
    """Return UNIX timestamp of last successful training (0.0 if missing)."""
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


def retrain_now(use_seed_fallback: bool = True) -> tuple[bool, str]:
    """Invoke the trainer in a subprocess. Returns (success, message).

    Runs train_eta_model.py with --no-cv for fast subprocess turn-around (CV
    is the slow part; the calibration/ SHAP /metrics still write). If
    `use_seed_fallback=True` and there aren't enough real rows yet, the
    --seed flag is added so the trainer succeeds.
    """
    # Close out any open predictions first so the dashboard's live MAE
    # picks up the most recent transits, and so any future training
    # extension that pulls from eta_predictions sees up-to-date labels.
    try:
        from eta_quality import match_open_predictions
        match_open_predictions()
    except Exception as exc:  # noqa: BLE001  matcher failure must not block retrain
        _log.warning("eta_scheduler: pre-retrain match failed: %s", exc)

    args = [sys.executable, str(_TRAINER_SCRIPT), "--no-cv"]
    if use_seed_fallback:
        args.append("--seed")
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


def _scheduler_loop() -> None:
    """Daemon thread body — sleeps CHECK_INTERVAL_SEC between checks."""
    while True:
        try:
            status = next_retrain_eta()
            if status["enough_data"] and status["cooldown_elapsed"]:
                _log.info("eta_scheduler: triggering retrain (real_rows=%s)", status["real_rows"])
                ok, msg = retrain_now(use_seed_fallback=False)
                _log.info("eta_scheduler: retrain finished — ok=%s msg=%s", ok, msg)
            else:
                _log.debug(
                    "eta_scheduler: skipping (real_rows=%s, cooldown_elapsed=%s)",
                    status["real_rows"], status["cooldown_elapsed"],
                )
        except Exception as exc:  # noqa: BLE001  must never kill the daemon thread
            _log.warning("eta_scheduler: tick failed: %s", exc)
        time.sleep(CHECK_INTERVAL_SEC)


def start_eta_scheduler() -> bool:
    """Spawn the scheduler thread once per process. Returns True if running."""
    global _started
    with _lock:
        if _started:
            return True
        _started = True
    threading.Thread(target=_scheduler_loop, daemon=True, name="eta_scheduler").start()
    return True
