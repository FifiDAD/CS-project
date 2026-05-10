"""Generate a deterministic synthetic dataset of chokepoint transits.

Each row simulates one vessel clearing one chokepoint. Per-chokepoint
mean transit times are calibrated to public references (canal authority
disclosures, Marine Traffic averages, IMO chokepoint reports). Queue
depth and ship type modulate the mean; Gaussian noise gives realistic
spread without overfitting to any one source.

Usage:
    python scripts/seed_eta.py

Writes data/eta_seed_transits.csv (~1500 rows).
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent.parent / "data" / "eta_seed_transits.csv"

# Per-chokepoint baseline: (mean_minutes, sigma_minutes, queue_sensitivity_min_per_vessel)
# Mean is the typical transit time at moderate queue depth (~10 vessels).
# queue_sensitivity is extra minutes added per additional waiting vessel.
CHOKEPOINTS: dict[str, tuple[float, float, float]] = {
    "Suez Canal":        (840.0,  90.0, 22.0),  # ~14h ± 1.5h
    "Panama Canal":      (540.0,  75.0, 28.0),  # ~9h ± 1.25h
    "Strait of Hormuz":  (240.0,  45.0,  4.0),  # ~4h ± 0.75h
    "Bab el-Mandeb":     (180.0,  30.0,  3.0),  # ~3h ± 0.5h
    "Strait of Malacca": (480.0,  60.0,  6.0),  # ~8h ± 1h
    "Singapore Strait":  (480.0,  55.0,  7.0),  # ~8h ± 0.9h
    "Bosphorus":         (135.0,  25.0,  3.5),  # ~2.25h ± 0.4h
    "Taiwan Strait":     (660.0,  90.0,  5.0),  # ~11h ± 1.5h
    "English Channel":   (420.0,  55.0,  4.0),  # ~7h ± 0.9h
}

# bbox diagonal in km (rough estimate for use as a constant feature)
BBOX_DIAG_KM: dict[str, float] = {
    "Suez Canal":        700.0,
    "Panama Canal":      400.0,
    "Strait of Hormuz":  500.0,
    "Bab el-Mandeb":     650.0,
    "Strait of Malacca": 650.0,
    "Singapore Strait":  150.0,
    "Bosphorus":         180.0,
    "Taiwan Strait":     550.0,
    "English Channel":   400.0,
}

SHIP_TYPES = ["tanker", "bulker", "container", "other", "unknown"]
# Multipliers: tankers/bulkers slower, containers faster.
SHIP_TYPE_MULT = {
    "tanker":    1.10,
    "bulker":    1.08,
    "container": 0.95,
    "other":     1.00,
    "unknown":   1.02,
}

ROWS_PER_CHOKEPOINT = 170  # → ~1530 total rows
RNG_SEED = 42


def _generate() -> list[dict]:
    rng = np.random.default_rng(RNG_SEED)
    rows: list[dict] = []
    # Synthesise rows over a 90-day window so the trainer's time-based
    # split has meaningful older vs newer partitions.
    base_ts = 1_704_067_200.0  # 2024-01-01 UTC
    window_sec = 90 * 86400

    for cp, (mean_m, sigma_m, q_sens) in CHOKEPOINTS.items():
        diag = BBOX_DIAG_KM[cp]
        for _ in range(ROWS_PER_CHOKEPOINT):
            entry_ts = base_ts + rng.uniform(0, window_sec)
            queue = max(0, int(rng.normal(loc=10, scale=4)))
            entry_sog = float(np.clip(rng.normal(loc=11.0, scale=2.5), 4.0, 22.0))
            ship_type = rng.choice(SHIP_TYPES, p=[0.20, 0.18, 0.30, 0.18, 0.14])
            mult = SHIP_TYPE_MULT[ship_type]

            # Mean for this row: baseline × type × queue penalty + noise.
            row_mean = mean_m * mult + q_sens * (queue - 10)
            transit = float(np.clip(rng.normal(loc=row_mean, scale=sigma_m), 5.0, 4320.0))

            # recent_throughput_24h roughly tracks queue with slack.
            recent = max(0, int(queue * rng.uniform(2.5, 4.5) + rng.normal(0, 5)))

            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
            rows.append({
                "chokepoint_id":        cp,
                "ship_type":            ship_type,
                "entry_sog_kn":         round(entry_sog, 2),
                "queue_depth":          queue,
                "hour_of_day":          dt.hour,
                "day_of_week":          dt.weekday(),
                "month":                dt.month,
                "recent_throughput_24h": recent,
                "bbox_diagonal_km":     diag,
                "transit_minutes":      round(transit, 1),
                "entry_ts":             round(entry_ts, 1),
                "_synthetic":           True,
            })
    return rows


def main() -> None:
    rows = _generate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} synthetic transits to {OUT.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    main()
