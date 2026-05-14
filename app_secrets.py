# =============================================================================
# app_secrets.py — WHERE WE LOAD API KEYS FROM (safely, not from git)
# =============================================================================
# This file's whole purpose is to read our API keys (NewsAPI key, FRED
# key, Guardian key, OpenWeather key, AISStream token) at app startup
# WITHOUT having those secrets hardcoded into a file that gets
# committed to git. We use python-dotenv to read a local .env file
# (which is in .gitignore) on import. Other modules then import the
# constants from here. If a key is missing we return None instead of
# crashing — the API client functions check for None and just skip
# that source with a warning, so the dashboard still loads with
# whatever sources DO have keys.
# =============================================================================

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
# Load project-local .env without overriding values already supplied by the host.
load_dotenv(_ROOT / ".env", override=False)


def _get(name: str, default: str | None = None) -> str | None:
    # Treat common placeholder strings as missing secrets so callers can degrade
    # cleanly instead of sending invalid credentials to external APIs.
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
    # Use only where the caller cannot fall back to cached/sample data.
    if not value:
        raise RuntimeError(
            f"Missing required env var {name}. Add it to .env (see .env.example)."
        )
    return value
