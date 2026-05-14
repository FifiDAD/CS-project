
# =============================================================================
# maps.py — DRAWING THE 3D GLOBE
# =============================================================================
# This file is where the big interactive 3D globe on the main dashboard
# is built. It only does visualisation — no API calls, no computation
# of risk scores. We use Plotly's orthographic projection so the user
# can drag the globe around with the mouse.
#
# The main public function is create_dashboard_map() which takes all
# the data you might want to draw (events, route statuses, port
# congestion, AIS vessel positions, piracy incidents) and toggle flags
# for each layer, and returns a Plotly Figure object the page renders.
#
# Layers drawn (each can be turned on/off):
#   - Shipping routes      : 5 named lanes coloured by status
#                            (config.MAJOR_SHIPPING_ROUTES + config.ROUTE_STATUS_COLORS)
#   - Ports                : 8 markers coloured by live congestion score
#                            (api_config.CRITICAL_PORTS)
#   - Event markers        : GDELT-sourced events, sized by impact level
#   - AIS vessels          : live vessel positions from our SQLite cache
#   - Piracy incidents     : recent piracy from the IMB feed
#   - Day/night terminator : grey overlay showing where it's night right now
#
# The visual style ("Naval Command palette") — graphite land, near-black
# ocean, cyan coastlines, gold borders, 15° graticule — is applied
# inside this file via update_geos(). Don't override those colours
# elsewhere or the look breaks.
# =============================================================================

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from config import EVENT_TYPES, MAJOR_SHIPPING_ROUTES, IMPACT_LEVELS, ROUTE_STATUS_COLORS
from api_config import CRITICAL_PORTS

# Map event type to a color string for Plotly
EVENT_COLORS = {
    # Legacy categories (still used by mock fallback data)
    "Military Strike":      "#FF2222",
    "Port Disruption":      "#FF8C00",
    "Terrorist Activity":   "#8B0000",
    "Political Instability":"#9B59B6",
    "Supply Chain Alert":   "#3498DB",
    "Weather Hazard":       "#1A5276",
    # Live shipping-bucket categories from events_aggregator
    "🛑 Disruption": "#FF8C00",
    "⚠️ Threat":     "#FF2222",
    "🌊 Weather":    "#1A5276",
    "🏛 Political":  "#9B59B6",
    "📦 Trade":      "#3498DB",
    "🌋 Seismic":    "#E91E63",
}

# Fallback route colors based on declared traffic level, used when no live
# risk status has been computed for a route (e.g. on first load or API failure).
TRAFFIC_COLORS = {
    "Critical":  "red",
    "Very High": "orange",
    "High":      "yellow",
    "Medium":    "limegreen",
    "Low":       "limegreen",
}

# Colors for port markers on the map, keyed by congestion severity level.
# These match the same severity scale used in the Port Congestion sidebar panel.
CONGESTION_COLORS = {
    "Critical": "#FF2222",
    "High":     "#FF8C00",
    "Medium":   "#FFD700",
    "Low":      "#00CC44",
}

# ISO-3 → ISO-2 mapping used by the country-hover Choropleth layer.
# Covers all UN member states + key territories that appear on the map.
_ISO3_TO_ISO2 = {
    "AFG":"AF","ALB":"AL","DZA":"DZ","AND":"AD","AGO":"AO","ATG":"AG",
    "ARG":"AR","ARM":"AM","AUS":"AU","AUT":"AT","AZE":"AZ","BHS":"BS",
    "BHR":"BH","BGD":"BD","BRB":"BB","BLR":"BY","BEL":"BE","BLZ":"BZ",
    "BEN":"BJ","BTN":"BT","BOL":"BO","BIH":"BA","BWA":"BW","BRA":"BR",
    "BRN":"BN","BGR":"BG","BFA":"BF","BDI":"BI","CPV":"CV","KHM":"KH",
    "CMR":"CM","CAN":"CA","CAF":"CF","TCD":"TD","CHL":"CL","CHN":"CN",
    "COL":"CO","COM":"KM","COD":"CD","COG":"CG","CRI":"CR","CIV":"CI",
    "HRV":"HR","CUB":"CU","CYP":"CY","CZE":"CZ","DNK":"DK","DJI":"DJ",
    "DMA":"DM","DOM":"DO","ECU":"EC","EGY":"EG","SLV":"SV","GNQ":"GQ",
    "ERI":"ER","EST":"EE","SWZ":"SZ","ETH":"ET","FJI":"FJ","FIN":"FI",
    "FRA":"FR","GAB":"GA","GMB":"GM","GEO":"GE","DEU":"DE","GHA":"GH",
    "GRC":"GR","GRD":"GD","GTM":"GT","GIN":"GN","GNB":"GW","GUY":"GY",
    "HTI":"HT","HND":"HN","HUN":"HU","ISL":"IS","IND":"IN","IDN":"ID",
    "IRN":"IR","IRQ":"IQ","IRL":"IE","ISR":"IL","ITA":"IT","JAM":"JM",
    "JPN":"JP","JOR":"JO","KAZ":"KZ","KEN":"KE","KIR":"KI","PRK":"KP",
    "KOR":"KR","KWT":"KW","KGZ":"KG","LAO":"LA","LVA":"LV","LBN":"LB",
    "LSO":"LS","LBR":"LR","LBY":"LY","LIE":"LI","LTU":"LT","LUX":"LU",
    "MDG":"MG","MWI":"MW","MYS":"MY","MDV":"MV","MLI":"ML","MLT":"MT",
    "MHL":"MH","MRT":"MR","MUS":"MU","MEX":"MX","FSM":"FM","MDA":"MD",
    "MCO":"MC","MNG":"MN","MNE":"ME","MAR":"MA","MOZ":"MZ","MMR":"MM",
    "NAM":"NA","NRU":"NR","NPL":"NP","NLD":"NL","NZL":"NZ","NIC":"NI",
    "NER":"NE","NGA":"NG","MKD":"MK","NOR":"NO","OMN":"OM","PAK":"PK",
    "PLW":"PW","PAN":"PA","PNG":"PG","PRY":"PY","PER":"PE","PHL":"PH",
    "POL":"PL","PRT":"PT","QAT":"QA","ROU":"RO","RUS":"RU","RWA":"RW",
    "KNA":"KN","LCA":"LC","VCT":"VC","WSM":"WS","SMR":"SM","STP":"ST",
    "SAU":"SA","SEN":"SN","SRB":"RS","SYC":"SC","SLE":"SL","SGP":"SG",
    "SVK":"SK","SVN":"SI","SLB":"SB","SOM":"SO","ZAF":"ZA","SSD":"SS",
    "ESP":"ES","LKA":"LK","SDN":"SD","SUR":"SR","SWE":"SE","CHE":"CH",
    "SYR":"SY","TWN":"TW","TJK":"TJ","TZA":"TZ","THA":"TH","TLS":"TL",
    "TGO":"TG","TON":"TO","TTO":"TT","TUN":"TN","TUR":"TR","TKM":"TM",
    "TUV":"TV","UGA":"UG","UKR":"UA","ARE":"AE","GBR":"GB","USA":"US",
    "URY":"UY","UZB":"UZ","VUT":"VU","VEN":"VE","VNM":"VN","YEM":"YE",
    "ZMB":"ZM","ZWE":"ZW","XKX":"XK","PSE":"PS","MAC":"MO","HKG":"HK",
    "GRL":"GL","FLK":"FK","NCL":"NC","PYF":"PF","SHN":"SH","CUW":"CW",
}


# Returns the geographic point on Earth's surface directly below the sun right now.
# Used to position the day/night overlay and the ☀️ marker on the map.
# Returns the latitude/longitude of the point on Earth where the sun is
# directly overhead RIGHT NOW (the "subsolar point"). We need this to
# draw the grey night-side overlay on the globe. Uses a simplified solar
# position calculation — accurate enough for visual purposes.
def _get_subsolar_point():
    """Return (lat, lon) of the point on Earth directly under the sun (UTC now)."""
    now = datetime.now(timezone.utc)
    doy = now.timetuple().tm_yday

    # Solar declination: how far north or south the sun is today (±23.45° over the year).
    # Day 81 ≈ spring equinox, when the sun is directly over the equator.
    decl_deg = 23.45 * np.sin(np.radians(360 / 365 * (doy - 81)))

    # The sun is directly overhead at noon local time; each hour away from noon
    # shifts the subsolar longitude by 15° (360° / 24h).
    utc_hours = now.hour + now.minute / 60 + now.second / 3600
    lon_sun = (12 - utc_hours) * 15

    return decl_deg, lon_sun


# Computes the lat/lon coordinates of the day/night terminator line — the great
# circle that separates the sunlit and dark hemispheres. The terminator is always
# perpendicular to the direction of the sun, so we find two vectors orthogonal to
# the sun vector and sweep a full circle around them in 3D Cartesian space.
def _compute_terminator(lat_s_deg, lon_s_deg, n=180):
    lat_s = np.radians(lat_s_deg)
    lon_s = np.radians(lon_s_deg)

    # Convert the subsolar point from spherical to 3D unit-vector (Cartesian).
    sx = np.cos(lat_s) * np.cos(lon_s)
    sy = np.cos(lat_s) * np.sin(lon_s)
    sz = np.sin(lat_s)

    # Build a first basis vector (v1) tangent to the equatorial plane.
    # Special-case the poles, where the standard tangent formula degenerates.
    cos_lat = np.cos(lat_s)
    if abs(cos_lat) > 1e-6:
        v1 = np.array([np.sin(lon_s), -np.cos(lon_s), 0.0])
    else:
        v1 = np.array([1.0, 0.0, 0.0])

    # v2 is perpendicular to both the sun vector and v1, completing the basis
    # of the terminator plane. Normalise to keep it on the unit sphere.
    v2 = np.cross([sx, sy, sz], v1)
    v2 = v2 / np.linalg.norm(v2)

    # Sweep n equally-spaced angles around the full circle in the terminator plane.
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    px = np.cos(t) * v1[0] + np.sin(t) * v2[0]
    py = np.cos(t) * v1[1] + np.sin(t) * v2[1]
    pz = np.cos(t) * v1[2] + np.sin(t) * v2[2]

    # Convert sampled 3D points back to lat/lon for Plotly.
    lats = np.degrees(np.arcsin(np.clip(pz, -1, 1)))
    lons = np.degrees(np.arctan2(py, px))
    return lats, lons


# Turns the terminator line into a closed polygon covering the night hemisphere,
# so Plotly can fill it with a dark semi-transparent colour. The terminator alone
# is just a line; to fill one side we must "cap" it by connecting both ends of
# the line through the pole that is currently in darkness.
def _build_night_polygon(lat_s_deg, lon_s_deg, n=180):
    lats, lons = _compute_terminator(lat_s_deg, lon_s_deg, n)

    # The dark pole is the one opposite to the sun's hemisphere.
    pole_lat = -90.0 if lat_s_deg >= 0 else 90.0

    half = n // 2

    # First half of the terminator arc.
    poly_lats = list(lats[:half])
    poly_lons = list(lons[:half])

    # Sweep across the pole to connect the two ends of the first half —
    # this closes the cap over the dark hemisphere without crossing the map.
    sweep_lons = np.linspace(lons[half - 1], lons[half], 30)
    poly_lats += [pole_lat] * 30
    poly_lons += list(sweep_lons)

    # Second half of the terminator arc (back toward the start).
    poly_lats += list(lats[half:])
    poly_lons += list(lons[half:])

    # Close the polygon by sweeping back across the pole to the starting point.
    sweep_lons2 = np.linspace(lons[-1], lons[0], 30)
    poly_lats += [pole_lat] * 30
    poly_lons += list(sweep_lons2)

    return poly_lats, poly_lons


# Renders all three components of the day/night overlay onto the figure:
# (1) a dark filled polygon covering the night hemisphere,
# (2) the golden dashed terminator line (the sunrise/sunset boundary),
# (3) a ☀️ star marker at the subsolar point (where the sun is directly overhead).
def _add_day_night(fig, lat_s, lon_s):
    """Add night hemisphere fill and terminator line to the figure."""
    poly_lats, poly_lons = _build_night_polygon(lat_s, lon_s)
    # Dark semi-transparent fill over the night side of the globe.
    fig.add_trace(go.Scattergeo(
        lat=poly_lats,
        lon=poly_lons,
        mode="lines",
        fill="toself",
        fillcolor="rgba(2, 6, 18, 0.40)",
        line=dict(width=0),
        hoverinfo="skip",
        showlegend=False,
        name="Night",
    ))

    # Close the terminator loop so it draws as a continuous circle, then
    # render it as a gold dotted line to evoke the look of a nautical chart.
    term_lats, term_lons = _compute_terminator(lat_s, lon_s)
    term_lats = np.append(term_lats, term_lats[0])
    term_lons = np.append(term_lons, term_lons[0])

    fig.add_trace(go.Scattergeo(
        lat=term_lats,
        lon=term_lons,
        mode="lines",
        line=dict(width=2.5, color="rgba(255, 220, 80, 0.95)", dash="dot"),
        hoverinfo="skip",
        showlegend=False,
        name="Terminator",
    ))

    # Gold star marker at the subsolar point — the one spot on Earth where the
    # sun is directly overhead right now. Appears in the legend under "Day / Night".
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


# The MAIN function of this file. Builds the entire 3D globe figure
# from all the data layers it's given, with toggleable visibility for
# each layer. Returns a Plotly Figure object — the calling page (app.py)
# just hands it to st.plotly_chart() to display.
def create_dashboard_map(
    events_df,
    show_routes=True,
    show_ports=True,
    show_events=True,
    show_vessels=False,
    show_daynight=True,
    show_piracy=False,
    route_statuses=None,
    port_congestion_df=None,
    ais_df=None,
    piracy_df=None,
):
    """
    Create a 2D world map (Natural Earth projection) with toggleable layers.

    Args:
        events_df: DataFrame of geopolitical events
        show_routes: Whether to draw shipping route lines
        show_ports: Whether to plot port markers
        show_events: Whether to plot event markers
        show_vessels: Whether to plot live AIS vessel positions
        show_daynight: Whether to draw the day/night terminator overlay
        route_statuses: dict {route_name: status_string} for dynamic coloring
        port_congestion_df: DataFrame from compute_port_congestion() for port markers
        ais_df: DataFrame from ais_consumer.latest_positions()
    """

    # Traces are added in back-to-front order so that important markers always
    # render on top: day/night fill → reference lines → routes → ports → events.
    fig = go.Figure()

    # ── Country hover layer ───────────────────────────────────────────────────
    # Fully-transparent Choropleth placed first (bottom of the stack) so all
    # Scattergeo traces render on top and their hovers take priority. The only
    # purpose of this trace is to expose per-country hover regions that show the
    # ISO-2 code when the cursor is over open land with no other marker nearby.
    _iso3 = list(_ISO3_TO_ISO2.keys())
    _iso2 = [_ISO3_TO_ISO2[k] for k in _iso3]
    fig.add_trace(go.Choropleth(
        locations=_iso3,
        z=[0] * len(_iso3),
        text=_iso2,
        hovertemplate="%{text}<extra></extra>",
        colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
        showscale=False,
        marker_line_width=0,
        showlegend=False,
        geo="geo",
    ))

    # ── Day / Night overlay ───────────────────────────────────────────────────
    if show_daynight:
        lat_sun, lon_sun = _get_subsolar_point()
        _add_day_night(fig, lat_sun, lon_sun)

    # ── Chokepoint labels (cartographic gravitas) ────────────────────────────
    # Major maritime chokepoints labelled in gold so the map reads as a
    # purposeful trade-route display, not just dots on a globe.
    _CHOKEPOINT_LABELS = [
        ("Suez",         30.5,   33.0),
        ("Hormuz",       26.5,   57.0),
        ("Bab el-Mandeb",12.5,   44.5),
        ("Malacca",       3.0,  100.5),
        ("Singapore Str.",1.0,  104.5),
        ("Panama",        9.0,  -79.5),
        ("Bosphorus",    41.0,   29.5),
        ("English Ch.",  50.5,   -1.0),
        ("Cape of G.H.",-34.5,   19.0),
    ]
    for _name, _clat, _clon in _CHOKEPOINT_LABELS:
        fig.add_trace(go.Scattergeo(
            lon=[_clon], lat=[_clat], mode="text",
            text=[f"<b>{_name}</b>"],
            textfont=dict(color="rgba(212,175,55,0.85)", size=8,
                          family="Inter, system-ui, sans-serif"),
            textposition="top right",
            hoverinfo="skip", showlegend=False,
        ))

    # ── Equator + Tropics overlay (cartographic gravitas) ────────────────────
    # Solid gold Equator; dashed Tropics of Cancer/Capricorn. Drawn behind
    # routes and markers so they don't compete for attention.
    fig.add_trace(go.Scattergeo(
        lon=[-180, 180], lat=[0, 0],
        mode="lines",
        line=dict(color="rgba(212,175,55,0.45)", width=1.0),
        hoverinfo="skip", showlegend=False,
        name="Equator",
    ))
    for _tropic_lat in (23.4368, -23.4368):
        fig.add_trace(go.Scattergeo(
            lon=[-180, 180], lat=[_tropic_lat, _tropic_lat],
            mode="lines",
            line=dict(color="rgba(120,180,220,0.25)", width=0.6, dash="dot"),
            hoverinfo="skip", showlegend=False,
        ))

    # ── Shipping routes ───────────────────────────────────────────────────────
    if show_routes:
        first_route = True
        for route_name, route_info in MAJOR_SHIPPING_ROUTES.items():
            coords  = route_info["coords"]
            traffic = route_info["traffic"]

            # Dynamic color from computed status; fall back to traffic-based color
            if route_statuses and route_name in route_statuses:
                color = ROUTE_STATUS_COLORS.get(route_statuses[route_name], "royalblue")
                status_label = route_statuses[route_name]
            else:
                color = TRAFFIC_COLORS.get(traffic, "royalblue")
                status_label = route_info.get("status", "operational").title()

            lats = [c[0] for c in coords]
            lons = [c[1] for c in coords]

            # Glow trace — wider, low-opacity. Scattergeo lines auto-follow
            # great-circle paths so curves come for free without spline args.
            fig.add_trace(go.Scattergeo(
                lat=lats,
                lon=lons,
                mode="lines",
                line=dict(width=10, color=color),
                opacity=0.22,
                hoverinfo="skip",
                showlegend=False,
                name=f"{route_name}_glow",
            ))

            # Main route line — bright neon, slightly thinner for premium feel
            fig.add_trace(go.Scattergeo(
                lat=lats,
                lon=lons,
                mode="lines",
                line=dict(width=2.2, color=color),
                opacity=0.95,
                name=route_name,
                hovertemplate=(
                    f"<b>{route_name}</b><br>"
                    f"Status: {status_label}<br>"
                    f"Traffic: {traffic}<extra></extra>"
                ),
                legendgroup="routes",
                legendgrouptitle_text="Shipping Routes" if first_route else None,
            ))

            # Directional arrow at the route midpoint — reinforces flow.
            if len(lats) >= 2:
                _mi = len(lats) // 2
                _a_lat = lats[_mi]
                _a_lon = lons[_mi]
                # Compute bearing from previous waypoint for arrow rotation;
                # Plotly text doesn't auto-rotate so we pick a chevron that
                # roughly points east-west based on the segment delta.
                _dlon = lons[_mi] - lons[_mi - 1]
                _arrow = "▶" if _dlon >= 0 else "◀"
                fig.add_trace(go.Scattergeo(
                    lat=[_a_lat], lon=[_a_lon], mode="text",
                    text=[_arrow],
                    textfont=dict(color=color, size=14),
                    hoverinfo="skip", showlegend=False,
                ))
            first_route = False

    # ── Port congestion markers ───────────────────────────────────────────────
    if not show_ports:
        port_congestion_df = None  # short-circuit fallback path too
    # When live congestion data is available, colour each port by its severity.
    # If the API hasn't returned data yet, fall back to static grey markers so
    # ports are always visible even on first load or API failure.
    if port_congestion_df is not None and len(port_congestion_df) > 0 and show_ports:
        port_colors = [CONGESTION_COLORS.get(c, "#888888") for c in port_congestion_df["Congestion"]]
        # Builds the multi-line tooltip shown when a user hovers over a port marker.
        def _port_hover(row):
            queue = row.get("Queue (anchored)", "—")
            delay = row.get("Expected Delay (d)", "—")
            return (
                f"<b>⚓ {row['Port']}</b> ({row.get('Country','')})<br>"
                f"Congestion: <b>{row['Congestion']}</b> · Score {row['Score']}/100<br>"
                f"Queue at anchor: <b>{queue}</b> vessels (in {row.get('Berths','?')} berths)<br>"
                f"Expected delay: <b>{delay} days</b><br>"
                f"Sea state: {row.get('Sea State','n/a')}<br>"
                f"Conflict events nearby: {row.get('Conflict Events',0)}<br>"
                f"Disruption news hits: {row.get('News Hits',0)}"
            )
        port_hover = [_port_hover(row) for _, row in port_congestion_df.iterrows()]
        fig.add_trace(go.Scattergeo(
            lat=port_congestion_df["Lat"].tolist(),
            lon=port_congestion_df["Lon"].tolist(),
            mode="markers+text",
            marker=dict(
                size=8,
                color=port_colors,
                symbol="circle",
                line=dict(width=1.0, color="rgba(212,175,55,0.55)"),
                opacity=0.95,
            ),
            text=[row["Port"][:3].upper() for _, row in port_congestion_df.iterrows()],
            textposition="top center",
            textfont=dict(size=8, color="rgba(212,175,55,0.85)"),
            name="⚓ Ports",
            hovertemplate="%{customdata}<extra></extra>",
            customdata=port_hover,
            showlegend=True,
            legendgroup="ports",
            legendgrouptitle_text="Ports",
        ))
    elif show_ports:
        # Fallback: always show ports as grey markers when API data unavailable
        fallback_lats  = [v["lat"]  for v in CRITICAL_PORTS.values()]
        fallback_lons  = [v["lon"]  for v in CRITICAL_PORTS.values()]
        fallback_names = list(CRITICAL_PORTS.keys())
        fallback_hover = [f"<b>⚓ {n}</b><br>Congestion: Unknown" for n in fallback_names]
        fig.add_trace(go.Scattergeo(
            lat=fallback_lats,
            lon=fallback_lons,
            mode="markers+text",
            marker=dict(
                size=7,
                color="#888888",
                symbol="circle",
                line=dict(width=1.0, color="rgba(212,175,55,0.45)"),
                opacity=0.7,
            ),
            text=[n[:3].upper() for n in fallback_names],
            textposition="top center",
            textfont=dict(size=8, color="white"),
            name="⚓ Ports",
            hovertemplate="%{customdata}<extra></extra>",
            customdata=fallback_hover,
            showlegend=True,
            legendgroup="ports",
            legendgrouptitle_text="Ports",
        ))

    # ── Critical event threat rings (radar ping effect) ───────────────────────
    # Large semi-transparent circles drawn beneath Critical event markers to
    # give a "radar ping" visual cue that these locations are high-priority threats.
    if show_events and len(events_df) > 0:
        critical_events = events_df[events_df["impact"] == "Critical"] if "impact" in events_df.columns else pd.DataFrame()
        if len(critical_events) > 0:
            fig.add_trace(go.Scattergeo(
                lat=critical_events["latitude"],
                lon=critical_events["longitude"],
                mode="markers",
                marker=dict(
                    size=32,
                    color="rgba(255, 0, 0, 0.08)",
                    symbol="circle",
                    line=dict(width=1.5, color="rgba(255, 50, 50, 0.5)"),
                ),
                hoverinfo="skip",
                showlegend=False,
                name="Critical Threat Ring",
            ))

    # ── AIS vessel positions ──────────────────────────────────────────────────
    # Live vessel positions from the AIS consumer. Green = moving (≥0.5 kn),
    # yellow = stationary/slow. This layer is off by default to avoid clutter.
    if show_vessels and ais_df is not None and len(ais_df) > 0:
        sog = ais_df["sog_kn"].fillna(0)
        ais_hover = [
            f"<b>⛴ {row.get('name') or 'MMSI ' + str(row['mmsi'])}</b><br>"
            f"Speed: {row.get('sog_kn') or 0:.1f} kn · Course: {row.get('cog_deg') or 0:.0f}°<br>"
            f"Lat {row['lat']:.3f} · Lon {row['lon']:.3f}"
            for _, row in ais_df.iterrows()
        ]
        fig.add_trace(go.Scattergeo(
            lat=ais_df["lat"],
            lon=ais_df["lon"],
            mode="markers",
            marker=dict(
                size=4,
                color=["#2ecc71" if s >= 0.5 else "#f1c40f" for s in sog],
                opacity=0.85,
                line=dict(width=0),
                symbol="triangle-up",
            ),
            name=f"⛴ Vessels ({len(ais_df)})",
            hovertemplate="%{customdata}<extra></extra>",
            customdata=ais_hover,
            legendgroup="vessels",
            legendgrouptitle_text="AIS",
        ))

    # ── Piracy incidents (last 90 days) ──────────────────────────────────────
    # Recent piracy and maritime crime incidents plotted as red X markers.
    # This layer is off by default and only shown when explicitly enabled.
    if show_piracy and piracy_df is not None and len(piracy_df) > 0:
        pir_hover = [
            f"<b>☠ Piracy / Maritime Crime</b><br>"
            f"📍 {row.get('source_country','')}<br>"
            f"🗓 {row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else row['date']}<br>"
            f"<i>{(row.get('title') or '')[:120]}</i>"
            for _, row in piracy_df.iterrows()
        ]
        fig.add_trace(go.Scattergeo(
            lat=piracy_df["lat"],
            lon=piracy_df["lon"],
            mode="markers",
            marker=dict(
                size=14,
                color="rgba(220, 38, 38, 0.85)",
                symbol="x",
                line=dict(width=2, color="white"),
            ),
            name=f"☠ Piracy ({len(piracy_df)})",
            hovertemplate="%{customdata}<extra></extra>",
            customdata=pir_hover,
            legendgroup="piracy",
            legendgrouptitle_text="Piracy",
        ))

    # ── Event markers (grouped by type) ──────────────────────────────────────
    # Each event type gets its own Plotly trace so they appear as separate
    # toggle-able entries in the legend. Within each type, marker size reflects
    # severity: Critical events are larger dots, Low events are smaller.
    if show_events and len(events_df) > 0:
        first_event_type = True
        for event_type, group in events_df.groupby("type"):
            color = EVENT_COLORS.get(event_type, "#AAAAAA")

            # Scale marker size by impact level so the most severe events
            # stand out visually even when many events overlap.
            sizes = group["impact"].map({
                "Critical": 13,
                "High":     9,
                "Medium":   7,
                "Low":      5,
            }).fillna(7)

            # Builds the rich tooltip shown when hovering an event marker.
            # Uses customdata (not hovertext) because Plotly only formats
            # customdata strings with full HTML newlines in Scattergeo.
            def _ev_hover(row):
                bucket = row.get("type", "Event")
                sub = row.get("subtype", "")
                loc = row.get("location", "")
                try:
                    ts = row["date"].strftime("%Y-%m-%d %H:%M")
                except Exception:
                    ts = ""
                impact = row.get("impact", "")
                detail = row.get("business_impact", "")
                # Plotly hover layers can't contain clickable HTML, so we
                # surface the multi-source corroboration here and leave the
                # actual article link to the Intel Feed page.
                n_sources = int(row.get("n_sources", 0) or 0)
                sources_line = (
                    f"<br>📰 Confirmed by {n_sources} sources · see Intel Feed"
                    if n_sources >= 2 else ""
                )
                return (
                    f"<b>{bucket}</b>"
                    + (f" · {sub}" if sub else "")
                    + f"<br>📍 {loc}"
                    + (f"<br>🗓 {ts}" if ts else "")
                    + f"<br>⚡ Impact: <b>{impact}</b>"
                    + (f"<br>📊 {detail}" if detail else "")
                    + sources_line
                )
            hover_texts = [_ev_hover(row) for _, row in group.iterrows()]

            # Halo ONLY for Critical events. With multi-source filtering letting
            # several events through at the same chokepoint coords, blanket halos
            # were stacking into giant orange/red blobs that read as a "background
            # fill" — see the screenshot regression. 1.4× / 0.06 opacity caps
            # five overlapping criticals at <0.30 effective opacity: visible
            # alert glow, no region wash.
            crit_mask = group["impact"] == "Critical"
            if crit_mask.any():
                fig.add_trace(go.Scattergeo(
                    lat=group.loc[crit_mask, "latitude"],
                    lon=group.loc[crit_mask, "longitude"],
                    mode="markers",
                    marker=dict(
                        size=sizes[crit_mask] * 1.4,
                        color=color,
                        opacity=0.06,
                        line=dict(width=0),
                        symbol="circle",
                    ),
                    hoverinfo="skip", showlegend=False,
                    legendgroup="events",
                ))

            fig.add_trace(go.Scattergeo(
                lat=group["latitude"],
                lon=group["longitude"],
                mode="markers",
                marker=dict(
                    size=sizes,
                    color=color,
                    opacity=0.95,
                    line=dict(width=0.6, color="rgba(255,255,255,0.35)"),
                    symbol="circle",
                ),
                name=event_type,
                hovertemplate="%{customdata}<extra></extra>",
                customdata=hover_texts,
                legendgroup="events",
                legendgrouptitle_text="Events" if first_event_type else None,
            ))
            first_event_type = False

    # ── Map layout — "Naval Command" aesthetic ──────────────────────────────
    # Heavy detail dark, military-grade situational-awareness look.
    # Country borders + states/oblasts + major rivers all visible. Bright
    # cyan coastlines, gold political borders, 15° graticule.
    fig.update_layout(
        height=600,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        # Pan mode by default so users can explore the map without accidentally
        # triggering zoom on scroll, which conflicts with the Streamlit page scroll.
        dragmode="pan",
        font=dict(family="Inter, system-ui, sans-serif", color="#cfe1ff", size=11),
        legend=dict(
            bgcolor="rgba(0,8,20,0.78)",
            bordercolor="rgba(212,175,55,0.30)",
            borderwidth=1,
            font=dict(color="#cfe1ff", size=10),
            x=0.01, y=0.99,
            itemsizing="constant",
        ),
        # All geographic styling lives inside the `geo` dict. The Natural Earth
        # projection gives a familiar flat-map appearance that works well on a
        # widescreen dashboard layout (orthographic globe was used previously
        # but the flat projection makes it easier to read routes at a glance).
        geo=dict(
            projection_type="natural earth",
            showland=True,
            landcolor="#1a1f26",                       # graphite
            showocean=True,
            oceancolor="#a8d5e8",                      # soft maritime blue
            showlakes=True,
            lakecolor="#0a1828",
            showcountries=True,
            countrycolor="rgba(212,175,55,0.32)",      # gold political borders
            countrywidth=0.7,
            showsubunits=True,                         # US states / Russian oblasts / Indian states
            subunitcolor="rgba(212,175,55,0.14)",
            subunitwidth=0.4,
            showrivers=True,                           # major rivers
            rivercolor="rgba(80,140,200,0.40)",
            riverwidth=0.5,
            showcoastlines=True,
            coastlinecolor="rgba(120,200,255,0.70)",   # bright cyan coastlines
            coastlinewidth=0.95,
            showframe=False,
            bgcolor="#0d1117",
            resolution=50,
            lataxis=dict(
                showgrid=True,
                gridcolor="rgba(120,180,220,0.10)",
                gridwidth=0.4,
                dtick=15,
            ),
            lonaxis=dict(
                showgrid=True,
                gridcolor="rgba(120,180,220,0.10)",
                gridwidth=0.4,
                dtick=15,
            ),
            # Clip latitude to avoid showing the poles, which are rarely relevant
            # for shipping routes and waste vertical space on a 600 px tall chart.
            lataxis_range=[-70, 80],
            lonaxis_range=[-180, 180],
        ),
    )

    return fig
