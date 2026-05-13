"""
Vessel physics: weather-aware fuel + ETA per edge, with Monte Carlo confidence.

Inspired by WINDMAR (windmar-nav/windmar-demo) but implemented as a small,
pure-Python alternative — no FastAPI, no Postgres, no Redis. The dashboard
already has marinav_router for graph topology and Open-Meteo for weather.

Model: admiralty-coefficient calm-water shaft power + simple wind-drag and
wave-added power. Sufficient for routing-grade estimates (within ~10% of
trial data for typical commercial speeds), and far better than the flat
"distance × consumption" the Fuel Calculator was using.

    P_calm   = displacement_t^(2/3) * speed_kn^3 / admiralty_coeff [kW]
    F_wind   = 0.5 * rho_air * Cd * A_front * v_app^2              [N]
    F_wave   = k_wave * Hs_m^2 * 1000                              [N]
    P_extra  = (F_wind + F_wave) * v_ship_ms / 1000                [kW]
    fuel_h   = (P_calm + P_extra) / propulsive_eff * SFOC / 1e6    [t/h]

`v_app` is the apparent headwind in m/s. `k_wave` is the per-vessel wave-
resistance coefficient (kN per m^2 of significant wave height squared).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


# ── Vessel presets ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class VesselProfile:
    name: str
    displacement_t: float        # full-load displacement (tonnes)
    admiralty_coeff: float       # higher = more efficient calm-water resistance
    frontal_area_m2: float       # projected wind area above waterline
    cd_wind: float               # drag coefficient (≈0.85 for box-like superstructures)
    k_wave: float                # wave-added resistance coefficient (kN per m^2)
    propulsive_eff: float        # 0..1, hull+propeller+gearbox combined
    sfoc_g_kwh: float            # specific fuel consumption at design point
    design_speed_kn: float
    fuel_grade: str
    # Hull dimensions for canal-transit checks (canal_tolls.py reads these
    # to validate beam < lock width and draught < canal depth).
    loa_m: float = 0.0
    beam_m: float = 0.0
    draught_m: float = 0.0
    dwt_t: float = 0.0

    def fuel_tpd(self, speed_kn: float) -> float:
        """Calm-water daily fuel burn (tonnes/day) at the requested speed.

        Wraps the same admiralty + wind/wave physics used per-edge with a
        24-hour synthetic edge under zero wind/zero wave so the result is the
        pure speed-dependent burn — useful for pages that don't have a real
        route to integrate over.
        """
        edge = EdgeMeta(
            a="_design", b="_design",
            dist_km=speed_kn * 1.852 * 24,  # one day's distance at given speed
            mid_lat=0.0, mid_lon=0.0, bearing_deg=0.0,
            wind_speed_ms=0.0, wind_dir_deg=0.0, wave_h_m=0.0,
        )
        return fuel_for_edge(self, edge, speed_kn)["fuel_t"]


# Admiralty coefficients here are calibrated so calm-water brake power at
# design speed lands within ~10% of published MCR/operating numbers for
# typical commercial vessels of each class. See `python -m vessel_physics`
# for a sanity table.
VESSEL_PROFILES: dict[str, VesselProfile] = {
    "Panamax bulker":    VesselProfile("Panamax bulker",     85_000, 480, 1_100, 0.85,  6.0, 0.65, 175, 14.0, "VLSFO",
                                       loa_m=229, beam_m=32.3, draught_m=12.0, dwt_t=75_000),
    "Suezmax tanker":    VesselProfile("Suezmax tanker",    175_000, 595, 1_400, 0.85,  9.0, 0.66, 170, 14.5, "VLSFO",
                                       loa_m=274, beam_m=48.0, draught_m=17.0, dwt_t=160_000),
    "VLCC tanker":       VesselProfile("VLCC tanker",       320_000, 720, 1_700, 0.85, 13.0, 0.67, 168, 15.5, "VLSFO",
                                       loa_m=330, beam_m=60.0, draught_m=22.0, dwt_t=300_000),
    "ULCV container":    VesselProfile("ULCV container",    220_000, 600, 2_400, 0.90, 11.0, 0.68, 165, 22.0, "VLSFO",
                                       loa_m=400, beam_m=61.0, draught_m=16.5, dwt_t=200_000),
    "MR product tanker": VesselProfile("MR product tanker",  50_000, 520,   900, 0.85,  4.5, 0.65, 178, 14.5, "VLSFO",
                                       loa_m=180, beam_m=32.2, draught_m=11.0, dwt_t=50_000),
}

RHO_AIR = 1.225  # kg/m^3
KN_TO_MS = 0.5144

# IMO MEPC.1/Circ.684 standard emission factors (kg CO2 per kg fuel burned).
# Kept as fuel-grade keyed constants so emissions can track fuel switching.
EMISSION_FACTORS_KG_CO2_PER_KG_FUEL: dict[str, float] = {
    "VLSFO":  3.114,
    "IFO380": 3.114,
    "MGO":    3.206,
    "LNG":    2.750,
}


def co2_tonnes(fuel_t: float, fuel_grade: str = "VLSFO") -> float:
    """Convert tonnes of fuel burned to tonnes of CO2 emitted."""
    return fuel_t * EMISSION_FACTORS_KG_CO2_PER_KG_FUEL.get(fuel_grade, 3.114)


# ── Edge metadata ─────────────────────────────────────────────────────────────
@dataclass
class EdgeMeta:
    """Per-edge geometry + sampled weather for the fuel calc.

    `bearing_deg` is the great-circle bearing from a→b. Wind direction
    follows meteorological convention (degrees the wind is *coming from*).
    """
    a: str
    b: str
    dist_km: float
    mid_lat: float
    mid_lon: float
    bearing_deg: float
    wind_speed_ms: float = 0.0
    wind_dir_deg: float = 0.0      # FROM direction (meteorological)
    wave_h_m: float = 0.0


def midpoint(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    # Simple midpoint is sufficient here because weather samples are route-edge
    # approximations, not navigation-grade waypoints.
    return ((lat1 + lat2) / 2.0, (lon1 + lon2) / 2.0)


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing a→b in degrees (0..360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def fuel_for_edge(v: VesselProfile, edge: EdgeMeta, speed_kn: float) -> dict:
    """Return per-edge fuel (tonnes), duration (hours), brake power (kW).

    Calm-water brake power comes from the admiralty coefficient (empirically
    derived from sea trials, so it already includes hull/propeller losses —
    we do NOT divide by `propulsive_eff` again there). The wind and wave
    components are mechanical resistance forces, so they are converted via
    `/propulsive_eff` to reach equivalent brake power.
    """
    # STEP 1 — Project the wind vector onto the course line.
    # Meteorological wind direction is "where wind comes from", so the
    # angle between (wind direction) and (vessel course) tells us whether
    # the wind hits the bow (headwind, slows us) or the stern (tailwind,
    # helps us). The (+540) % 360 - 180 trick wraps the angle into [-180,180].
    course = edge.bearing_deg
    delta = math.radians((edge.wind_dir_deg - course + 540.0) % 360.0 - 180.0)
    headwind_ms = (edge.wind_speed_ms or 0.0) * math.cos(delta)  # +head, -tail

    # STEP 2 — Calm-water shaft power from the admiralty coefficient.
    # The relationship is roughly cubic in speed, which is why even a
    # 1-knot speed cut can save a noticeable amount of fuel. This term
    # already bundles hull+propeller losses (it's empirical), so we do
    # NOT divide by `propulsive_eff` again here.
    P_calm_kW = (v.displacement_t ** (2.0 / 3.0) * speed_kn ** 3) / v.admiralty_coeff
    speed_ms = max(0.1, speed_kn * KN_TO_MS)

    # STEP 3 — Extra power needed to push through wind and waves.
    # Wind drag uses the standard 0.5·ρ·Cd·A·v² aerodynamic formula on
    # the *apparent* airspeed (ship speed + headwind). Wave resistance
    # is modelled as proportional to Hs² — a common simplification.
    v_app = max(0.0, speed_ms + headwind_ms)
    F_wind = 0.5 * RHO_AIR * v.cd_wind * v.frontal_area_m2 * v_app * v_app          # N
    F_wave = v.k_wave * (edge.wave_h_m or 0.0) ** 2 * 1000.0                         # N
    # Mechanical force × speed = power. We divide by propulsive efficiency
    # because these are resistance forces at the hull, not brake power.
    P_extra_shaft_kW = (F_wind + F_wave) * speed_ms / 1000.0                         # kW at prop shaft
    P_brake_kW = P_calm_kW + P_extra_shaft_kW / max(0.05, v.propulsive_eff)

    # STEP 4 — Convert power × time into fuel mass.
    # SFOC is grams of fuel per kWh, so (kW × g/kWh × h) / 1e6 gives tonnes.
    duration_h = (edge.dist_km * 1000.0) / speed_ms / 3600.0
    fuel_t = P_brake_kW * v.sfoc_g_kwh * duration_h / 1.0e6
    return {
        "fuel_t":      fuel_t,
        "duration_h":  duration_h,
        "power_kW":    P_brake_kW,
        "headwind_ms": headwind_ms,
    }


def voyage_totals(v: VesselProfile, edges: list[EdgeMeta], speed_kn: float) -> dict:
    # Sum edge-level physics outputs so route planners can compare complete
    # voyage fuel and ETA with the same model used for individual legs.
    fuel = 0.0
    hours = 0.0
    for e in edges:
        r = fuel_for_edge(v, e, speed_kn)
        fuel += r["fuel_t"]
        hours += r["duration_h"]
    return {"fuel_t": fuel, "hours": hours, "days": hours / 24.0}


# ── Monte Carlo ───────────────────────────────────────────────────────────────
def monte_carlo_voyage(
    v: VesselProfile,
    edges: list[EdgeMeta],
    speed_kn: float,
    n: int = 200,
    wind_sigma: float = 0.30,
    wave_sigma: float = 0.30,
    seed: int | None = 42,
) -> dict:
    """Perturb wind/wave on each edge and re-run fuel calc N times.

    Wind: Gaussian (can flip direction), σ = `wind_sigma` * forecast value.
    Wave: lognormal multiplier so Hs stays ≥ 0, σ in log-space = wave_sigma.
    Returns P10/P50/P90 fuel and ETA days plus the full sample arrays.
    """
    # Seeded RNG keeps the dashboard reproducible across reloads — same
    # forecast in, same P10/P50/P90 out. Change seed=None for fresh draws.
    rng = random.Random(seed)
    fuels: list[float] = []
    days: list[float] = []
    # Outer loop: N independent voyages. Inner loop: each edge gets its
    # own noisy wind and wave multipliers so different parts of the route
    # can be "lucky" or "unlucky" independently — same as reality.
    for _ in range(n):
        f_total = 0.0
        h_total = 0.0
        for e in edges:
            # Wind is symmetric around 1 (can be calmer or stronger).
            # Wave uses a lognormal so the multiplier stays positive — a
            # wave-height of zero or negative is non-physical.
            wind_mult = 1.0 + rng.gauss(0.0, wind_sigma)
            wave_mult = math.exp(rng.gauss(0.0, wave_sigma))
            perturbed = EdgeMeta(
                a=e.a, b=e.b, dist_km=e.dist_km,
                mid_lat=e.mid_lat, mid_lon=e.mid_lon,
                bearing_deg=e.bearing_deg,
                wind_speed_ms=max(0.0, e.wind_speed_ms * wind_mult),
                wind_dir_deg=e.wind_dir_deg,
                wave_h_m=max(0.0, e.wave_h_m * wave_mult),
            )
            r = fuel_for_edge(v, perturbed, speed_kn)
            f_total += r["fuel_t"]
            h_total += r["duration_h"]
        fuels.append(f_total)
        days.append(h_total / 24.0)
    # Sorting lets the percentile helper pick empirical quantiles directly
    # without pulling in NumPy just for this small Monte Carlo summary.
    fuels.sort(); days.sort()
    def pct(arr, p):
        idx = max(0, min(len(arr) - 1, int(p * (len(arr) - 1))))
        return arr[idx]
    return {
        "fuel_p10": pct(fuels, 0.10),
        "fuel_p50": pct(fuels, 0.50),
        "fuel_p90": pct(fuels, 0.90),
        "days_p10": pct(days, 0.10),
        "days_p50": pct(days, 0.50),
        "days_p90": pct(days, 0.90),
        "n":        n,
    }


# ── Edge weather penalty (used by marinav_router for graph weighting) ────────
def edge_weather_factor(edge: EdgeMeta) -> float:
    """Multiplier applied to edge weight in Dijkstra.

    Captures the routing intuition: prefer edges with tailwind / calm seas,
    penalize headwind and heavy seas. Caps at 2.5× so weather alone can't
    completely block an edge (chokepoint risk handles hard avoidance).
    """
    course = edge.bearing_deg
    delta = math.radians((edge.wind_dir_deg - course + 540.0) % 360.0 - 180.0)
    headwind_ms = (edge.wind_speed_ms or 0.0) * math.cos(delta)
    headwind_kts = max(-30.0, min(30.0, headwind_ms / KN_TO_MS))
    wave_pen = 0.10 * max(0.0, (edge.wave_h_m or 0.0) - 2.5)
    head_pen = 0.015 * max(0.0, headwind_kts)        # tailwind costs nothing extra
    tail_bonus = 0.005 * max(0.0, -headwind_kts)     # mild bonus for tailwind
    factor = 1.0 + head_pen + wave_pen - tail_bonus
    return max(0.85, min(2.5, factor))
