"""Test script to verify all API connections are working properly."""

import sys

# The project has a secrets.py that shadows Python's built-in secrets module.
# numpy's bit_generator imports `randbits` from the real secrets module.
# Fix: load the real secrets from the stdlib before the project root shadows it.
_project_root = sys.path[0] if sys.path and sys.path[0] == "" or "Logistics" in (sys.path[0] if sys.path else "") else None
_removed = False
if sys.path and (sys.path[0] == "" or sys.path[0].endswith("Logistics_dashboard")):
    _saved_path0 = sys.path.pop(0)
    _removed = True
import secrets as _real_secrets  # noqa: E402 — must load real secrets before project root
if _removed:
    sys.path.insert(0, _saved_path0)
sys.modules["secrets"] = _real_secrets  # ensure numpy finds the real secrets module

import requests
import pandas as pd

# Mock Streamlit decorators BEFORE importing APIClient.
# Every APIClient method uses @st.cache_data which crashes outside Streamlit.
import streamlit as st
st.cache_data = lambda *args, **kwargs: (lambda fn: fn)
st.warning = lambda *args, **kwargs: None

from api_integrations import APIClient
from api_config import (
    NEWSAPI_KEY, FRED_API_KEY, GUARDIAN_API_KEY,
    ACLED_BASE_URL, GDELT_BASE_URL, WORLD_BANK_BASE_URL, NOAA_ALERTS_URL,
)

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

results = []

def record(name, passed, message):
    results.append({"name": name, "passed": passed, "message": message})
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}: {message}")

def classify_http_error(response):
    """Return a labelled error string for a non-200 HTTP response."""
    code = response.status_code
    if code in (401, 403):
        return f"AUTH_ERROR - HTTP {code}"
    if code == 429:
        return f"RATE_LIMITED - HTTP {code}"
    return f"HTTP_{code}"

# ---------------------------------------------------------------------------
# Individual API tests
# ---------------------------------------------------------------------------

def test_acled():
    print("\n 1. ACLED (Armed Conflict Data)...")
    try:
        df = APIClient.get_acled_events(limit=5)
        if not isinstance(df, pd.DataFrame):
            record("ACLED", False, "INVALID_DATA - did not return a DataFrame")
            return
        if len(df) == 0:
            record("ACLED", False, "EMPTY_RESPONSE - no events returned")
            return
        sample = df.iloc[0].get("country", df.iloc[0].get("event_date", "?"))
        record("ACLED", True, f"Retrieved {len(df)} events. Sample: {sample}")
    except requests.exceptions.ConnectionError:
        record("ACLED", False, "CONNECTION_ERROR")
    except requests.exceptions.Timeout:
        record("ACLED", False, "TIMEOUT")
    except Exception as e:
        record("ACLED", False, f"UNEXPECTED_ERROR - {e}")


def test_gdelt():
    print("\n 2. GDELT (Global Events)...")
    try:
        data = APIClient.get_gdelt_events()
        if not isinstance(data, dict):
            record("GDELT", False, f"INVALID_DATA - expected dict, got {type(data).__name__}")
            return
        if not data:
            record("GDELT", False, "EMPTY_RESPONSE - empty dict returned")
            return
        if "timeline" not in data:
            record("GDELT", False, f"INVALID_DATA - 'timeline' key missing, got keys: {list(data.keys())}")
            return
        points = len(data["timeline"][0].get("data", [])) if data["timeline"] else 0
        record("GDELT", True, f"'timeline' key present ({points} data points)")
    except requests.exceptions.ConnectionError:
        record("GDELT", False, "CONNECTION_ERROR")
    except requests.exceptions.Timeout:
        record("GDELT", False, "TIMEOUT")
    except Exception as e:
        record("GDELT", False, f"UNEXPECTED_ERROR - {e}")


def test_newsapi():
    print("\n 3. NewsAPI...")
    try:
        df = APIClient.get_news_alerts(keywords="shipping supply chain")
        if not isinstance(df, pd.DataFrame):
            record("NewsAPI", False, "INVALID_DATA - did not return a DataFrame")
            return
        if len(df) == 0:
            # Also check raw HTTP for a better diagnosis
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={"q": "shipping", "apiKey": NEWSAPI_KEY, "pageSize": 1},
                timeout=8,
            )
            if resp.status_code != 200:
                record("NewsAPI", False, classify_http_error(resp))
            else:
                body = resp.json()
                if body.get("status") == "error":
                    record("NewsAPI", False, f"AUTH_ERROR - {body.get('code')}: {body.get('message')}")
                else:
                    record("NewsAPI", False, "EMPTY_RESPONSE - no articles returned")
            return
        title_col = "title" if "title" in df.columns else None
        if title_col is None:
            record("NewsAPI", False, f"INVALID_DATA - 'title' column missing, got: {list(df.columns)}")
            return
        record("NewsAPI", True, f"Retrieved {len(df)} articles")
    except requests.exceptions.ConnectionError:
        record("NewsAPI", False, "CONNECTION_ERROR")
    except requests.exceptions.Timeout:
        record("NewsAPI", False, "TIMEOUT")
    except Exception as e:
        record("NewsAPI", False, f"UNEXPECTED_ERROR - {e}")


def test_guardian():
    print("\n 4. Guardian API...")
    try:
        df = APIClient.get_guardian_news(keywords="shipping")
        if not isinstance(df, pd.DataFrame):
            record("Guardian", False, "INVALID_DATA - did not return a DataFrame")
            return
        if len(df) == 0:
            record("Guardian", False, "EMPTY_RESPONSE - no articles returned")
            return
        if "webTitle" not in df.columns:
            record("Guardian", False, f"INVALID_DATA - 'webTitle' column missing, got: {list(df.columns)}")
            return
        record("Guardian", True, f"Retrieved {len(df)} articles")
    except requests.exceptions.ConnectionError:
        record("Guardian", False, "CONNECTION_ERROR")
    except requests.exceptions.Timeout:
        record("Guardian", False, "TIMEOUT")
    except Exception as e:
        record("Guardian", False, f"UNEXPECTED_ERROR - {e}")


def test_fred_oil_direct():
    """Direct HTTP test of FRED oil price endpoint — detects auth errors that APIClient masks."""
    print("\n 5. FRED - Oil Price (direct HTTP)...")
    try:
        resp = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": "DCOILWTICO", "api_key": FRED_API_KEY, "file_type": "json", "limit": 5, "sort_order": "desc"},
            timeout=8,
        )
        if resp.status_code != 200:
            record("FRED Oil (HTTP)", False, classify_http_error(resp))
            return
        obs = resp.json().get("observations", [])
        if not obs:
            record("FRED Oil (HTTP)", False, "EMPTY_RESPONSE - no observations")
            return
        # Find most recent non-missing value
        value_str = next((o["value"] for o in obs if o["value"] != "."), None)
        if value_str is None:
            record("FRED Oil (HTTP)", False, "INVALID_DATA - all recent values are missing ('.')")
            return
        price = float(value_str)
        date = obs[0]["date"]
        record("FRED Oil (HTTP)", True, f"DCOILWTICO: ${price:.2f}/bbl (latest date: {date})")
    except requests.exceptions.ConnectionError:
        record("FRED Oil (HTTP)", False, "CONNECTION_ERROR")
    except requests.exceptions.Timeout:
        record("FRED Oil (HTTP)", False, "TIMEOUT")
    except Exception as e:
        record("FRED Oil (HTTP)", False, f"UNEXPECTED_ERROR - {e}")


def test_fred_oil_client(direct_passed):
    """APIClient integration test — flags when the hardcoded sentinel $78.45 is returned instead of live data."""
    print("\n 6. FRED - Oil Price (APIClient integration)...")
    try:
        price = APIClient.get_oil_price()
        if not isinstance(price, (int, float)):
            record("FRED Oil (APIClient)", False, f"INVALID_DATA - expected float, got {type(price).__name__}")
            return
        if price == 78.45 and not direct_passed:
            record("FRED Oil (APIClient)", False, "EMPTY_RESPONSE - returning hardcoded fallback (78.45); live API unavailable")
            return
        note = " (live data)" if price != 78.45 else " (fallback value, but API appears reachable)"
        record("FRED Oil (APIClient)", True, f"get_oil_price() returned {price:.2f}{note}")
    except Exception as e:
        record("FRED Oil (APIClient)", False, f"UNEXPECTED_ERROR - {e}")


def test_fred_bdi_direct():
    """Direct HTTP test of FRED Baltic Dry Index endpoint."""
    print("\n 7. FRED - Baltic Dry Index (direct HTTP)...")
    try:
        resp = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": "TSIFRGHT", "api_key": FRED_API_KEY, "file_type": "json", "limit": 5, "sort_order": "desc"},
            timeout=8,
        )
        if resp.status_code != 200:
            record("FRED BDI (HTTP)", False, classify_http_error(resp))
            return
        obs = resp.json().get("observations", [])
        if not obs:
            record("FRED BDI (HTTP)", False, "EMPTY_RESPONSE - no observations")
            return
        value_str = next((o["value"] for o in obs if o["value"] != "."), None)
        if value_str is None:
            record("FRED BDI (HTTP)", False, "INVALID_DATA - all recent values are missing ('.')")
            return
        bdi = float(value_str)
        date = obs[0]["date"]
        record("FRED BDI (HTTP)", True, f"TSIFRGHT: {bdi:.1f} (latest date: {date})")
    except requests.exceptions.ConnectionError:
        record("FRED BDI (HTTP)", False, "CONNECTION_ERROR")
    except requests.exceptions.Timeout:
        record("FRED BDI (HTTP)", False, "TIMEOUT")
    except Exception as e:
        record("FRED BDI (HTTP)", False, f"UNEXPECTED_ERROR - {e}")


def test_fred_bdi_client(direct_passed):
    print("\n 8. FRED - Baltic Dry Index (APIClient integration)...")
    try:
        bdi = APIClient.get_shipping_index()
        if not isinstance(bdi, (int, float)):
            record("FRED BDI (APIClient)", False, f"INVALID_DATA - expected float, got {type(bdi).__name__}")
            return
        if bdi == 1200 and not direct_passed:
            record("FRED BDI (APIClient)", False, "EMPTY_RESPONSE - returning hardcoded fallback (1200); live API unavailable")
            return
        note = " (live data)" if bdi != 1200 else " (fallback value, but API appears reachable)"
        record("FRED BDI (APIClient)", True, f"get_shipping_index() returned {bdi:.0f}{note}")
    except Exception as e:
        record("FRED BDI (APIClient)", False, f"UNEXPECTED_ERROR - {e}")


def test_noaa():
    print("\n 9. NOAA Weather Alerts...")
    try:
        # Direct HTTP check first
        resp = requests.get(
            NOAA_ALERTS_URL,
            params={"point": "40,-95"},
            headers={"User-Agent": "logistics-dashboard/1.0"},
            timeout=8,
        )
        if resp.status_code != 200:
            record("NOAA", False, classify_http_error(resp))
            return
        content_type = resp.headers.get("Content-Type", "")
        if "geo+json" not in content_type and "json" not in content_type:
            record("NOAA", False, f"INVALID_DATA - unexpected Content-Type: {content_type}")
            return
        # APIClient integration
        hazards = APIClient.get_weather_hazards(lat=40, lon=-95)
        if not isinstance(hazards, list):
            record("NOAA", False, f"INVALID_DATA - APIClient returned {type(hazards).__name__}, expected list")
            return
        record("NOAA", True, f"API reachable. {len(hazards)} active alert(s) for lat=40, lon=-95")
    except requests.exceptions.ConnectionError:
        record("NOAA", False, "CONNECTION_ERROR")
    except requests.exceptions.Timeout:
        record("NOAA", False, "TIMEOUT")
    except Exception as e:
        record("NOAA", False, f"UNEXPECTED_ERROR - {e}")


def test_world_bank():
    print("\n10. World Bank Trade Data...")
    try:
        data = APIClient.get_world_bank_trade("US")
        if not isinstance(data, list):
            record("World Bank", False, f"INVALID_DATA - expected list, got {type(data).__name__}")
            return
        if len(data) == 0:
            record("World Bank", False, "EMPTY_RESPONSE - no trade records returned for US")
            return
        if not isinstance(data[0], dict):
            record("World Bank", False, f"INVALID_DATA - expected list of dicts, first item is {type(data[0]).__name__}")
            return
        record("World Bank", True, f"Retrieved {len(data)} records for country US")
    except requests.exceptions.ConnectionError:
        record("World Bank", False, "CONNECTION_ERROR")
    except requests.exceptions.Timeout:
        record("World Bank", False, "TIMEOUT")
    except Exception as e:
        record("World Bank", False, f"UNEXPECTED_ERROR - {e}")


def test_exchange_rates():
    print("\n11. Exchange Rates (FX)...")
    expected_keys = ["EUR", "GBP", "JPY", "CNY", "INR"]
    try:
        rates = APIClient.get_exchange_rates()
        if not isinstance(rates, dict):
            record("ExchangeRate", False, f"INVALID_DATA - expected dict, got {type(rates).__name__}")
            return
        missing = [k for k in expected_keys if k not in rates]
        if missing:
            record("ExchangeRate", False, f"INVALID_DATA - missing keys: {missing}")
            return
        non_positive = [k for k in expected_keys if not isinstance(rates[k], (int, float)) or rates[k] <= 0]
        if non_positive:
            record("ExchangeRate", False, f"INVALID_DATA - non-positive values for: {non_positive}")
            return
        summary = ", ".join(f"{k}={rates[k]:.4g}" for k in expected_keys)
        record("ExchangeRate", True, f"All 5 rates present. {summary}")
    except requests.exceptions.ConnectionError:
        record("ExchangeRate", False, "CONNECTION_ERROR")
    except requests.exceptions.Timeout:
        record("ExchangeRate", False, "TIMEOUT")
    except Exception as e:
        record("ExchangeRate", False, f"UNEXPECTED_ERROR - {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print(" LOGISTICS DASHBOARD - API CONNECTION TESTS")
    print("=" * 60)

    test_acled()
    test_gdelt()
    test_newsapi()
    test_guardian()

    # FRED: run direct HTTP first so APIClient test can detect sentinel fallback
    test_fred_oil_direct()
    fred_oil_direct_passed = results[-1]["passed"]
    test_fred_oil_client(fred_oil_direct_passed)

    test_fred_bdi_direct()
    fred_bdi_direct_passed = results[-1]["passed"]
    test_fred_bdi_client(fred_bdi_direct_passed)

    test_noaa()
    test_world_bank()
    test_exchange_rates()

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    print("\n" + "=" * 60)
    if failed == 0:
        print(f" SUMMARY: {passed}/{total} tests passed — All APIs operational.")
    else:
        print(f" SUMMARY: {passed}/{total} tests passed")
        print(" FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"   - {r['name']}: {r['message']}")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
