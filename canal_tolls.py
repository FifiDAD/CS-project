"""Canal toll lookup tables.

Suez and Panama tolls vary by vessel class, transit direction, and laden
status. Real published rates are buried in PDFs (SCNT for Suez, PC/UMS for
Panama) and updated yearly. The numbers below are *representative* 2024–2025
rates in USD per transit, rounded to the nearest $1k. Good enough for a
route comparison; flag in the UI as "indicative — call agent for booking".

If you wire in a real toll API later (Leth Agencies / Inchcape), replace
`estimate_toll_usd()` here.
"""

from __future__ import annotations

# Approximate per-transit cost in USD by vessel class, laden.
# Sources: SCNT 2024 circular, ACP 2025 toll schedule, brokers' rule of thumb.
SUEZ_TOLLS_USD = {
    "Panamax":   450_000,   # ~70k DWT bulk
    "Capesize":  750_000,   # ~180k DWT bulk
    "VLCC":     1_100_000,  # ~300k DWT crude
    "ULCV":     1_400_000,  # 24k+ TEU container
    "Handysize": 250_000,
}

PANAMA_TOLLS_USD = {
    "Panamax":   350_000,
    "Capesize":  None,       # Capesize bulkers don't fit Neopanamax locks reliably
    "VLCC":      None,       # VLCC > Neopanamax beam (49m); cannot transit
    "ULCV":     1_000_000,
    "Handysize": 180_000,
}


def estimate_toll_usd(canal: str, vessel_class: str) -> int | None:
    """Return indicative toll in USD, or None if vessel cannot transit canal."""
    table = {"suez": SUEZ_TOLLS_USD, "panama": PANAMA_TOLLS_USD}.get(canal.lower())
    if not table:
        return 0
    return table.get(vessel_class)


def can_transit(canal: str, vessel_class: str) -> bool:
    return estimate_toll_usd(canal, vessel_class) is not None
