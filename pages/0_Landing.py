"""TradeWatch — Landing Page"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import plotly.graph_objects as go
import streamlit as st
import pandas as pd

from data_loader import load_core_data
from dynamic_status import compute_shipping_status
from maps import create_dashboard_map
from ui_helpers import inject_css, risk_col


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TradeWatch — Welcome",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

st.markdown("""
<style>
/* ── Base ── */
.stApp { background: #f2f5fa !important; }
p, span, div, label, li, td, th,
.stMarkdown, .stText { color: #1e3a5f !important; }
h1, h2, h3 { color: #0f2744 !important; }

/* ── Hero ── */
.tw-hero {
  background: linear-gradient(130deg, #0f2744 0%, #1a4a7a 55%, #0e6e85 100%);
  border-radius: 14px;
  padding: 40px 48px 36px 48px;
  text-align: center;
  margin-bottom: 28px;
  box-shadow: 0 6px 28px rgba(15,39,68,0.22);
}
.tw-hero-eyebrow {
  font-size: 12px !important;
  font-weight: 700 !important;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: #7ec8e3 !important;
  margin-bottom: 12px;
}
.tw-hero-title {
  font-size: 68px !important;
  font-weight: 900 !important;
  color: #ffffff !important;
  line-height: 1.05;
  margin-bottom: 16px;
  text-shadow: 0 2px 16px rgba(0,0,0,0.35);
}
.tw-hero-subtitle {
  font-size: 19px !important;
  font-weight: 400 !important;
  color: #e8f4fd !important;
  max-width: 600px;
  margin: 0 auto 22px auto;
  line-height: 1.65;
}
.tw-scroll-cue {
  font-size: 13px !important;
  color: #7ec8e3 !important;
  letter-spacing: 0.06em;
}

/* ── Mission/Vision/Why cards ── */
.tw-card-row {
  display: flex;
  gap: 18px;
  margin-bottom: 28px;
}
.tw-card {
  flex: 1;
  background: #ffffff;
  border-radius: 12px;
  padding: 22px 20px 20px 20px;
  box-shadow: 0 2px 12px rgba(15,39,68,0.09);
  border-top: 4px solid #1a6ea8;
}
.tw-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.tw-card-icon { font-size: 20px; line-height: 1; }
.tw-card-title {
  font-size: 15px !important;
  font-weight: 700 !important;
  color: #0f2744 !important;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 0;
}
.tw-card-body {
  font-size: 14px !important;
  color: #3d5a7a !important;
  line-height: 1.7;
}

/* ── Risk panel ── */
.tw-risk-panel {
  background: #ffffff;
  border-radius: 12px;
  padding: 20px 20px 16px 20px;
  box-shadow: 0 2px 12px rgba(15,39,68,0.09);
  height: 100%;
}
.tw-risk-panel-header {
  font-size: 13px;
  font-weight: 700;
  color: #0f2744;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.tw-live-badge {
  background: rgba(220,38,38,0.1);
  color: #dc2626;
  border: 1px solid rgba(220,38,38,0.28);
  border-radius: 4px;
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

/* ── Bottom CTA button ── */
.stButton button {
  background: #1a6ea8 !important;
  color: #ffffff !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 700 !important;
  font-size: 15px !important;
  padding: 12px 0 !important;
  letter-spacing: 0.03em;
  transition: background 0.2s;
}
.stButton button:hover { background: #0f2744 !important; }
</style>
""", unsafe_allow_html=True)


# ── ISO-3 country codes for hover choropleth layer ────────────────────────────
# fmt: off
_ALL_ISO3 = [
    "AFG","ALB","DZA","AND","AGO","ATG","ARG","ARM","AUS","AUT","AZE","BHS","BHR",
    "BGD","BRB","BLR","BEL","BLZ","BEN","BTN","BOL","BIH","BWA","BRA","BRN","BGR",
    "BFA","BDI","CPV","KHM","CMR","CAN","CAF","TCD","CHL","CHN","COL","COM","COD",
    "COG","CRI","CIV","HRV","CUB","CYP","CZE","DNK","DJI","DOM","ECU","EGY","SLV",
    "GNQ","ERI","EST","SWZ","ETH","FJI","FIN","FRA","GAB","GMB","GEO","DEU","GHA",
    "GRC","GRD","GTM","GIN","GNB","GUY","HTI","HND","HUN","ISL","IND","IDN","IRN",
    "IRQ","IRL","ISR","ITA","JAM","JPN","JOR","KAZ","KEN","KIR","PRK","KOR","XKX",
    "KWT","KGZ","LAO","LVA","LBN","LSO","LBR","LBY","LIE","LTU","LUX","MDG","MWI",
    "MYS","MDV","MLI","MLT","MHL","MRT","MUS","MEX","FSM","MDA","MCO","MNG","MNE",
    "MAR","MOZ","MMR","NAM","NRU","NPL","NLD","NZL","NIC","NER","NGA","MKD","NOR",
    "OMN","PAK","PLW","PAN","PNG","PRY","PER","PHL","POL","PRT","QAT","ROU","RUS",
    "RWA","KNA","LCA","VCT","WSM","SMR","STP","SAU","SEN","SRB","SYC","SLE","SGP",
    "SVK","SVN","SLB","SOM","ZAF","SSD","ESP","LKA","SDN","SUR","SWE","CHE","SYR",
    "TWN","TJK","TZA","THA","TLS","TGO","TON","TTO","TUN","TUR","TKM","TUV","UGA",
    "UKR","ARE","GBR","USA","URY","UZB","VUT","VEN","VNM","YEM","ZMB","ZWE",
]
# fmt: on


# ── Data loading ──────────────────────────────────────────────────────────────
with st.spinner("Initializing global shipping intelligence..."):
    events_df, oil_price, shipping_index, exchange_rates = load_core_data()

events_json = events_df.to_json() if len(events_df) > 0 else pd.DataFrame().to_json()

with st.spinner("Computing route risk signals..."):
    shipping_df = compute_shipping_status(events_json)


# ── Helper: route action text ─────────────────────────────────────────────────
def route_action(status: str) -> str:
    if status == "Critical - Avoid":
        return "Avoid or compare alternative routing before dispatch."
    if status == "Operational - High Risk":
        return "Proceed only with monitoring and contingency planning."
    if status == "Operational - Alert":
        return "Monitor before final route confirmation."
    if status == "Unavailable":
        return "Data unavailable — manual review required."
    return "Proceed normally under current conditions."


# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="tw-hero">
  <div class="tw-hero-eyebrow">Shipping Route Intelligence</div>
  <div class="tw-hero-title">🌍 TradeWatch</div>
  <div class="tw-hero-subtitle">
    Shipping Route Intelligence for Safer, Smarter Global Trade
  </div>
  <div class="tw-scroll-cue">Scroll to explore live risks ↓</div>
</div>
""", unsafe_allow_html=True)


# ── Mission / Vision / Why cards ──────────────────────────────────────────────
st.markdown("""
<div class="tw-card-row">
  <div class="tw-card">
    <div class="tw-card-header">
      <span class="tw-card-icon">🎯</span>
      <span class="tw-card-title">Mission</span>
    </div>
    <div class="tw-card-body">
      Turn fragmented global risk signals into clear routing intelligence
      for shipping companies — before risk affects cargo safety or margins.
    </div>
  </div>
  <div class="tw-card">
    <div class="tw-card-header">
      <span class="tw-card-icon">🔭</span>
      <span class="tw-card-title">Vision</span>
    </div>
    <div class="tw-card-body">
      Make global shipping decisions more transparent, data-driven, and
      resilient in a world of geopolitical instability and market volatility.
    </div>
  </div>
  <div class="tw-card">
    <div class="tw-card-header">
      <span class="tw-card-icon">⚠️</span>
      <span class="tw-card-title">Why This Matters</span>
    </div>
    <div class="tw-card-body">
      A route that looks short on the map may become unsafe, delayed, or
      expensive once conflict, congestion, weather, and fuel costs are weighed.
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── How to use TradeWatch ─────────────────────────────────────────────────────
st.markdown("""
<div style="background:#ffffff;border-radius:12px;padding:26px 28px 22px 28px;
            margin-bottom:28px;box-shadow:0 2px 12px rgba(15,39,68,0.09);">
  <div style="font-size:15px;font-weight:700;color:#0f2744;text-transform:uppercase;
              letter-spacing:0.08em;margin-bottom:18px;">How to use TradeWatch</div>
  <div style="display:flex;gap:16px;">
    <div style="flex:1;background:#f2f7fc;border-radius:10px;padding:18px 16px;
                border-top:3px solid #1a6ea8;text-align:center;">
      <div style="font-size:22px;font-weight:800;color:#1a6ea8;margin-bottom:6px;">1</div>
      <div style="font-size:13px;font-weight:700;color:#0f2744;margin-bottom:6px;">Check live global risks</div>
      <div style="font-size:12px;color:#3d5a7a;line-height:1.55;">
        See which routes and regions have active geopolitical, weather, or port disruption signals right now.
      </div>
    </div>
    <div style="flex:1;background:#f2f7fc;border-radius:10px;padding:18px 16px;
                border-top:3px solid #0e6e85;text-align:center;">
      <div style="font-size:22px;font-weight:800;color:#0e6e85;margin-bottom:6px;">2</div>
      <div style="font-size:13px;font-weight:700;color:#0f2744;margin-bottom:6px;">Compare affected routes</div>
      <div style="font-size:12px;color:#3d5a7a;line-height:1.55;">
        Review risk scores and status for each shipping lane side-by-side in the Route Status panel.
      </div>
    </div>
    <div style="flex:1;background:#f2f7fc;border-radius:10px;padding:18px 16px;
                border-top:3px solid #1a8a5a;text-align:center;">
      <div style="font-size:22px;font-weight:800;color:#1a8a5a;margin-bottom:6px;">3</div>
      <div style="font-size:13px;font-weight:700;color:#0f2744;margin-bottom:6px;">Review delay &amp; cost exposure</div>
      <div style="font-size:12px;color:#3d5a7a;line-height:1.55;">
        Understand estimated delay hours and financial cost impact per route before committing.
      </div>
    </div>
    <div style="flex:1;background:#f2f7fc;border-radius:10px;padding:18px 16px;
                border-top:3px solid #7c3aed;text-align:center;">
      <div style="font-size:22px;font-weight:800;color:#7c3aed;margin-bottom:6px;">4</div>
      <div style="font-size:13px;font-weight:700;color:#0f2744;margin-bottom:6px;">Choose the safest route</div>
      <div style="font-size:12px;color:#3d5a7a;line-height:1.55;">
        Use route recommendations and the full analytics dashboard to make confident dispatch decisions.
      </div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Map + live risks ──────────────────────────────────────────────────────────
map_col, story_col = st.columns([1.45, 1], gap="large")

with map_col:
    route_statuses = {}
    if len(shipping_df) > 0:
        route_statuses = dict(zip(shipping_df["Route"], shipping_df["Status"]))

    globe_fig = create_dashboard_map(
        events_df,
        show_routes=True,
        show_ports=False,
        show_events=True,
        show_vessels=False,
        show_daynight=False,
        show_piracy=False,
        route_statuses=route_statuses,
    )

    # Transparent choropleth for country hover names (no rivers, country borders kept)
    globe_fig.add_trace(
        go.Choropleth(
            locations=_ALL_ISO3,
            z=[0] * len(_ALL_ISO3),
            locationmode="ISO-3",
            colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
            showscale=False,
            marker=dict(line=dict(width=0)),
            hovertemplate="%{location}<extra></extra>",
            geo="geo",
        )
    )

    globe_fig.update_geos(
        projection_rotation=dict(lon=20, lat=20, roll=0),
        bgcolor="#dce8f5",
        landcolor="#d0dfc8",
        oceancolor="#a8c8e8",
        showrivers=False,
        showlakes=False,
        showcountries=True,
        countrycolor="#9ab0c8",
    )

    globe_fig.update_layout(
        height=530,
        paper_bgcolor="#f2f5fa",
        margin=dict(l=0, r=0, t=0, b=0),
    )

    st.plotly_chart(
        globe_fig,
        use_container_width=True,
        config={"scrollZoom": False, "displayModeBar": False},
    )

with story_col:
    st.markdown("""
<div class="tw-risk-panel">
  <div class="tw-risk-panel-header">
    Live Route Risk Examples
    <span class="tw-live-badge">live</span>
  </div>
""", unsafe_allow_html=True)

    if len(shipping_df) > 0:
        top_risks = shipping_df.sort_values("Risk Score", ascending=False).head(3)

        for _, row in top_risks.iterrows():
            score = int(row["Risk Score"])
            color = risk_col(score)
            action = route_action(row["Status"])

            st.markdown(f"""
<div style="background:#f7f9fc;border:1px solid #d8e4f0;
            border-left:4px solid {color};border-radius:8px;
            padding:12px 14px;margin-bottom:10px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
    <span style="font-size:14px;font-weight:700;color:#0f2744">{row["Route"]}</span>
    <span style="font-size:13px;font-weight:700;color:{color}">{score}/100</span>
  </div>
  <div style="font-size:13px;color:#3d5a7a;line-height:1.65">
    Status: <b>{row["Status"]}</b><br>
    Delay exposure: <b>{row["Average Delay"]}</b><br>
    Cost impact: <b>{row["Cost Impact"]}</b><br>
    Signals: {row["Nearby Events"]} events · {row["News Signals"]} news signals<br>
    <span style="color:#1a6ea8;font-weight:600">Action: {action}</span>
  </div>
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown("""
<div style="font-size:13px;color:#6b8faf;padding:10px 0">
  No live route risks available at the moment.
</div>
""", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


# ── Bottom CTA ────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)

col_l, col_btn, col_r = st.columns([1, 2, 1])
with col_btn:
    if st.button("Open Main Dashboard →", use_container_width=True, type="primary"):
        st.switch_page("app.py")
