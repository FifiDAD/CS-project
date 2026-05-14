# =============================================================================
# disk_cache.py — A SIMPLE ON-DISK RESULT CACHE
# =============================================================================
# Streamlit's built-in @st.cache_data only lives in memory: as soon as
# the Streamlit process is killed (e.g. we restart the server), every
# cached value is gone and the next page load has to re-fetch from the
# internet from scratch.
#
# This little helper adds a SECOND, persistent cache layer that survives
# restarts. It saves successful function results to small pickle files
# under a temp directory, keyed by a hash of the function name + cache
# tag + a TTL. If the function is called again within the TTL window —
# even from a fresh Streamlit process — we return the pickle instead of
# re-running the slow function.
#
# Used by app.py for load_core_data and the heaviest dynamic_status
# computations so a "streamlit run" restart doesn't blow away ~10s of
# warm-up time.
#
# Safety: any pickle / IO error silently falls back to calling the
# wrapped function. Worst case = "no speedup". The page never breaks
# because of a cache miss or corrupted cache file.
# =============================================================================
from __future__ import annotations

import hashlib
import pickle
import time
from pathlib import Path
from typing import Any, Callable

_CACHE_DIR = Path(__file__).resolve().parent / ".cache"


def _safe_key(key: str) -> str:
    # Hash so arbitrary keys (including large JSON blobs) become safe filenames.
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def disk_cached(key: str, ttl: float, fn: Callable[..., Any], *args, **kwargs) -> Any:
    """Return fn(*args, **kwargs), caching its result on disk for `ttl` seconds.

    Identical return values to calling `fn` directly. Falls back to the
    live call on any cache miss or error.
    """
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _CACHE_DIR / f"{_safe_key(key)}.pkl"
        if path.exists() and (time.time() - path.stat().st_mtime) < ttl:
            try:
                with path.open("rb") as fp:
                    return pickle.load(fp)
            except Exception:  # noqa: BLE001  corrupt pickle → recompute
                pass
    except Exception:  # noqa: BLE001  fs failure → just compute
        pass

    result = fn(*args, **kwargs)

    try:
        path = _CACHE_DIR / f"{_safe_key(key)}.pkl"
        tmp = path.with_suffix(".pkl.tmp")
        with tmp.open("wb") as fp:
            pickle.dump(result, fp, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
    except Exception:  # noqa: BLE001  caching is best-effort
        pass

    return result
