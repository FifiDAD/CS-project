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
    "_s_atlantic":   (-20.0, -25.0),   # South Atlantic
    "_gibraltar":    (35.9,  -5.6),    # Strait of Gibraltar
    "_med_w":        (37.0,   5.0),    # Western Mediterranean
    "_med_e":        (35.0,  28.0),    # Eastern Mediterranean
    "_suez_n":       (31.2,  32.3),    # Suez Canal north (Port Said)
    "_suez_s":       (29.5,  32.6),    # Suez Canal south
    "_red_sea_n":    (22.0,  37.0),    # Red Sea (north)
    "_red_sea_s":    (13.0,  43.5),    # Red Sea south / Bab-el-Mandeb
    "_gulf_aden":    (11.5,  45.5),    # Gulf of Aden / Horn of Africa
    "_hormuz":       (26.2,  56.3),    # Strait of Hormuz
    "_arabian_sea":  (15.0,  63.0),    # Arabian Sea
    "_ind_w":        (0.0,   72.0),    # Western Indian Ocean
    "_ind_c":        (-10.0, 80.0),    # Central Indian Ocean
    "_ind_e":        (-5.0,  93.0),    # Eastern Indian Ocean
    "_malacca_w":    (5.5,   99.0),    # Malacca Strait west
    "_singapore":    (1.2,  103.8),    # Singapore Strait
    "_scs":          (10.0, 112.0),    # South China Sea
    "_scs_n":        (21.0, 118.0),    # Northern South China Sea (Luzon Strait)
    "_far_east":     (33.0, 126.0),    # Far East junction (Korea / Japan / China)
    "_pac_nw":       (45.0, 165.0),    # NW Pacific (great circle route)
    "_pac_c":        (30.0, 180.0),    # Central Pacific
    "_pac_ne":       (35.0,-145.0),    # NE Pacific
    "_pac_e":        (10.0,-140.0),    # Eastern Pacific
    "_panama_pac":   (8.0,  -80.0),    # Panama Canal (Pacific side)
    "_panama_atl":   (9.5,  -79.0),    # Panama Canal (Atlantic side)
    "_caribbean":    (15.0,  -70.0),   # Caribbean Sea
    "_gulf_mex":     (26.0,  -90.0),   # Gulf of Mexico
    "_us_east":      (38.0,  -73.0),   # US East Coast
    "_us_west":      (34.0, -120.0),   # US West Coast
    "_cape":         (-34.4,  18.5),   # Cape of Good Hope
    "_s_ind":        (-38.0,  60.0),   # Southern Indian Ocean (roaring forties)
    "_s_pac":        (-38.0, 170.0),   # Southern Pacific (Cape Horn area)
}

# Explicit maritime edges — defines the global route network.
# Inspired by MariNav's graph connectivity approach (Vaishnav2804/MariNav).
_EDGES: list[tuple[str, str]] = [
    # ── Northern Europe ───────────────────────────────────────────────────────
    ("_nw_europe",  "_channel_e"),
    ("_channel_e",  "_channel_w"),
    ("_channel_w",  "_n_atlantic"),
    ("_nw_europe",  "_n_atlantic"),       # direct North Atlantic access
    # ── North Atlantic ────────────────────────────────────────────────────────
    ("_n_atlantic", "_us_east"),
    ("_n_atlantic", "_caribbean"),
    ("_n_atlantic", "_s_atlantic"),
    ("_n_atlantic", "_gibraltar"),
    # ── Mediterranean ─────────────────────────────────────────────────────────
    ("_channel_w",  "_gibraltar"),
    ("_gibraltar",  "_med_w"),
    ("_med_w",      "_med_e"),
    ("_med_e",      "_suez_n"),
    ("_suez_n",     "_suez_s"),
    ("_suez_s",     "_red_sea_n"),
    ("_red_sea_n",  "_red_sea_s"),
    ("_red_sea_s",  "_gulf_aden"),
    # ── Strait of Hormuz branch ───────────────────────────────────────────────
    ("_gulf_aden",  "_hormuz"),
    ("_hormuz",     "_arabian_sea"),
    # ── Indian Ocean ──────────────────────────────────────────────────────────
    ("_gulf_aden",  "_arabian_sea"),
    ("_arabian_sea","_ind_w"),
    ("_ind_w",      "_ind_c"),
    ("_ind_c",      "_ind_e"),
    ("_ind_e",      "_malacca_w"),
    ("_malacca_w",  "_singapore"),
    ("_singapore",  "_scs"),
    ("_scs",        "_scs_n"),
    ("_scs_n",      "_far_east"),
    # ── Far East / Pacific ────────────────────────────────────────────────────
    ("_far_east",   "_pac_nw"),
    ("_pac_nw",     "_pac_c"),
    ("_pac_c",      "_pac_ne"),
    ("_pac_ne",     "_us_west"),
    ("_pac_ne",     "_panama_pac"),
    ("_us_west",    "_panama_pac"),       # direct US West Coast to Panama
    # ── Panama Canal ─────────────────────────────────────────────────────────
    ("_panama_pac", "_panama_atl"),
    ("_panama_atl", "_caribbean"),
    ("_caribbean",  "_us_east"),
    ("_caribbean",  "_gulf_mex"),
    ("_caribbean",  "_s_atlantic"),
    # ── South Atlantic / Cape of Good Hope ────────────────────────────────────
    ("_s_atlantic", "_cape"),
    ("_cape",       "_ind_w"),            # Cape → Indian Ocean (Suez alternative)
    ("_cape",       "_ind_c"),
    ("_cape",       "_s_ind"),
    ("_s_ind",      "_ind_e"),
    # ── Southern Pacific (Cape Horn / roaring forties) ────────────────────────
    ("_s_pac",      "_panama_pac"),
    ("_s_pac",      "_s_atlantic"),
    # ── Shortcuts / alternate paths ───────────────────────────────────────────
    ("_arabian_sea","_ind_c"),            # direct Arabian Sea → mid Indian Ocean
    ("_us_east",    "_caribbean"),
    ("_us_east",    "_gulf_mex"),
    ("_gulf_mex",   "_caribbean"),
    ("_scs",        "_far_east"),         # direct SCS → Far East (skip Luzon Str)
    ("_pac_e",      "_panama_pac"),
    ("_pac_e",      "_pac_ne"),
    ("_pac_c",      "_pac_e"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
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
    """
    risk_scores = risk_scores or {}
    G = nx.Graph()

    # Add backbone waypoints as nodes
    for node_id, (lat, lon) in _WP.items():
        G.add_node(node_id, lat=lat, lon=lon, kind="ocean")

    # Build per-edge risk factor — applies to the FULL chokepoint corridor so
    # that Dijkstra can meaningfully compare "Suez shortcut" vs "Cape detour".
    # Inspired by MariNav's per-cell hazard penalty (Vaishnav2804/MariNav).
    # risk 0 → factor 1× (no penalty), risk 100 → factor 8× (heavy penalty)
    def _edge_risk_factor(a: str, b: str) -> float:
        cp = _EDGE_CHOKEPOINT.get((a, b)) or _EDGE_CHOKEPOINT.get((b, a))
        if cp is None:
            return 1.0
        raw = risk_scores.get(cp, 0)
        return 1.0 + (raw / 100.0) * 7.0

    # Add backbone edges with distance × risk weight
    for (a, b) in _EDGES:
        if a not in _WP or b not in _WP:
            continue
        la, loa = _WP[a]
        lb, lob = _WP[b]
        dist_km = _haversine_km(la, loa, lb, lob)
        factor  = _edge_risk_factor(a, b)
        G.add_edge(a, b, weight=dist_km * factor,
                   dist_km=dist_km, route="backbone")

    # Add major ports as nodes and connect each to its nearest backbone waypoint
    for port_name, (lat, lon) in PORTS.items():
        node_id = f"_port_{port_name}"
        G.add_node(node_id, lat=lat, lon=lon, kind="port", name=port_name)

        # Connect to two nearest backbone waypoints for redundancy
        dists = sorted(
            ((wp_id, _haversine_km(lat, lon, wlat, wlon))
             for wp_id, (wlat, wlon) in _WP.items()),
            key=lambda x: x[1],
        )
        for wp_id, d in dists[:2]:
            G.add_edge(node_id, wp_id, weight=d * 1.0,
                       dist_km=d, route="port_access")

    return G


# ── Route finding ─────────────────────────────────────────────────────────────

def find_optimal_route(
    origin: str,
    destination: str,
    G: nx.Graph,
    risk_scores: dict | None = None,
) -> dict:
    """
    Find the lowest-risk maritime route using Dijkstra's algorithm.

    Inspired by MariNav's shortest-path baseline (Vaishnav2804/MariNav).
    Risk-weighted edges cause Dijkstra to naturally avoid high-risk chokepoints —
    e.g. if the Suez Canal risk score is 80/100, the algorithm may route via
    the Cape of Good Hope despite the extra ~3,000 km.

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
        path = nx.shortest_path(G, orig_node, dest_node, weight="weight")
        total_weighted = nx.shortest_path_length(G, orig_node, dest_node,
                                                 weight="weight")
    except nx.NetworkXNoPath:
        return {"error": "No connected route found between these ports"}

    # Build coordinate list from path nodes
    path_coords: list[tuple[float, float]] = []
    for node in path:
        d = G.nodes[node]
        path_coords.append((d["lat"], d["lon"]))

    # Actual geographic distance (ignoring risk weights)
    total_dist_km = sum(
        G[path[i]][path[i + 1]].get("dist_km",
            _haversine_km(G.nodes[path[i]]["lat"],  G.nodes[path[i]]["lon"],
                          G.nodes[path[i+1]]["lat"], G.nodes[path[i+1]]["lon"]))
        for i in range(len(path) - 1)
    )

    # Identify chokepoints that appear in path
    path_set = set(path)
    chokepoints_used = [
        route for route, nodes in CHOKEPOINT_NODES.items()
        if any(n in path_set for n in nodes)
    ]

    # Identify which backbone segments are used
    route_segments: dict[str, int] = {}
    for node in path:
        kind = G.nodes[node].get("kind", "ocean")
        if kind == "port":
            continue
        # Map backbone node to chokepoint label if applicable
        label = "Open Ocean"
        for route, nodes in CHOKEPOINT_NODES.items():
            if node in nodes:
                label = route
                break
        route_segments[label] = route_segments.get(label, 0) + 1

    return {
        "path":               path,
        "path_coords":        path_coords,
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
