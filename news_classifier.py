"""Groq-powered news classifier — clusters duplicates, scores severity,
and flags freshness so stale items stop dominating the feed.

Design:
- One batched chat-completion call per render. Cached 5 min keyed on input
  titles, so repeat reruns are free.
- Falls back to identity (no clustering, all fresh) if GROQ_API_KEY is
  missing or the API call fails — never blocks rendering.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Iterable

import requests
import streamlit as st

from app_secrets import GROQ_API_KEY

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"   # fast + free-tier friendly
_TIMEOUT = 12

_PROMPT = """You classify shipping/geopolitical news headlines for a maritime risk dashboard.

For each headline (referenced by its index), return a JSON array of objects:
- "i": the input index (integer)
- "cluster": short slug grouping near-duplicate stories about the same event
              (e.g. "houthi-red-sea-strike-2025-05-02"). Use the SAME slug
              for all headlines describing the same incident.
- "severity": 0.0..1.0 — how disruptive to global shipping (1.0 = strait
              closure / fleet-wide attack; 0.1 = minor advisory)
- "fresh":   true if the story is current/active news, false if it's a
              historical recap, anniversary piece, opinion, or unrelated.

Return ONLY the JSON array, no prose."""


def _cache_key(titles: list[str]) -> str:
    # Short hash used when the same title batch is classified again.
    h = hashlib.sha1("\n".join(titles).encode("utf-8", "ignore")).hexdigest()
    return h[:16]


@st.cache_data(ttl=300)
def classify_titles(titles: tuple[str, ...]) -> list[dict] | None:
    """Return classifications aligned by index, or None on failure.

    Tuple input so Streamlit can hash it.
    """
    if not GROQ_API_KEY or not titles:
        return None

    # Number titles so the model can return results in the same order.
    user_msg = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    body = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    try:
        # Ask Groq to classify all titles in one request.
        r = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.warning("Groq classify failed: %s", exc)
        return None

    # Groq's json_object mode returns an object; the array is usually under
    # a single key (we ask for an array but force json_object for stability).
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Groq returned non-JSON content")
        return None

    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        # Find the first array value — model often nests under "results"/"items"/etc.
        # This accepts small JSON shape differences from the model.
        items = next((v for v in parsed.values() if isinstance(v, list)), None)
        if items is None:
            return None
    else:
        return None

    # Build index → classification map; fill gaps with neutral defaults.
    out: list[dict] = [
        {"cluster": f"_solo_{i}", "severity": 0.3, "fresh": True}
        for i in range(len(titles))
    ]
    for entry in items:
        # Replace each default row with the model's answer when it is valid.
        if not isinstance(entry, dict):
            continue
        try:
            i = int(entry.get("i"))
        except (TypeError, ValueError):
            continue
        if not (0 <= i < len(titles)):
            continue
        out[i] = {
            "cluster":  str(entry.get("cluster") or f"_solo_{i}"),
            "severity": float(entry.get("severity") or 0.3),
            "fresh":    bool(entry.get("fresh", True)),
        }
    return out
