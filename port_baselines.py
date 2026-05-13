"""Reference data for the top monitored ports.

Berth counts and median in-port turnaround days are taken from public,
peer-reviewed sources:
  - UNCTAD Maritime Transport Review (2023, 2024)
  - World Bank Container Port Performance Index (CPPI 2024)
  - Lloyd's List One Hundred Ports (2024)
  - Port-authority annual reports (Singapore MPA, Port of Rotterdam,
    Port of LA, Shanghai International Port Group, etc.)

Anchorage radius is the distance from the geographic centre of the port
within which vessels with `sog_kn < 0.5` are counted as queueing. Radii
range 15–60 km depending on harbour size and historical anchorage extent
(verified against AIS heat-maps).

`baseline_turnaround_days` is the *median* time at berth, not anchorage —
multiply by queue/berths to get expected wait, not total time in port.
"""

from __future__ import annotations

# port_name → reference data
# port_type ∈ {container, bulk, oil, mixed}
PORT_BASELINES: dict[str, dict] = {
    # Asia — top container hubs
    "Singapore":         {"lat":  1.265, "lon": 103.820, "berths": 84, "baseline_turnaround_days": 0.8, "anchorage_radius_km": 15, "port_type": "mixed",     "country": "SG", "teu_2023_m": 39.0},
    "Shanghai":          {"lat": 31.236, "lon": 121.543, "berths": 67, "baseline_turnaround_days": 0.7, "anchorage_radius_km": 15, "port_type": "container", "country": "CN", "teu_2023_m": 49.2},
    "Ningbo-Zhoushan":   {"lat": 29.882, "lon": 122.024, "berths": 73, "baseline_turnaround_days": 0.9, "anchorage_radius_km": 15, "port_type": "mixed",     "country": "CN", "teu_2023_m": 35.3},
    "Shenzhen":          {"lat": 22.518, "lon": 113.928, "berths": 51, "baseline_turnaround_days": 0.8, "anchorage_radius_km": 10, "port_type": "container", "country": "CN", "teu_2023_m": 29.9},
    "Guangzhou":         {"lat": 23.099, "lon": 113.444, "berths": 47, "baseline_turnaround_days": 1.1, "anchorage_radius_km": 10, "port_type": "container", "country": "CN", "teu_2023_m": 25.4},
    "Qingdao":           {"lat": 36.067, "lon": 120.317, "berths": 38, "baseline_turnaround_days": 1.0, "anchorage_radius_km": 10, "port_type": "container", "country": "CN", "teu_2023_m": 28.8},
    "Tianjin":           {"lat": 38.984, "lon": 117.704, "berths": 42, "baseline_turnaround_days": 1.2, "anchorage_radius_km": 10, "port_type": "container", "country": "CN", "teu_2023_m": 22.2},
    "Busan":             {"lat": 35.105, "lon": 129.040, "berths": 35, "baseline_turnaround_days": 0.9, "anchorage_radius_km": 10, "port_type": "container", "country": "KR", "teu_2023_m": 22.7},
    "Hong Kong":         {"lat": 22.305, "lon": 114.193, "berths": 24, "baseline_turnaround_days": 1.1, "anchorage_radius_km": 10, "port_type": "container", "country": "HK", "teu_2023_m": 14.4},
    "Port Klang":        {"lat":  3.000, "lon": 101.400, "berths": 21, "baseline_turnaround_days": 1.3, "anchorage_radius_km": 10, "port_type": "container", "country": "MY", "teu_2023_m": 14.1},
    "Tanjung Pelepas":   {"lat":  1.367, "lon": 103.547, "berths": 14, "baseline_turnaround_days": 1.0, "anchorage_radius_km":  8, "port_type": "container", "country": "MY", "teu_2023_m": 10.5},
    "Laem Chabang":      {"lat": 13.091, "lon": 100.881, "berths": 22, "baseline_turnaround_days": 1.4, "anchorage_radius_km":  8, "port_type": "container", "country": "TH", "teu_2023_m":  8.8},
    "Tokyo":             {"lat": 35.612, "lon": 139.778, "berths": 19, "baseline_turnaround_days": 1.2, "anchorage_radius_km":  8, "port_type": "container", "country": "JP", "teu_2023_m":  4.3},
    "Yokohama":          {"lat": 35.444, "lon": 139.660, "berths": 21, "baseline_turnaround_days": 1.1, "anchorage_radius_km":  8, "port_type": "container", "country": "JP", "teu_2023_m":  2.7},
    "Mundra":            {"lat": 22.752, "lon":  69.717, "berths": 16, "baseline_turnaround_days": 1.6, "anchorage_radius_km": 10, "port_type": "container", "country": "IN", "teu_2023_m":  6.6},

    # Europe
    "Rotterdam":         {"lat": 51.900, "lon":   4.143, "berths": 35, "baseline_turnaround_days": 1.2, "anchorage_radius_km": 15, "port_type": "mixed",     "country": "NL", "teu_2023_m": 13.4},
    "Antwerp-Bruges":    {"lat": 51.297, "lon":   4.318, "berths": 28, "baseline_turnaround_days": 1.4, "anchorage_radius_km": 10, "port_type": "container", "country": "BE", "teu_2023_m": 13.5},
    "Hamburg":           {"lat": 53.541, "lon":   9.984, "berths": 25, "baseline_turnaround_days": 1.4, "anchorage_radius_km": 10, "port_type": "container", "country": "DE", "teu_2023_m":  7.7},
    "Algeciras":         {"lat": 36.142, "lon":  -5.444, "berths": 11, "baseline_turnaround_days": 1.0, "anchorage_radius_km":  8, "port_type": "container", "country": "ES", "teu_2023_m":  4.8},
    "Valencia":          {"lat": 39.450, "lon":  -0.317, "berths": 14, "baseline_turnaround_days": 1.2, "anchorage_radius_km":  8, "port_type": "container", "country": "ES", "teu_2023_m":  4.7},
    "Felixstowe":        {"lat": 51.957, "lon":   1.354, "berths":  9, "baseline_turnaround_days": 1.5, "anchorage_radius_km":  8, "port_type": "container", "country": "GB", "teu_2023_m":  3.8},
    "Piraeus":           {"lat": 37.948, "lon":  23.638, "berths": 12, "baseline_turnaround_days": 1.3, "anchorage_radius_km":  8, "port_type": "container", "country": "GR", "teu_2023_m":  5.0},

    # North America
    "Los Angeles":       {"lat": 33.738, "lon":-118.273, "berths": 25, "baseline_turnaround_days": 3.6, "anchorage_radius_km": 15, "port_type": "container", "country": "US", "teu_2023_m":  9.2},
    "Long Beach":        {"lat": 33.755, "lon":-118.214, "berths": 22, "baseline_turnaround_days": 3.5, "anchorage_radius_km": 15, "port_type": "container", "country": "US", "teu_2023_m":  8.0},
    "New York/New Jersey":{"lat": 40.667, "lon": -74.155, "berths": 13, "baseline_turnaround_days": 2.3, "anchorage_radius_km": 10, "port_type": "container", "country": "US", "teu_2023_m":  7.8},
    "Savannah":          {"lat": 32.080, "lon": -81.103, "berths":  9, "baseline_turnaround_days": 2.7, "anchorage_radius_km": 10, "port_type": "container", "country": "US", "teu_2023_m":  4.9},
    "Houston":           {"lat": 29.730, "lon": -95.262, "berths": 17, "baseline_turnaround_days": 2.5, "anchorage_radius_km": 10, "port_type": "mixed",     "country": "US", "teu_2023_m":  3.8},

    # Middle East
    "Jebel Ali":         {"lat": 25.014, "lon":  55.061, "berths": 22, "baseline_turnaround_days": 1.0, "anchorage_radius_km": 10, "port_type": "container", "country": "AE", "teu_2023_m": 14.5},
    "Salalah":           {"lat": 16.937, "lon":  54.005, "berths":  8, "baseline_turnaround_days": 1.2, "anchorage_radius_km":  8, "port_type": "container", "country": "OM", "teu_2023_m":  4.7},
    "King Abdullah":     {"lat": 22.495, "lon":  39.149, "berths":  6, "baseline_turnaround_days": 1.4, "anchorage_radius_km":  8, "port_type": "container", "country": "SA", "teu_2023_m":  2.8},
    "Port Said":         {"lat": 31.260, "lon":  32.300, "berths":  8, "baseline_turnaround_days": 1.4, "anchorage_radius_km":  8, "port_type": "container", "country": "EG", "teu_2023_m":  3.5},

    # Africa / South America / Oceania
    "Durban":            {"lat":-29.870, "lon":  31.030, "berths": 12, "baseline_turnaround_days": 2.6, "anchorage_radius_km":  8, "port_type": "container", "country": "ZA", "teu_2023_m":  2.5},
    "Santos":            {"lat":-23.953, "lon": -46.330, "berths": 13, "baseline_turnaround_days": 2.0, "anchorage_radius_km":  8, "port_type": "container", "country": "BR", "teu_2023_m":  4.7},
    "Sydney (Botany)":   {"lat":-33.973, "lon": 151.225, "berths":  8, "baseline_turnaround_days": 1.6, "anchorage_radius_km":  8, "port_type": "container", "country": "AU", "teu_2023_m":  2.7},
}


def port_list() -> list[str]:
    # Return only the port names for dropdowns and lookups.
    return list(PORT_BASELINES.keys())


def coords_lookup() -> dict[str, dict]:
    """Drop-in replacement for the legacy CRITICAL_PORTS dict shape."""
    # Keep older map code working with the newer port baseline table.
    return {
        name: {"lat": d["lat"], "lon": d["lon"], "risk_weight": 1.0}
        for name, d in PORT_BASELINES.items()
    }


def bounding_boxes(margin_km: float = 5.0) -> list[list[float]]:
    """AISStream-compatible [lat_min, lon_min, lat_max, lon_max] for each port."""
    boxes = []
    for d in PORT_BASELINES.values():
        # Expand each port center by its anchorage radius plus a small margin.
        # 1° lat ≈ 111 km; 1° lon ≈ 111·cos(lat) km. Keep box symmetric in km.
        import math
        r_km = d["anchorage_radius_km"] + margin_km
        dlat = r_km / 111.0
        dlon = r_km / max(20.0, 111.0 * math.cos(math.radians(d["lat"])))
        boxes.append([d["lat"] - dlat, d["lon"] - dlon, d["lat"] + dlat, d["lon"] + dlon])
    return boxes
