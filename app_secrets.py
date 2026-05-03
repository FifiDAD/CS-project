"""Central secrets loader.

Loads .env at import time. All API keys/credentials are read here so that
api_config.py and api_integrations.py can stay free of hardcoded secrets.

Missing keys are returned as None — callers must handle that gracefully
(skip the API and log a warning) rather than silently using stale defaults.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env", override=False)


def _get(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value in ("", "YOUR_KEY_HERE", "YOUR_NEWSAPI_KEY_HERE"):
        return None
    return value


# Keyed APIs
NEWSAPI_KEY      = _get("NEWSAPI_KEY")
FRED_API_KEY     = _get("FRED_API_KEY")
OPENWEATHER_KEY  = _get("OPENWEATHER_KEY")
GUARDIAN_API_KEY = _get("GUARDIAN_API_KEY")

# AISStream.io WebSocket
AISSTREAM_KEY = _get("AISSTREAM_KEY")

# Groq LLM (used for news dedup + threat classification)
GROQ_API_KEY = _get("GROQ_API_KEY")


def require(name: str, value: str | None) -> str:
    """Raise if a required secret is missing — for code paths that cannot degrade."""
    if not value:
        raise RuntimeError(
            f"Missing required env var {name}. Add it to .env (see .env.example)."
        )
    return value
