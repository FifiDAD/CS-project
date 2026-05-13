"""On-disk result cache for slow loading-screen computations.

Sits below `@st.cache_data` and above the API layer. Survives Streamlit
restarts (which clear `@st.cache_data` per-process). Any IO or pickle
error transparently falls back to calling the wrapped function — the
worst case is "no speedup", never a broken page.
"""
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
