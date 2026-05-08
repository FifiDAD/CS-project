"""UI Components — TradeWatch shipping intelligence dashboard"""

import streamlit as st
import pandas as pd
from config import EVENT_TYPES, IMPACT_LEVELS

# ── Shared constants ──────────────────────────────────────────────────────────

STATUS_COLORS = {
    "Operational":              "#00CC44",
    "Operational - Alert":      "#FFD700",
    "Operational - High Risk":  "#FF8C00",
    "Critical - Avoid":         "#FF2222",
}
STATUS_BG = {
    "Operational":              "rgba(0,204,68,0.12)",
    "Operational - Alert":      "rgba(255,215,0,0.12)",
    "Operational - High Risk":  "rgba(255,140,0,0.12)",
    "Critical - Avoid":         "rgba(255,34,34,0.12)",
}
STATUS_EMOJI = {
    "Operational":              "🟢",
    "Operational - Alert":      "🟡",
    "Operational - High Risk":  "🟠",
    "Critical - Avoid":         "🔴",
}

# Route → nearest monitored port (for wind/weather data on cards)
ROUTE_PORT_MAP = {
    "Suez Canal":        "Port Said",
    "Strait of Hormuz":  "Dubai",
    "Singapore Strait":  "Singapore",
    "Panama Canal":      None,
    "English Channel":   "Rotterdam",
    "Cape of Good Hope": None,
}


def _risk_score_color(score: int) -> str:
    if score >= 70:   return "#FF2222"
    if score >= 40:   return "#FF8C00"
    if score >= 15:   return "#FFD700"
    return "#00CC44"


def _hours_since(when) -> float:
    """Hours between `when` and now (UTC). Handles tz-naive and tz-aware inputs."""
    ts = pd.Timestamp(when)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return (pd.Timestamp.now(tz="UTC") - ts).total_seconds() / 3600


# ── Route Intelligence Card ───────────────────────────────────────────────────

def render_route_card(row: pd.Series, selected_route: str | None, port_cong_df: pd.DataFrame | None = None) -> None:
    """Render a single chokepoint intelligence card below the globe."""
    route      = row["Route"]
    status     = row["Status"]
    risk_score = int(row["Risk Score"])
    delay      = row["Average Delay"]
    cost       = row["Cost Impact"]
    events_nb  = row["Nearby Events"]

    sc   = STATUS_COLORS.get(status, "#888888")
    sbg  = STATUS_BG.get(status, "rgba(128,128,128,0.1)")
    emoji = STATUS_EMOJI.get(status, "⚪")
    rscolor = _risk_score_color(risk_score)

    # Highlight selected route with accent border
    selected = selected_route == route
    outer_border = "2px solid #2e7fff" if selected else f"1px solid #1a3a6c"

    # Wind data from nearest port
    wind_html = ""
    nearest_port = ROUTE_PORT_MAP.get(route)
    if nearest_port and port_cong_df is not None and len(port_cong_df) > 0:
        port_row = port_cong_df[port_cong_df["Port"] == nearest_port]
        if len(port_row) > 0:
            wind_ms = port_row.iloc[0].get("Wind (m/s)", 0)
            w_alert = port_row.iloc[0].get("Weather Alert", "✅ No")
            warn = "⚠️ " if "Yes" in str(w_alert) else ""
            wind_html = f'<div style="font-size:0.72em;color:#6b9cc4;margin-top:4px">{warn}Wind {wind_ms} m/s · {nearest_port}</div>'

    card_html = f"""
<div style="
  background:#040e22;
  border:{outer_border};
  border-top:3px solid {sc};
  border-radius:10px;
  padding:12px 10px;
  margin-bottom:4px;
  min-height:140px;
">
  <div style="font-size:0.7em;font-weight:700;letter-spacing:0.08em;
              text-transform:uppercase;color:#6b9cc4;margin-bottom:6px">
    {emoji} {route}
  </div>
  <div style="font-size:1.5em;font-weight:700;color:{rscolor};line-height:1">
    {risk_score}<span style="font-size:0.5em;color:#6b9cc4">/100</span>
  </div>
  <div style="font-size:0.65em;color:#6b9cc4;margin-bottom:8px">Risk Score</div>
  <div style="
    background:{sbg};
    border:1px solid {sc};
    border-radius:20px;
    padding:2px 8px;
    display:inline-block;
    font-size:0.65em;
    font-weight:600;
    color:{sc};
    margin-bottom:8px;
  ">{status}</div>
  <div style="border-top:1px solid #1a3a6c;padding-top:8px;margin-top:4px">
    <div style="display:flex;justify-content:space-between;font-size:0.72em;margin:2px 0">
      <span style="color:#6b9cc4">Delay</span>
      <span style="color:#e8f4ff;font-weight:600">{delay}</span>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:0.72em;margin:2px 0">
      <span style="color:#6b9cc4">Cost</span>
      <span style="color:#e8f4ff;font-weight:600">{cost}</span>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:0.72em;margin:2px 0">
      <span style="color:#6b9cc4">Events</span>
      <span style="color:#e8f4ff;font-weight:600">{events_nb}</span>
    </div>
  </div>
  {wind_html}
</div>"""
    st.markdown(card_html, unsafe_allow_html=True)
    if st.button("Select", key=f"sel_{route}", use_container_width=True):
        st.session_state["selected_route"] = route
        st.rerun()


# ── Sidebar Alert Strip ───────────────────────────────────────────────────────

def render_alert_strip(events_df: pd.DataFrame, max_alerts: int = 4) -> None:
    """Render compact live alert cards in the sidebar."""
    if events_df.empty:
        st.sidebar.caption("No active alerts")
        return

    ALERT_COLORS = {"Critical": "#FF2222", "High": "#FF8C00", "Medium": "#FFD700", "Low": "#6b9cc4"}
    ALERT_ICONS  = {"Critical": "🚨", "High": "⚠️", "Medium": "📍", "Low": "ℹ️"}

    alerts = events_df[events_df["impact"].isin(["Critical", "High"])].sort_values("date", ascending=False).head(max_alerts)
    if len(alerts) == 0:
        alerts = events_df.sort_values("date", ascending=False).head(max_alerts)

    html = ""
    for _, row in alerts.iterrows():
        color = ALERT_COLORS.get(row["impact"], "#6b9cc4")
        icon  = ALERT_ICONS.get(row["impact"], "ℹ️")
        try:
            age_h = _hours_since(row["date"])
            age_str = f"{int(age_h)}h ago" if age_h < 48 else f"{int(age_h/24)}d ago"
        except Exception:
            age_str = ""
        desc = str(row.get("description", ""))[:70]
        html += f"""
<div style="border-left:3px solid {color};border-radius:6px;padding:7px 9px;
            margin:4px 0;background:#071428">
  <div style="font-size:0.65em;color:#6b9cc4">{icon} {age_str} · {row.get('location','')}</div>
  <div style="font-size:0.76em;color:#e8f4ff;line-height:1.3;margin-top:2px">{desc}</div>
</div>"""
    st.sidebar.markdown(html, unsafe_allow_html=True)


# ── Route Comparison Table ────────────────────────────────────────────────────

def render_comparison_table(
    shipping_df: pd.DataFrame,
    port_cong_df: pd.DataFrame,
    best_route: str,
    scenario_overrides: dict | None = None,
) -> None:
    """Render styled HTML route comparison matrix."""

    STATUS_COLORS_LOCAL = STATUS_COLORS
    rows_html = ""

    for _, row in shipping_df.iterrows():
        route      = row["Route"]
        risk_score = int(row["Risk Score"])
        status     = row["Status"]
        delay      = row["Average Delay"]
        cost       = row["Cost Impact"]

        # Apply scenario override
        if scenario_overrides and route in scenario_overrides:
            status     = "Critical - Avoid"
            risk_score = 100
            delay      = "48+ hours"
            cost       = "+50%"

        sc       = STATUS_COLORS_LOCAL.get(status, "#888")
        rscolor  = _risk_score_color(risk_score)
        is_best  = route == best_route and not (scenario_overrides and route in scenario_overrides)
        rec_cell = "✅ Best" if is_best else ""
        rec_color = "#00CC44" if is_best else "#6b9cc4"

        # Port congestion for nearest port
        nearest = ROUTE_PORT_MAP.get(route)
        cong_text = "—"
        if nearest and port_cong_df is not None and len(port_cong_df) > 0:
            p = port_cong_df[port_cong_df["Port"] == nearest]
            if len(p) > 0:
                cong = p.iloc[0]["Congestion"]
                cong_col = {"Critical": "#FF2222", "High": "#FF8C00", "Medium": "#FFD700", "Low": "#00CC44"}.get(cong, "#888")
                cong_text = f'<span style="color:{cong_col};font-weight:600">{cong}</span>'

        # Row highlight for best
        row_bg = "background:rgba(46,127,255,0.06);" if is_best else ""

        rows_html += f"""
<tr style="{row_bg}border-bottom:1px solid #1a3a6c;">
  <td style="padding:10px 8px;font-weight:600;color:#e8f4ff">{route}</td>
  <td style="padding:10px 8px">
    <span style="background:{sc}22;border:1px solid {sc};border-radius:20px;
                 padding:2px 8px;font-size:0.78em;font-weight:600;color:{sc}">
      {status}
    </span>
  </td>
  <td style="padding:10px 8px;font-weight:700;color:{rscolor};font-size:1.1em">{risk_score}</td>
  <td style="padding:10px 8px;color:#e8f4ff">{delay}</td>
  <td style="padding:10px 8px;color:#e8f4ff">{cost}</td>
  <td style="padding:10px 8px">{cong_text}</td>
  <td style="padding:10px 8px;color:{rec_color};font-weight:600">{rec_cell}</td>
</tr>"""

    table_html = f"""
<div style="overflow-x:auto">
<table style="width:100%;border-collapse:collapse;font-size:0.85em;font-family:Inter,sans-serif">
  <thead>
    <tr style="border-bottom:2px solid #2a5aaa">
      <th style="padding:8px;text-align:left;color:#6b9cc4;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;font-size:0.75em">Route</th>
      <th style="padding:8px;text-align:left;color:#6b9cc4;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;font-size:0.75em">Status</th>
      <th style="padding:8px;text-align:left;color:#6b9cc4;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;font-size:0.75em">Risk</th>
      <th style="padding:8px;text-align:left;color:#6b9cc4;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;font-size:0.75em">Delay</th>
      <th style="padding:8px;text-align:left;color:#6b9cc4;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;font-size:0.75em">Cost Δ</th>
      <th style="padding:8px;text-align:left;color:#6b9cc4;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;font-size:0.75em">Port Cong.</th>
      <th style="padding:8px;text-align:left;color:#6b9cc4;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;font-size:0.75em">Rec.</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
</div>"""
    st.markdown(table_html, unsafe_allow_html=True)


# ── Intel Brief (rule-based, pure Python) ─────────────────────────────────────

def generate_intel_brief(events_df: pd.DataFrame, news_df: pd.DataFrame, shipping_df: pd.DataFrame) -> list[str]:
    """Generate a 5-bullet intelligence brief from live data."""
    lines = []

    if not events_df.empty:
        critical = events_df[events_df["impact"] == "Critical"]
        if len(critical) > 0:
            top = critical.sort_values("date", ascending=False).iloc[0]
            lines.append(f"🚨 **Most severe event:** {top['type']} in **{top['location']}** — {str(top.get('description',''))[:80]}")

    if not shipping_df.empty:
        worst = shipping_df.sort_values("Risk Score", ascending=False).iloc[0]
        lines.append(f"🔴 **Highest-risk chokepoint:** {worst['Route']} (score {int(worst['Risk Score'])}/100) — {worst['Average Delay']} delay, {worst['Cost Impact']} cost impact")

        best = shipping_df.sort_values("Risk Score").iloc[0]
        lines.append(f"✅ **Lowest-risk route:** {best['Route']} (score {int(best['Risk Score'])}/100) — recommended alternative")

    if not news_df.empty:
        conflict_news = news_df[news_df["topic"] == "conflict"].head(1)
        if len(conflict_news) > 0:
            lines.append(f"📰 **Conflict signal:** {str(conflict_news.iloc[0]['title'])[:100]}")
        shipping_news = news_df[news_df["topic"] == "shipping"].head(1)
        if len(shipping_news) > 0:
            lines.append(f"🚢 **Shipping signal:** {str(shipping_news.iloc[0]['title'])[:100]}")

    return lines


# ── Retained utilities ────────────────────────────────────────────────────────

def filter_events(events_df, event_type=None, impact_level=None, search_text=None):
    """Filter events by type, impact, and free text search."""
    filtered = events_df.copy()
    if event_type and event_type != "All Types":
        filtered = filtered[filtered["type"] == event_type]
    if impact_level and impact_level != "All Levels":
        filtered = filtered[filtered["impact"] == impact_level]
    if search_text:
        s = search_text.lower()
        filtered = filtered[
            filtered["description"].str.lower().str.contains(s, na=False) |
            filtered["location"].str.lower().str.contains(s, na=False)
        ]
    return filtered


def get_impact_color(impact):
    return IMPACT_LEVELS.get(impact, {}).get("color", "#FFD700")
