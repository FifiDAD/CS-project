"""Vessel class profiles for the route planner.

Fuel consumption follows a cubic-in-speed model:
    tons_per_day(v) = a * v**3 + b
where v is service speed in knots. Coefficients are tuned to published
design points (e.g. Panamax burns ~32 t/d at 14 kn, ~55 t/d at 16.5 kn).

Dimensions are typical "design" vessels — used to validate canal transit
(beam < lock width, draught < canal depth) and to size cargo capacity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VesselClass:
    name: str
    loa_m: float
    beam_m: float
    draught_m: float
    dwt_t: int
    design_speed_kn: float
    fuel_a: float    # cubic coeff, t/d per kn^3
    fuel_b: float    # idle/aux load, t/d
    fuel_grade: str  # primary fuel grade for cost lookup

    def fuel_tpd(self, speed_kn: float) -> float:
        return self.fuel_a * (speed_kn ** 3) + self.fuel_b


VESSELS: dict[str, VesselClass] = {
    "Panamax": VesselClass(
        name="Panamax",
        loa_m=229, beam_m=32.3, draught_m=12.0, dwt_t=75_000,
        design_speed_kn=14.0,
        fuel_a=0.0117, fuel_b=0.0,   # ~32 t/d @ 14 kn
        fuel_grade="VLSFO",
    ),
    "Capesize": VesselClass(
        name="Capesize",
        loa_m=300, beam_m=50.0, draught_m=18.0, dwt_t=180_000,
        design_speed_kn=14.5,
        fuel_a=0.0205, fuel_b=0.0,   # ~62 t/d @ 14.5 kn
        fuel_grade="VLSFO",
    ),
    "VLCC": VesselClass(
        name="VLCC",
        loa_m=330, beam_m=60.0, draught_m=22.0, dwt_t=300_000,
        design_speed_kn=15.5,
        fuel_a=0.0247, fuel_b=0.0,   # ~92 t/d @ 15.5 kn
        fuel_grade="VLSFO",
    ),
}
