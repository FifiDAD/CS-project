"""Map visualization functions for the Global Events Dashboard"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from config import EVENT_TYPES, MAJOR_SHIPPING_ROUTES, IMPACT_LEVELS

# Map event type to a color string for Plotly
EVENT_COLORS = {
    "Military Strike":      "#FF2222",
    "Port Disruption":      "#FF8C00",
    "Terrorist Activity":   "#8B0000",
    "Political Instability":"#9B59B6",
    "Supply Chain Alert":   "#3498DB",
    "Weather Hazard":       "#1A5276",
}

TRAFFIC_COLORS = {
    "Critical":  "red",
    "Very High": "orange",
    "High":      "yellow",
    "Medium":    "royalblue",
    "Low":       "limegreen",
}


def _get_subsolar_point():
    """Return (lat, lon) of the point on Earth directly under the sun (UTC now)."""
    now = datetime.now(timezone.utc)
    doy = now.timetuple().tm_yday

    # Solar declination (degrees)
    decl_deg = 23.45 * np.sin(np.radians(360 / 365 * (doy - 81)))

    # Subsolar longitude: at UTC 12:00 the sun is over lon=0
    utc_hours = now.hour + now.minute / 60 + now.second / 3600
    lon_sun = (12 - utc_hours) * 15  # degrees, wraps naturally

    return decl_deg, lon_sun


def _compute_terminator(lat_s_deg, lon_s_deg, n=360):
    """
    Return (lats, lons) arrays for the full terminator circle.
    Uses the parametric form of the great circle perpendicular to the sun vector.
    """
    lat_s = np.radians(lat_s_deg)
    lon_s = np.radians(lon_s_deg)

    # Sun unit vector
    sx = np.cos(lat_s) * np.cos(lon_s)
    sy = np.cos(lat_s) * np.sin(lon_s)
    sz = np.sin(lat_s)

    # v1: perpendicular to sun in the equatorial plane
    cos_lat = np.cos(lat_s)
    if abs(cos_lat) > 1e-6:
        v1 = np.array([np.sin(lon_s), -np.cos(lon_s), 0.0])
    else:
        v1 = np.array([1.0, 0.0, 0.0])

    # v2: perpendicular to both sun and v1
    v2 = np.cross([sx, sy, sz], v1)
    v2 = v2 / np.linalg.norm(v2)

    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    px = np.cos(t) * v1[0] + np.sin(t) * v2[0]
    py = np.cos(t) * v1[1] + np.sin(t) * v2[1]
    pz = np.cos(t) * v1[2] + np.sin(t) * v2[2]

    lats = np.degrees(np.arcsin(np.clip(pz, -1, 1)))
    lons = np.degrees(np.arctan2(py, px))
    return lats, lons


def _build_night_polygon(lat_s_deg, lon_s_deg, n=360):
    """
    Build a closed polygon (lats, lons) that covers the night hemisphere.
    Strategy: terminator first half → night pole → terminator second half.
    """
    lats, lons = _compute_terminator(lat_s_deg, lon_s_deg, n)

    # The pole in permanent night depends on the sign of solar declination
    pole_lat = -90.0 if lat_s_deg >= 0 else 90.0

    half = n // 2

    # First half of terminator (t: 0 → π)
    poly_lats = list(lats[:half])
    poly_lons = list(lons[:half])

    # Drop straight down (or up) to the night pole, sweeping in longitude
    # to avoid a cross-meridian artefact in Plotly
    sweep_lons = np.linspace(lons[half - 1], lons[half], 30)
    poly_lats += [pole_lat] * 30
    poly_lons += list(sweep_lons)

    # Second half of terminator (t: π → 2π)
    poly_lats += list(lats[half:])
    poly_lons += list(lons[half:])

    # Close back to the night pole so Plotly fills correctly
    sweep_lons2 = np.linspace(lons[-1], lons[0], 30)
    poly_lats += [pole_lat] * 30
    poly_lons += list(sweep_lons2)

    return poly_lats, poly_lons


def _add_day_night(fig, lat_s, lon_s):
    """Add night hemisphere fill and terminator line to the figure."""

    # ── Night fill ────────────────────────────────────────────────────────────
    poly_lats, poly_lons = _build_night_polygon(lat_s, lon_s)
    fig.add_trace(go.Scattergeo(
        lat=poly_lats,
        lon=poly_lons,
        mode="lines",
        fill="toself",
        fillcolor="rgba(0, 0, 20, 0.55)",
        line=dict(width=0),
        hoverinfo="skip",
        showlegend=False,
        name="Night",
    ))

    # ── Terminator line ───────────────────────────────────────────────────────
    term_lats, term_lons = _compute_terminator(lat_s, lon_s)
    # Close the line
    term_lats = np.append(term_lats, term_lats[0])
    term_lons = np.append(term_lons, term_lons[0])

    fig.add_trace(go.Scattergeo(
        lat=term_lats,
        lon=term_lons,
        mode="lines",
        line=dict(width=1.5, color="rgba(255, 200, 50, 0.75)", dash="dot"),
        hoverinfo="skip",
        showlegend=False,
        name="Terminator",
    ))

    # ── Subsolar point ────────────────────────────────────────────────────────
    fig.add_trace(go.Scattergeo(
        lat=[lat_s],
        lon=[lon_s],
        mode="markers+text",
        marker=dict(size=14, color="gold", symbol="star",
                    line=dict(width=1, color="white")),
        text=["☀️"],
        textposition="top center",
        textfont=dict(size=14),
        hovertemplate=(
            f"<b>☀️ Subsolar Point</b><br>"
            f"Lat: {lat_s:.1f}°  Lon: {lon_s:.1f}°<extra></extra>"
        ),
        showlegend=True,
        name="☀️ Subsolar Point",
        legendgroup="daynight",
        legendgrouptitle_text="Day / Night",
    ))


def create_dashboard_map(events_df, show_routes=True):
    """Create a 3D orthographic globe with events and shipping routes."""

    fig = go.Figure()

    # ── Day / Night overlay ───────────────────────────────────────────────────
    lat_sun, lon_sun = _get_subsolar_point()
    _add_day_night(fig, lat_sun, lon_sun)

    # ── Shipping routes ──────────────────────────────────────────────────────
    if show_routes:
        for route_name, route_info in MAJOR_SHIPPING_ROUTES.items():
            coords  = route_info["coords"]
            traffic = route_info["traffic"]
            status  = route_info["status"]
            color   = TRAFFIC_COLORS.get(traffic, "royalblue")

            lats = [c[0] for c in coords]
            lons = [c[1] for c in coords]

            fig.add_trace(go.Scattergeo(
                lat=lats,
                lon=lons,
                mode="lines",
                line=dict(width=3, color=color),
                name=route_name,
                hovertemplate=(
                    f"<b>{route_name}</b><br>"
                    f"Traffic: {traffic}<br>"
                    f"Status: {status}<extra></extra>"
                ),
                legendgroup="routes",
                legendgrouptitle_text="Shipping Routes" if route_name == list(MAJOR_SHIPPING_ROUTES.keys())[0] else None,
            ))

    # ── Events ───────────────────────────────────────────────────────────────
    if len(events_df) > 0:
        # Group by event type so each type gets its own legend entry
        for event_type, group in events_df.groupby("type"):
            color  = EVENT_COLORS.get(event_type, "#AAAAAA")
            icon   = EVENT_TYPES.get(event_type, {}).get("icon", "📍")

            # Marker size driven by impact level
            sizes = group["impact"].map({
                "Critical": 18,
                "High":     13,
                "Medium":   9,
                "Low":      6,
            }).fillna(9)

            hover_texts = [
                f"<b>{icon} {row['type']}</b><br>"
                f"📍 {row['location']}<br>"
                f"🗓 {row['date'].strftime('%Y-%m-%d %H:%M')}<br>"
                f"⚡ Impact: <b>{row['impact']}</b><br>"
                f"{row['description']}<br>"
                f"📦 {row['business_impact']}"
                for _, row in group.iterrows()
            ]

            fig.add_trace(go.Scattergeo(
                lat=group["latitude"],
                lon=group["longitude"],
                mode="markers",
                marker=dict(
                    size=sizes,
                    color=color,
                    opacity=0.85,
                    line=dict(width=1, color="white"),
                    symbol="circle",
                ),
                name=f"{icon} {event_type}",
                hovertemplate="%{customdata}<extra></extra>",
                customdata=hover_texts,
                legendgroup="events",
                legendgrouptitle_text="Events" if event_type == events_df["type"].unique()[0] else None,
            ))

    # ── Globe layout ─────────────────────────────────────────────────────────
    fig.update_layout(
        height=650,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="#000510",
        legend=dict(
            bgcolor="rgba(0,5,16,0.85)",
            bordercolor="#1a3a5c",
            borderwidth=1,
            font=dict(color="#d0e8ff", size=11),
            x=0.01,
            y=0.99,
        ),
        geo=dict(
            projection_type="orthographic",
            showland=True,
            landcolor="#2d6a2d",
            showocean=True,
            oceancolor="#0a2a5e",
            showlakes=True,
            lakecolor="#1a5090",
            showcountries=True,
            countrycolor="rgba(255,255,255,0.35)",
            showcoastlines=True,
            coastlinecolor="rgba(255,255,255,0.7)",
            showrivers=True,
            rivercolor="#1a6aaa",
            showframe=False,
            bgcolor="#000510",
            resolution=50,
            projection_rotation=dict(lon=20, lat=20, roll=0),
        ),
    )

    return fig
