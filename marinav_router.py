"""
Maritime route optimizer for TradeWatch.

Routing methodology inspired by MariNav (https://github.com/Vaishnav2804/MariNav)
by Vaishnav2804 and contributors. Key concepts borrowed:
  - Uber H3 hexagonal grid representation of ocean space
  - NetworkX graph-based shortest-path routing with risk-weighted edges
  - Chokepoint risk penalties that steer routes toward safer alternatives

Adaptation for TradeWatch: instead of AIS training data + RL policy,
this module uses an explicit global maritime backbone graph whose edges
are weighted by geographic distance × live TradeWatch risk scores.
When a chokepoint like the Suez Canal has a high risk score, Dijkstra
automatically prefers the Cape of Good Hope detour.
"""

from __future__ import annotations

import math
import networkx as nx

try:
    import h3 as _h3
    H3_AVAILABLE = True
except ImportError:
    H3_AVAILABLE = False

H3_RES = 4  # ~220 km hexagons — same resolution concept as MariNav

# ── Major shipping ports ──────────────────────────────────────────────────────
PORTS: dict[str, tuple[float, float]] = {
    "Rotterdam":         (51.922,   4.479),
    "Antwerp":           (51.221,   4.405),
    "Hamburg":           (53.551,  10.000),
    "Felixstowe":        (51.964,   1.352),
    "Piraeus":           (37.940,  23.640),
    "Algeciras":         (36.130,  -5.450),
    "Singapore":         (1.265,  103.820),
    "Port Klang":        (3.000,  101.400),
    "Shanghai":          (31.230, 121.474),
    "Ningbo":            (29.867, 121.550),
    "Tianjin":           (38.980, 117.720),
    "Busan":             (35.180, 129.076),
    "Hong Kong":         (22.280, 114.170),
    "Kaohsiung":         (22.620, 120.280),
    "Tokyo / Yokohama":  (35.440, 139.650),
    "Jebel Ali (Dubai)": (24.986,  55.027),
    "Colombo":           (6.927,   79.861),
    "Mumbai":            (18.975,  72.826),
    "Jeddah":            (21.490,  39.180),
    "Los Angeles":       (33.740, -118.265),
    "Long Beach":        (33.754, -118.216),
    "New York / Newark": (40.650,  -74.035),
    "Houston":           (29.735,  -95.000),
    "Santos":            (-23.961, -46.334),
    "Cape Town":         (-33.925,  18.424),
    "Durban":            (-29.870,  31.040),
}

# Edges belonging to each chokepoint corridor — risk is applied to the
# FULL corridor so Dijkstra can meaningfully prefer the alternative path.
# For Suez this means penalising Med_E→Suez→Red Sea→Gulf of Aden as a unit,
# making the Cape of Good Hope detour competitive when risk is high.
CHOKEPOINT_EDGES: dict[str, list[tuple[str, str]]] = {
    "English Channel":   [("_nw_europe", "_channel_e"),
                          ("_channel_e", "_channel_w")],
    "Suez Canal":        [("_med_e",     "_suez_n"),
                          ("_suez_n",    "_suez_s"),
                          ("_suez_s",    "_red_sea_n"),
                          ("_red_sea_n", "_red_sea_s"),
                          ("_red_sea_s", "_gulf_aden")],
    "Strait of Hormuz":  [("_gulf_aden", "_hormuz"),
                          ("_hormuz",    "_arabian_sea")],
    "Singapore Strait":  [("_malacca_w", "_singapore"),
                          ("_singapore", "_scs")],
    "Panama Canal":      [("_panama_pac","_panama_atl"),
                          ("_panama_atl","_caribbean")],
    "Cape of Good Hope": [("_s_atlantic","_cape"),
                          ("_cape",      "_ind_w"),
                          ("_cape",      "_ind_c")],
}

# Flat map: (a,b) → chokepoint name  (both orderings stored)
_EDGE_CHOKEPOINT: dict[tuple[str, str], str] = {}
for _cp, _edges in CHOKEPOINT_EDGES.items():
    for _a, _b in _edges:
        _EDGE_CHOKEPOINT[(_a, _b)] = _cp
        _EDGE_CHOKEPOINT[(_b, _a)] = _cp

# Exclusive nodes — used ONLY for result annotation (detecting which chokepoints
# a route actually passes through).  These are nodes that exist exclusively on
# one chokepoint's path; shared ocean nodes like _ind_c are intentionally omitted.
CHOKEPOINT_NODES: dict[str, list[str]] = {
    "English Channel":   ["_channel_w", "_channel_e"],
    "Suez Canal":        ["_suez_n", "_suez_s", "_red_sea_n", "_red_sea_s"],
    "Strait of Hormuz":  ["_hormuz"],
    "Singapore Strait":  ["_malacca_w", "_singapore"],
    "Panama Canal":      ["_panama_pac", "_panama_atl"],
    "Cape of Good Hope": ["_cape"],
}

CHOKEPOINT_ROUTES = set(CHOKEPOINT_EDGES.keys())

CHOKEPOINT_ROUTES = set(CHOKEPOINT_NODES.keys())

# ── Global maritime backbone ──────────────────────────────────────────────────
# Key ocean waypoints that form the trunk shipping network.
# Each point represents a major maritime junction or crossing.
_WP: dict[str, tuple[float, float]] = {
    "_nw_europe":    (51.5,   3.0),    # North Sea / English Channel east
    "_channel_w":    (49.5,  -5.5),    # English Channel west / Atlantic mouth
    "_channel_e":    (51.0,   2.0),    # English Channel / North Sea junction
    "_n_atlantic":   (45.0,  -30.0),   # North Atlantic crossing
    "_n_atl_w":      (43.0,  -50.0),   # West Atlantic, off the Grand Banks
    "_mid_atl":      (30.0,  -50.0),   # Mid-Atlantic crossing point
    "_s_atlantic":   (-20.0, -25.0),   # South Atlantic
    "_brazil_e":     (-10.0, -34.0),   # NE Brazil offshore (S. Atlantic crossing)
    "_gibraltar":    (35.9,  -5.6),    # Strait of Gibraltar
    "_med_w":        (37.0,   5.0),    # Western Mediterranean
    "_med_c":        (37.0,  14.0),    # Sicily Channel (Med West → Med East)
    "_med_e":        (35.0,  26.0),    # Eastern Mediterranean (south of Crete)
    "_med_se":       (33.0,  29.0),    # SE Mediterranean (Suez approach)
    "_bosphorus":    (41.0,  29.0),    # Bosphorus / Sea of Marmara
    "_black_sea":    (44.0,  35.0),    # Black Sea midpoint
    "_suez_n":       (31.2,  32.3),    # Suez Canal north (Port Said)
    "_suez_s":       (29.5,  32.6),    # Suez Canal south
    "_red_sea_n":    (22.0,  37.0),    # Red Sea (north)
    "_red_sea_s":    (13.0,  43.5),    # Red Sea south / Bab-el-Mandeb
    "_gulf_aden":    (11.5,  45.5),    # Gulf of Aden / Horn of Africa
    "_socotra":      (12.0,  55.0),    # Off Socotra (Aden → Arabian Sea)
    "_hormuz":       (26.2,  56.3),    # Strait of Hormuz
    "_arabian_sea":  (15.0,  63.0),    # Arabian Sea
    "_ind_w":        (0.0,   72.0),    # Western Indian Ocean
    "_seychelles_w": (-10.0, 60.0),    # Mid-Indian Ocean junction
    "_s_madagascar": (-30.0, 50.0),    # South of Madagascar (Cape ↔ Indian Ocean)
    "_ind_c":        (-10.0, 80.0),    # Central Indian Ocean
    "_ind_e":        (-5.0,  93.0),    # Eastern Indian Ocean
    "_andaman":      (8.0,   96.0),    # Andaman Sea (approach to Malacca)
    "_malacca_w":    (5.5,   99.0),    # Malacca Strait west
    "_singapore":    (1.2,  103.8),    # Singapore Strait
    "_scs":          (10.0, 112.0),    # South China Sea
    "_scs_n":        (21.0, 118.0),    # Northern South China Sea (Luzon Strait)
    "_far_east":     (33.0, 126.0),    # Far East junction (Korea / Japan / China)
    "_japan_e":      (38.0, 145.0),    # East of Honshu (avoid clipping Japan)
    "_pac_nw":       (45.0, 165.0),    # NW Pacific (great circle route)
    "_aleutian":     (52.0, 175.0),    # Aleutian arc (great-circle Pacific)
    "_pac_c":        (30.0, 180.0),    # Central Pacific
    "_pac_ne":       (35.0,-145.0),    # NE Pacific
    "_pac_e":        (10.0,-140.0),    # Eastern Pacific
    "_pac_se":       (15.0,-110.0),    # SE Pacific (NE Pacific → Panama bridge)
    "_panama_pac":   (8.0,  -80.0),    # Panama Canal (Pacific side)
    "_panama_atl":   (9.5,  -79.0),    # Panama Canal (Atlantic side)
    "_carib_w":      (15.0, -82.0),    # Caribbean west (south of Cuba)
    "_caribbean":    (15.0, -70.0),    # Caribbean Sea (east basin)
    "_gulf_mex":     (26.0, -90.0),    # Gulf of Mexico
    "_us_east":      (38.0, -73.0),    # US East Coast
    "_us_west":      (34.0,-120.0),    # US West Coast
    "_cape":         (-34.4,  18.5),   # Cape of Good Hope
    "_s_ind":        (-38.0,  60.0),   # Southern Indian Ocean (roaring forties)
    "_s_pac":        (-38.0, 170.0),   # Southern Pacific (Cape Horn area)
}

# Explicit maritime edges — defines the global route network.
# Long spans are threaded through intermediate ocean waypoints so that no
# straight edge crosses a continent on the orthographic globe rendering.
_EDGES: list[tuple[str, str]] = [
    # ── Northern Europe ───────────────────────────────────────────────────────
    ("_nw_europe",  "_channel_e"),
    ("_channel_e",  "_channel_w"),
    ("_channel_w",  "_n_atlantic"),
    ("_nw_europe",  "_n_atlantic"),
    # ── North Atlantic (threaded via _n_atl_w + _mid_atl) ─────────────────────
    ("_n_atlantic", "_n_atl_w"),
    ("_n_atl_w",    "_us_east"),
    ("_n_atlantic", "_mid_atl"),
    ("_mid_atl",    "_caribbean"),
    ("_mid_atl",    "_s_atlantic"),
    ("_n_atlantic", "_gibraltar"),
    # ── Mediterranean / Black Sea ────────────────────────────────────────────
    ("_channel_w",  "_gibraltar"),
    ("_gibraltar",  "_med_w"),
    ("_med_w",      "_med_c"),
    ("_med_c",      "_med_e"),
    ("_med_e",      "_med_se"),
    ("_med_se",     "_suez_n"),
    ("_med_e",      "_bosphorus"),
    ("_bosphorus",  "_black_sea"),
    # ── Suez / Red Sea ───────────────────────────────────────────────────────
    ("_suez_n",     "_suez_s"),
    ("_suez_s",     "_red_sea_n"),
    ("_red_sea_n",  "_red_sea_s"),
    ("_red_sea_s",  "_gulf_aden"),
    # ── Strait of Hormuz branch ───────────────────────────────────────────────
    ("_gulf_aden",  "_socotra"),
    ("_socotra",    "_hormuz"),
    ("_hormuz",     "_arabian_sea"),
    # ── Indian Ocean (threaded via _socotra, _seychelles_w) ──────────────────
    ("_socotra",    "_arabian_sea"),
    ("_arabian_sea","_ind_w"),
    ("_ind_w",      "_seychelles_w"),
    ("_seychelles_w","_ind_c"),
    ("_ind_c",      "_ind_e"),
    ("_ind_e",      "_andaman"),
    ("_andaman",    "_malacca_w"),
    ("_malacca_w",  "_singapore"),
    ("_singapore",  "_scs"),
    ("_scs",        "_scs_n"),
    ("_scs_n",      "_far_east"),
    # ── Far East / Pacific (threaded via _japan_e, _aleutian) ────────────────
    ("_far_east",   "_japan_e"),
    ("_japan_e",    "_pac_nw"),
    ("_pac_nw",     "_aleutian"),
    ("_aleutian",   "_pac_c"),
    ("_pac_c",      "_pac_ne"),
    ("_pac_ne",     "_us_west"),
    ("_pac_ne",     "_pac_se"),
    ("_pac_se",     "_panama_pac"),
    ("_us_west",    "_pac_se"),           # US West Coast offshore to Panama
    # ── Panama Canal ─────────────────────────────────────────────────────────
    ("_panama_pac", "_panama_atl"),
    ("_panama_atl", "_carib_w"),
    ("_carib_w",    "_caribbean"),
    ("_caribbean",  "_us_east"),
    ("_caribbean",  "_gulf_mex"),
    ("_carib_w",    "_gulf_mex"),
    ("_caribbean",  "_brazil_e"),
    ("_brazil_e",   "_s_atlantic"),
    # ── South Atlantic / Cape of Good Hope ────────────────────────────────────
    ("_s_atlantic", "_cape"),
    ("_cape",       "_s_madagascar"),
    ("_s_madagascar","_seychelles_w"),    # Cape → Indian Ocean (Suez alternative)
    ("_cape",       "_s_ind"),
    ("_s_ind",      "_ind_e"),
    # ── Southern Pacific (Cape Horn / roaring forties) ────────────────────────
    ("_s_pac",      "_panama_pac"),
    ("_s_pac",      "_s_atlantic"),
    # ── Shortcuts / alternate paths ───────────────────────────────────────────
    ("_us_east",    "_caribbean"),
    ("_us_east",    "_gulf_mex"),
    ("_gulf_mex",   "_caribbean"),
    ("_scs",        "_far_east"),         # direct SCS → Far East (skip Luzon Str)
    ("_pac_e",      "_pac_se"),
    ("_pac_e",      "_pac_ne"),
    ("_pac_c",      "_pac_e"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    # Calculate distance between two map points.
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))


# ── Graph construction ────────────────────────────────────────────────────────

def build_shipping_graph(
    shipping_routes: dict,
    risk_scores: dict | None = None,
    weather_provider=None,
    chokepoint_queue_penalty: dict[str, float] | None = None,
) -> nx.Graph:
    """
    Build a risk-weighted NetworkX graph of the global maritime route network.

    Inspired by MariNav's cell_visit_graph approach (Vaishnav2804/MariNav):
    nodes represent maritime waypoints and chokepoints; edge weights are
    geographic distance × a risk multiplier derived from TradeWatch's live
    chokepoint risk scores.  When a chokepoint scores high, Dijkstra routes
    traffic around it automatically — the same optimality goal as MariNav's RL agent.

    Args:
        shipping_routes: MAJOR_SHIPPING_ROUTES from config.py (used for
                         chokepoint waypoint coords — labels only, not topology)
        risk_scores: {route_name: 0-100 risk score} from compute_shipping_status()
        weather_provider: optional callable (lat, lon) -> dict with keys
            wind_speed_ms, wind_dir_deg, wave_h_m. When supplied, edge weights
            are additionally multiplied by `vessel_physics.edge_weather_factor`
            and the per-edge metadata (bearing, midpoint, sampled wind/wave)
            is attached to G.edges so downstream fuel calc can reuse it.
    """
    risk_scores = risk_scores or {}
    chokepoint_queue_penalty = chokepoint_queue_penalty or {}
    G = nx.Graph()

    # Add backbone waypoints as nodes
    for node_id, (lat, lon) in _WP.items():
        # Ocean nodes form the main route network.
        G.add_node(node_id, lat=lat, lon=lon, kind="ocean")

    # Build per-edge risk factor — applies to the FULL chokepoint corridor so
    # that Dijkstra can meaningfully compare "Suez shortcut" vs "Cape detour".
    # Inspired by MariNav's per-cell hazard penalty (Vaishnav2804/MariNav).
    # risk 0 → factor 1× (no penalty), risk 100 → factor 8× (heavy penalty)
    def _edge_risk_factor(a: str, b: str) -> float:
        # Increase edge cost when the edge belongs to a risky chokepoint.
        cp = _EDGE_CHOKEPOINT.get((a, b)) or _EDGE_CHOKEPOINT.get((b, a))
        if cp is None:
            return 1.0
        raw = risk_scores.get(cp, 0)
        return 1.0 + (raw / 100.0) * 7.0

    # Add backbone edges with distance × risk weight (× weather factor when
    # a weather_provider is supplied)
    from vessel_physics import (
        EdgeMeta as _EdgeMeta,
        midpoint as _mid,
        bearing as _bearing,
        edge_weather_factor as _wx_factor,
    )

    def _edge_meta(a_lat, a_lon, b_lat, b_lon, a_node, b_node, dist_km):
        m_lat, m_lon = _mid(a_lat, a_lon, b_lat, b_lon)
        brg = _bearing(a_lat, a_lon, b_lat, b_lon)
        wx = weather_provider(m_lat, m_lon) if weather_provider else {}
        return _EdgeMeta(
            a=a_node, b=b_node, dist_km=dist_km,
            mid_lat=m_lat, mid_lon=m_lon, bearing_deg=brg,
            wind_speed_ms=float(wx.get("wind_speed_ms") or 0.0),
            wind_dir_deg=float(wx.get("wind_dir_deg") or 0.0),
            wave_h_m=float(wx.get("wave_h_m") or 0.0),
        )

    # The chokepoint corridor an edge belongs to (None for open-ocean edges).
    # We split the per-corridor queue penalty across all edges in that corridor
    # so the total km bump matches the model's predicted delay end-to-end.
    _corridor_edge_count: dict[str, int] = {}
    for _ab, _cp in _EDGE_CHOKEPOINT.items():
        # _EDGE_CHOKEPOINT stores both (a,b) and (b,a); count each undirected
        # edge once.
        a_, b_ = _ab
        if a_ < b_:
            _corridor_edge_count[_cp] = _corridor_edge_count.get(_cp, 0) + 1

    def _edge_queue_penalty(a: str, b: str) -> float:
        cp = _EDGE_CHOKEPOINT.get((a, b)) or _EDGE_CHOKEPOINT.get((b, a))
        if cp is None or cp not in chokepoint_queue_penalty:
            return 0.0
        n = max(1, _corridor_edge_count.get(cp, 1))
        return float(chokepoint_queue_penalty[cp]) / n

    for (a, b) in _EDGES:
        if a not in _WP or b not in _WP:
            continue
        la, loa = _WP[a]
        lb, lob = _WP[b]
        dist_km = _haversine_km(la, loa, lb, lob)
        factor  = _edge_risk_factor(a, b)
        meta    = _edge_meta(la, loa, lb, lob, a, b, dist_km)
        wx_mult = _wx_factor(meta) if weather_provider else 1.0
        # ML-derived queue penalty for chokepoint-corridor edges. Adds an
        # equivalent-km bump so a congested chokepoint costs literal extra
        # voyage distance (model's predicted delay × speed). Keeps the same
        # "shorter is better" Dijkstra semantics across all three objectives.
        queue_pen = _edge_queue_penalty(a, b)
        # Three named-objective weights are stored on each edge so that
        # `find_optimal_route(..., weight_key=...)` can run Dijkstra under
        # different planner priorities without rebuilding the graph or
        # re-fetching weather. `weight` stays as the balanced default for
        # backwards compatibility.
        balanced = (dist_km + queue_pen) * factor * wx_mult
        fastest  = dist_km + queue_pen                       # ignore risk + weather, but queue still costs time
        safest   = (dist_km + queue_pen) * (factor ** 3) * wx_mult
        G.add_edge(
            a, b,
            weight=balanced,
            weight_balanced=balanced,
            weight_fast=fastest,
            weight_safe=safest,
            dist_km=dist_km,
            queue_penalty_km=queue_pen,
            route="backbone",
            meta=meta,
        )

    # Add major ports as nodes and connect each to its nearest backbone waypoint
    for port_name, (lat, lon) in PORTS.items():
        # Add real ports and connect each one to nearby ocean waypoints.
        node_id = f"_port_{port_name}"
        G.add_node(node_id, lat=lat, lon=lon, kind="port", name=port_name)

        # Connect to two nearest backbone waypoints for redundancy
        dists = sorted(
            ((wp_id, _haversine_km(lat, lon, wlat, wlon))
             for wp_id, (wlat, wlon) in _WP.items()),
            key=lambda x: x[1],
        )
        for wp_id, d in dists[:2]:
            wlat, wlon = _WP[wp_id]
            meta = _edge_meta(lat, lon, wlat, wlon, node_id, wp_id, d)
            wx_mult = _wx_factor(meta) if weather_provider else 1.0
            base_w = d * wx_mult
            G.add_edge(
                node_id, wp_id,
                weight=base_w,
                weight_balanced=base_w,
                weight_fast=d,
                weight_safe=base_w,         # port access has no chokepoint risk
                dist_km=d,
                route="port_access",
                meta=meta,
            )

    return G


# ── Route finding ─────────────────────────────────────────────────────────────

def _summarise_path(path: list[str], G: nx.Graph, origin: str, destination: str,
                    total_weighted: float) -> dict:
    """Shared helper: turn a node-id path into the canonical result dict."""
    # Convert graph node IDs into coordinates and display data for the UI.
    path_coords = [(G.nodes[n]["lat"], G.nodes[n]["lon"]) for n in path]

    total_dist_km = sum(
        G[path[i]][path[i + 1]].get(
            "dist_km",
            _haversine_km(G.nodes[path[i]]["lat"],  G.nodes[path[i]]["lon"],
                          G.nodes[path[i+1]]["lat"], G.nodes[path[i+1]]["lon"]))
        for i in range(len(path) - 1)
    )

    path_set = set(path)
    chokepoints_used = [
        route for route, nodes in CHOKEPOINT_NODES.items()
        if any(n in path_set for n in nodes)
    ]

    route_segments: dict[str, int] = {}
    for node in path:
        if G.nodes[node].get("kind", "ocean") == "port":
            continue
        label = "Open Ocean"
        for route, nodes in CHOKEPOINT_NODES.items():
            if node in nodes:
                label = route
                break
        route_segments[label] = route_segments.get(label, 0) + 1

    path_edges = [G[path[i]][path[i + 1]].get("meta") for i in range(len(path) - 1)]

    return {
        "path":               path,
        "path_coords":        path_coords,
        "path_edges":         path_edges,
        "total_dist_km":      round(total_dist_km),
        "total_weighted_km":  round(total_weighted),
        "route_segments":     dict(sorted(route_segments.items(), key=lambda x: -x[1])),
        "chokepoints_used":   chokepoints_used,
        "origin":             origin,
        "destination":        destination,
        "origin_coords":      PORTS[origin],
        "destination_coords": PORTS[destination],
        "node_count":         len(path),
    }


def find_optimal_route(
    origin: str,
    destination: str,
    G: nx.Graph,
    risk_scores: dict | None = None,
    weight_key: str = "weight",
) -> dict:
    """
    Find the lowest-cost maritime route between two ports using Dijkstra.

    `weight_key` selects the objective: "weight" / "weight_balanced" (default)
    optimises distance × risk × weather; "weight_fast" ignores risk + weather
    (pure shortest distance); "weight_safe" applies a cubic risk penalty.

    Returns a result dict or {"error": str} on failure.
    """
    if origin not in PORTS:
        return {"error": f"Unknown port: {origin}"}
    if destination not in PORTS:
        return {"error": f"Unknown port: {destination}"}
    if origin == destination:
        return {"error": "Origin and destination must differ"}

    orig_node = f"_port_{origin}"
    dest_node = f"_port_{destination}"

    if orig_node not in G or dest_node not in G:
        return {"error": "Port not found in routing graph"}

    try:
        path = nx.shortest_path(G, orig_node, dest_node, weight=weight_key)
        total_weighted = nx.shortest_path_length(G, orig_node, dest_node,
                                                 weight=weight_key)
    except nx.NetworkXNoPath:
        return {"error": "No connected route found between these ports"}

    return _summarise_path(path, G, origin, destination, total_weighted)


# ── Route economics: shared by alternatives + page UI ────────────────────────

def _route_total_cost_usd(
    result: dict,
    vessel,
    speed_kn: float,
    bunker_usd_per_t: float,
    opex_per_day: float,
    risk_scores: dict,
) -> dict:
    """Compute fuel + risk surcharge + canal toll + opex for a route.

    Returns a dict with `fuel_usd`, `risk_surcharge_usd`, `toll_usd`,
    `opex_usd`, `total_usd`, `voyage_days`, `fuel_t`, `max_chokepoint_risk`.
    Used both for ranking the Cheapest alternative and for displaying the
    economics breakdown on each comparison card.
    """
    from vessel_physics import voyage_totals as _voyage_totals
    from canal_tolls import estimate_toll_usd as _estimate_toll_usd

    edges = [e for e in result.get("path_edges", []) or [] if e is not None]
    if edges:
        # Use per-edge vessel physics when edge metadata is available.
        det = _voyage_totals(vessel, edges, speed_kn)
        days = det["days"]
        fuel_t = det["fuel_t"]
    else:
        days = result["total_dist_km"] / max(0.01, speed_kn * 1.852 * 24)
        fuel_t = vessel.fuel_tpd(speed_kn) * days

    fuel_usd = fuel_t * bunker_usd_per_t

    max_risk = max(
        (risk_scores.get(cp, 0) for cp in result.get("chokepoints_used", [])),
        default=0,
    )
    surcharge_pct = max_risk / 400.0       # same formula as the existing page
    risk_surcharge_usd = fuel_usd * surcharge_pct

    toll_usd = 0.0
    for cp in result.get("chokepoints_used", []):
        # Add canal tolls only for routes that use Suez or Panama.
        canal = "suez" if "Suez" in cp else "panama" if "Panama" in cp else None
        if canal:
            t = _estimate_toll_usd(canal, vessel.name)
            if t is not None:
                toll_usd += t

    opex_usd = days * opex_per_day
    total_usd = fuel_usd + risk_surcharge_usd + toll_usd + opex_usd

    return {
        "fuel_t":              fuel_t,
        "voyage_days":         days,
        "fuel_usd":            fuel_usd,
        "risk_surcharge_usd":  risk_surcharge_usd,
        "toll_usd":            toll_usd,
        "opex_usd":            opex_usd,
        "total_usd":           total_usd,
        "max_chokepoint_risk": max_risk,
        "surcharge_pct":       surcharge_pct,
    }


# ── Multi-objective alternatives ─────────────────────────────────────────────

# Three named alternatives — Recommended is *derived* from these three by
# composite scoring on (ML-ETA, cost, risk), not run as a separate Dijkstra.
# Display order is preserved by `find_route_alternatives`.
ROUTE_OBJECTIVES: list[dict] = [
    {
        "key":      "fastest",
        "label":    "Fastest",
        "tagline":  "Least time on the water",
        "color":    "#f97316",   # orange
        "icon":     "⏱",
        "weight":   "weight_fast_h",
    },
    {
        "key":      "safest",
        "label":    "Safest",
        "tagline":  "Hard-avoid risky chokepoints",
        "color":    "#22c55e",   # green
        "icon":     "🛡",
        "weight":   "weight_safe_stepped",
    },
    {
        "key":      "cheapest",
        "label":    "Cheapest",
        "tagline":  "Lowest total dollars incl. tolls",
        "color":    "#a855f7",   # purple
        "icon":     "💰",
        "weight":   "weight_cheap_usd",
    },
]


# Stepped risk multiplier — mirrors the chokepoint status thresholds in
# `dynamic_status.py:197-212`. Soft cubic penalties couldn't overcome a
# 10,500 km Cape detour at moderate risk; these are sharp enough that
# Safest actually detours when a real disruption is reported.
def _safe_step_factor(risk_score: float) -> float:
    if risk_score >= 70:  return 10_000.0   # Critical — effectively forbidden
    if risk_score >= 40:  return 1_000.0    # High Risk — forbidden unless no alt
    if risk_score >= 15:  return 5.0        # Alert — penalised
    return 1.0                              # Operational — no penalty


# Edges that contribute the FULL canal toll to the Cheapest objective. Any
# Suez-using path crosses (_suez_n, _suez_s); any Panama-using path crosses
# (_panama_pac, _panama_atl). Putting the toll on one interior edge per canal
# (not split across the corridor) keeps the math simple: cheapest sees
# "toll vs extra fuel + extra OPEX of Cape detour" as a binary decision.
_CANAL_INTERIOR_EDGES: dict[tuple[str, str], str] = {
    ("_suez_n", "_suez_s"):       "suez",
    ("_suez_s", "_suez_n"):       "suez",
    ("_panama_pac", "_panama_atl"): "panama",
    ("_panama_atl", "_panama_pac"): "panama",
}


def _apply_objective_weights(
    G: nx.Graph,
    risk_scores: dict,
    vessel,
    speed_kn: float,
    bunker_usd_per_t: float,
    opex_per_day: float,
) -> None:
    """Mutates G in place: writes the three objective weights onto every edge.

    Called once per `find_route_alternatives()` invocation — the weights
    depend on the specific vessel/speed/bunker so they can't be baked into
    `build_shipping_graph()` (which is shared across vessel choices).

    Writes:
      weight_fast_h        — voyage hours per edge (weather-aware, risk-blind)
      weight_safe_stepped  — distance × stepped-risk factor (1 / 5 / 1000 / 10000)
      weight_cheap_usd     — fuel + OPEX + risk-surcharge + canal toll, in USD
    """
    from vessel_physics import fuel_for_edge as _fuel_for_edge
    from canal_tolls import estimate_toll_usd as _estimate_toll_usd

    risk_scores = risk_scores or {}
    # Toll lookup cached per canal so we don't re-call into canal_tolls per edge.
    _canal_toll_usd: dict[str, float] = {}
    for canal in {"suez", "panama"}:
        t = _estimate_toll_usd(canal, vessel.name)
        _canal_toll_usd[canal] = float(t) if t is not None else 0.0

    speed_kmh = max(0.01, float(speed_kn) * 1.852)

    for a, b, data in G.edges(data=True):
        # Write all objective weights onto each edge for later Dijkstra runs.
        meta = data.get("meta")
        dist_km = float(data.get("dist_km", 0.0))
        queue_pen = float(data.get("queue_penalty_km", 0.0))

        # ── weight_fast_h: voyage hours, weather-aware, no risk.
        if meta is not None:
            try:
                edge_det = _fuel_for_edge(vessel, meta, speed_kn)
                edge_hours = float(edge_det.get("hours", dist_km / speed_kmh))
            except Exception:  # noqa: BLE001  fall back to flat distance/speed
                edge_hours = dist_km / speed_kmh
        else:
            edge_hours = dist_km / speed_kmh
        # Queue penalty was expressed in km — convert to hours at service speed.
        weight_fast_h = edge_hours + (queue_pen / speed_kmh)

        # ── weight_safe_stepped: hard-avoid risky chokepoints.
        cp = _EDGE_CHOKEPOINT.get((a, b)) or _EDGE_CHOKEPOINT.get((b, a))
        risk_for_edge = risk_scores.get(cp, 0) if cp else 0
        weight_safe_stepped = (dist_km + queue_pen) * _safe_step_factor(risk_for_edge)

        # ── weight_cheap_usd: real per-edge dollars.
        # Fuel from vessel physics (already weather-aware); OPEX from edge_hours;
        # risk surcharge proportional to fuel × edge-chokepoint-risk; canal toll
        # applied once on each canal's interior edge.
        if meta is not None:
            try:
                edge_det = _fuel_for_edge(vessel, meta, speed_kn)
                edge_fuel_t = float(edge_det.get("fuel_t", 0.0))
            except Exception:  # noqa: BLE001
                edge_fuel_t = float(vessel.fuel_tpd(speed_kn)) * (edge_hours / 24.0)
        else:
            edge_fuel_t = float(vessel.fuel_tpd(speed_kn)) * (edge_hours / 24.0)
        edge_fuel_usd = edge_fuel_t * float(bunker_usd_per_t)
        edge_opex_usd = (edge_hours / 24.0) * float(opex_per_day)
        # Per-edge risk surcharge — matches the post-hoc formula's intent
        # (fuel × max_risk/400) but allocated per edge so Dijkstra sees the
        # signal directly. Routes touching a high-risk chokepoint see fuel ×
        # (cp_risk / 400) on the in-corridor edges only.
        edge_risk_surcharge_usd = edge_fuel_usd * (risk_for_edge / 400.0)
        # Canal toll: applied once, on the canal's interior edge.
        toll_usd = 0.0
        canal = _CANAL_INTERIOR_EDGES.get((a, b))
        if canal:
            toll_usd = _canal_toll_usd.get(canal, 0.0)
        weight_cheap_usd = edge_fuel_usd + edge_opex_usd + edge_risk_surcharge_usd + toll_usd

        data["weight_fast_h"]       = weight_fast_h
        data["weight_safe_stepped"] = weight_safe_stepped
        data["weight_cheap_usd"]    = weight_cheap_usd


def _composite_score(
    alt: dict, mins: dict, ranges: dict
) -> float:
    """Normalised composite — lowest wins. Each metric is z-scored over the
    three named alternatives so they're equal-weighted regardless of units."""
    def _z(value: float, m: str) -> float:
        r = ranges.get(m, 0.0)
        return ((value - mins[m]) / r) if r > 1e-9 else 0.0
    eta_h = float(alt.get("ml_eta_h") or 0.0)
    cost  = float(alt["economics"]["total_usd"])
    risk  = float(alt["economics"]["max_chokepoint_risk"])
    return _z(eta_h, "eta_h") + _z(cost, "cost") + _z(risk, "risk")


def find_route_alternatives(
    origin: str,
    destination: str,
    G: nx.Graph,
    risk_scores: dict,
    vessel,
    speed_kn: float,
    bunker_usd_per_t: float,
    opex_per_day: float,
    ml_eta_h_for: callable | None = None,
) -> list[dict]:
    """Return three named route alternatives (Fastest, Safest, Cheapest),
    one of which is flagged as Recommended via composite scoring on
    (ML-ETA, total USD, max chokepoint risk).

    Each alternative is one Dijkstra under its own per-edge weight (set by
    `_apply_objective_weights` above): voyage hours, stepped risk multiplier,
    and per-edge USD respectively. Recommended is then *derived* — no fourth
    Dijkstra. This guarantees the three are genuinely different and the
    Recommended choice can be explained by name vs. the other two.

    `ml_eta_h_for(alt) -> float | None` is an optional callback: given an
    alternative dict (with `chokepoints_used`, `total_dist_km`, etc.) returns
    the ML-predicted total transit time in hours. When None, composite
    scoring falls back to physics `voyage_days` from `economics`.
    """
    if origin not in PORTS or destination not in PORTS:
        return [{"error": f"Unknown port: {origin if origin not in PORTS else destination}"}]
    if origin == destination:
        return [{"error": "Origin and destination must differ"}]

    orig_node = f"_port_{origin}"
    dest_node = f"_port_{destination}"
    risk_scores = risk_scores or {}

    # Compute the per-edge objective weights for this vessel/speed/economics
    # snapshot. Cheap to do once before the three Dijkstras run.
    _apply_objective_weights(G, risk_scores, vessel, speed_kn,
                             bunker_usd_per_t, opex_per_day)

    out: list[dict] = []

    def _runner_up_for(weight_key: str, winning_path: list[str]) -> dict | None:
        """Best topologically-distinct alternative path under `weight_key`."""
        winning_cps = frozenset(_summarise_path(
            winning_path, G, origin, destination, 0.0)["chokepoints_used"])
        first_alt: dict | None = None
        try:
            paths_iter = nx.shortest_simple_paths(G, orig_node, dest_node,
                                                  weight=weight_key)
            for idx, candidate in enumerate(paths_iter):
                if idx >= 25:
                    break
                if candidate == winning_path:
                    continue
                cand_total = sum(
                    G[candidate[i]][candidate[i + 1]].get(weight_key, 0)
                    for i in range(len(candidate) - 1)
                )
                summary = _summarise_path(candidate, G, origin, destination,
                                          cand_total)
                summary["economics"] = _route_total_cost_usd(
                    summary, vessel, speed_kn, bunker_usd_per_t,
                    opex_per_day, risk_scores,
                )
                cand_cps = frozenset(summary["chokepoints_used"])
                if cand_cps != winning_cps:
                    return summary
                if first_alt is None:
                    first_alt = summary
        except (nx.NetworkXNoPath, nx.NetworkXError):
            return None
        return first_alt

    # ── One Dijkstra per objective ──────────────────────────────────────────
    for objective in ROUTE_OBJECTIVES:
        # Run one shortest-path search for each route objective.
        result = find_optimal_route(origin, destination, G, risk_scores,
                                     weight_key=objective["weight"])
        if "error" in result:
            continue
        result["objective"] = objective["key"]
        result["label"]     = objective["label"]
        result["tagline"]   = objective["tagline"]
        result["color"]     = objective["color"]
        result["icon"]      = objective["icon"]
        result["economics"] = _route_total_cost_usd(
            result, vessel, speed_kn, bunker_usd_per_t, opex_per_day, risk_scores,
        )
        # ML ETA in hours — used both for composite scoring and for the
        # ETA-anchored trade-vs-others line in the UI. Caller-injected so the
        # router stays free of eta_model imports.
        result["ml_eta_h"] = None
        if ml_eta_h_for is not None:
            try:
                result["ml_eta_h"] = float(ml_eta_h_for(result))
            except Exception:  # noqa: BLE001  ETA failure must not block routing
                result["ml_eta_h"] = None
        result["runner_up"] = _runner_up_for(objective["weight"], result["path"])
        out.append(result)

    if not out:
        return out

    # ── Convergence detection — alternatives sharing the same node path
    # get the same `convergence_group`. The UI uses a single value across
    # all alternatives as the trigger for the "all three converged" banner.
    group_of: dict[tuple[str, ...], int] = {}
    for alt in out:
        pt = tuple(alt["path"])
        if pt not in group_of:
            group_of[pt] = len(group_of)
        alt["convergence_group"] = group_of[pt]

    # ── Composite scoring — pick Recommended from the three. Falls back to
    # physics voyage_days when ml_eta_h isn't available (model artifact missing
    # or callback raised).
    def _alt_eta_h(alt: dict) -> float:
        if alt.get("ml_eta_h") is not None:
            return float(alt["ml_eta_h"])
        # voyage_days from physics — × 24 to express in hours so the mixed
        # case (some alts have ML, some don't) still uses comparable units.
        return float(alt["economics"].get("voyage_days", 0.0)) * 24.0

    for alt in out:
        alt["_eta_h_for_score"] = _alt_eta_h(alt)
    mins = {
        "eta_h": min(a["_eta_h_for_score"] for a in out),
        "cost":  min(a["economics"]["total_usd"] for a in out),
        "risk":  min(a["economics"]["max_chokepoint_risk"] for a in out),
    }
    maxs = {
        "eta_h": max(a["_eta_h_for_score"] for a in out),
        "cost":  max(a["economics"]["total_usd"] for a in out),
        "risk":  max(a["economics"]["max_chokepoint_risk"] for a in out),
    }
    ranges = {m: maxs[m] - mins[m] for m in mins}

    def _z(value: float, m: str) -> float:
        r = ranges.get(m, 0.0)
        return ((value - mins[m]) / r) if r > 1e-9 else 0.0

    for alt in out:
        alt["composite_score"] = (
            _z(alt["_eta_h_for_score"],                m="eta_h")
            + _z(alt["economics"]["total_usd"],         m="cost")
            + _z(alt["economics"]["max_chokepoint_risk"], m="risk")
        )

    # ── Vs-alternatives deltas + recommendation pick + rationale.
    rec = min(out, key=lambda a: a["composite_score"])
    rec_idx = out.index(rec)
    rec_eta_h  = rec["_eta_h_for_score"]
    rec_cost   = rec["economics"]["total_usd"]
    rec_risk   = rec["economics"]["max_chokepoint_risk"]
    rec_days   = rec["economics"]["voyage_days"]

    for alt in out:
        alt["is_recommended"] = (alt is rec)
        alt["vs_alternatives"] = {
            other["objective"]: {
                "d_eta_h":  alt["_eta_h_for_score"] - other["_eta_h_for_score"],
                "d_cost":   alt["economics"]["total_usd"] - other["economics"]["total_usd"],
                "d_risk":   alt["economics"]["max_chokepoint_risk"] - other["economics"]["max_chokepoint_risk"],
                "d_days":   alt["economics"]["voyage_days"] - other["economics"]["voyage_days"],
            }
            for other in out if other is not alt
        }
        # Cosmetic field used by the UI; not part of scoring.
        alt["delta_vs_recommended"] = {
            "d_eta_h": alt["_eta_h_for_score"]                - rec_eta_h,
            "d_cost":  alt["economics"]["total_usd"]          - rec_cost,
            "d_risk":  alt["economics"]["max_chokepoint_risk"] - rec_risk,
            "d_days":  alt["economics"]["voyage_days"]        - rec_days,
        }

    # Build a recommendation reason in plain English. When all 3 converge
    # the reason is a single sentence; when they diverge, it names the
    # losers' tradeoffs explicitly.
    all_same_path = len(set(alt["convergence_group"] for alt in out)) == 1
    if all_same_path:
        reason = (
            f"All three objectives converged on the same route — same ML-ETA, "
            f"same cost, same risk. See \"Why this is the only choice\" below "
            f"for the runner-up Cape of Good Hope detour we evaluated."
        )
    else:
        losers = [a for a in out if a is not rec]
        bits = []
        for L in losers:
            d_eta_h  = L["_eta_h_for_score"]                 - rec_eta_h
            d_cost   = L["economics"]["total_usd"]           - rec_cost
            d_risk   = L["economics"]["max_chokepoint_risk"] - rec_risk
            bits.append(
                f"{L['label']} adds {d_eta_h:+.1f}h, ${d_cost/1000:+,.0f}k, "
                f"{d_risk:+.0f} risk"
            )
        reason = f"{rec['label']} wins on composite score · " + " · ".join(bits)
    rec["recommendation_reason"] = reason
    for alt in out:
        if alt is not rec:
            alt["recommendation_reason"] = ""

    # Clean up internal scratch field before returning.
    for alt in out:
        alt.pop("_eta_h_for_score", None)

    return out
