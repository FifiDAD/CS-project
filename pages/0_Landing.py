"""TradeWatch — Landing Page (static tutorial / informational)

Pure-static welcome page: no live API fetches, no globe, no interactive
demos. Renders instantly. While the user reads, a daemon thread warms
every cache the rest of the dashboard hits, so clicking "Open Main
Dashboard →" feels instant.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import streamlit as st

from data_loader import prefetch_full_dashboard
from ui_helpers import inject_css


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
  max-width: 640px;
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

/* ── Section headers ── */
.tw-section-title {
  font-size: 13px !important;
  font-weight: 700 !important;
  color: #0f2744 !important;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  margin: 32px 0 14px 0;
  padding-bottom: 8px;
  border-bottom: 1px solid #cfdce9;
}

/* ── Workflow steps ── */
.tw-step {
  background: #ffffff;
  border-radius: 10px;
  padding: 18px 18px 14px 18px;
  box-shadow: 0 2px 10px rgba(15,39,68,0.07);
  border-left: 3px solid #1a6ea8;
  height: 100%;
}
.tw-step-num {
  display: inline-block;
  width: 26px; height: 26px; line-height: 26px;
  text-align: center;
  background: #1a6ea8;
  color: #ffffff !important;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 10px;
}
.tw-step-title {
  font-size: 13px !important;
  font-weight: 700 !important;
  color: #0f2744 !important;
  margin-bottom: 6px;
}
.tw-step-body {
  font-size: 12px !important;
  color: #3d5a7a !important;
  line-height: 1.6;
}
.tw-step-tag {
  display: inline-block;
  font-size: 10px;
  background: #e8f1fb;
  color: #1a6ea8 !important;
  padding: 2px 8px;
  border-radius: 4px;
  margin-top: 8px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

/* ── Feature page tiles ── */
.tw-feature {
  background: #ffffff;
  border-radius: 12px;
  padding: 20px 20px 16px 20px;
  box-shadow: 0 2px 12px rgba(15,39,68,0.09);
  border-top: 3px solid #0e6e85;
  height: 100%;
}
.tw-feature-icon {
  font-size: 28px;
  margin-bottom: 8px;
  display: block;
}
.tw-feature-title {
  font-size: 14px !important;
  font-weight: 700 !important;
  color: #0f2744 !important;
  margin-bottom: 4px;
}
.tw-feature-sub {
  font-size: 11px !important;
  color: #6b8faf !important;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 10px;
}
.tw-feature-body {
  font-size: 13px !important;
  color: #3d5a7a !important;
  line-height: 1.65;
}
.tw-feature-list {
  font-size: 12px !important;
  color: #3d5a7a !important;
  margin: 10px 0 0 0;
  padding-left: 16px;
  line-height: 1.7;
}

/* ── Quick-start tutorial ── */
.tw-tutorial {
  background: linear-gradient(180deg, #ffffff 0%, #f7fbff 100%);
  border-radius: 12px;
  padding: 24px 28px 20px 28px;
  box-shadow: 0 2px 12px rgba(15,39,68,0.09);
  border: 1px solid #e0eaf4;
}
.tw-tutorial-step {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 10px 0;
  border-bottom: 1px dashed #e0eaf4;
}
.tw-tutorial-step:last-child { border-bottom: none; }
.tw-tutorial-num {
  flex: 0 0 32px;
  width: 32px; height: 32px; line-height: 32px;
  text-align: center;
  background: #0e6e85;
  color: #ffffff !important;
  border-radius: 50%;
  font-size: 13px;
  font-weight: 700;
}
.tw-tutorial-text {
  flex: 1;
  font-size: 13px !important;
  color: #3d5a7a !important;
  line-height: 1.65;
}
.tw-tutorial-text b { color: #0f2744 !important; }

/* ── Risk-priority callout ── */
.tw-priority-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-top: 12px;
}
.tw-priority {
  background: #ffffff;
  border-radius: 8px;
  padding: 14px 14px 12px 14px;
  border-top: 3px solid #1a6ea8;
  box-shadow: 0 1px 6px rgba(15,39,68,0.06);
}
.tw-priority-icon { font-size: 22px; }
.tw-priority-name {
  font-size: 12px !important;
  font-weight: 700 !important;
  color: #0f2744 !important;
  margin: 4px 0 4px 0;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.tw-priority-body {
  font-size: 11px !important;
  color: #3d5a7a !important;
  line-height: 1.55;
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


# ── Background warm-up ────────────────────────────────────────────────────────
# Kick off the daemon thread that warms every cache the rest of the dashboard
# hits. The Landing page itself doesn't await it — by the time the user clicks
# "Open Main Dashboard →" the slow paths are already cached.
prefetch_full_dashboard()


# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="tw-hero">
  <div class="tw-hero-eyebrow">Shipping Route Intelligence</div>
  <div class="tw-hero-title">🌍 TradeWatch</div>
  <div class="tw-hero-subtitle">
    Live geopolitical, weather, and market intelligence for global shipping
    routes — so planners can pick the right route based on their priorities,
    not just the shortest line on the map.
  </div>
  <div class="tw-scroll-cue">Scroll to see what TradeWatch does ↓</div>
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


# ── How TradeWatch works (4-step workflow) ────────────────────────────────────
st.markdown('<div class="tw-section-title">How TradeWatch Works</div>',
            unsafe_allow_html=True)

st.markdown("""
<div class="tw-card-row">
  <div class="tw-step">
    <div class="tw-step-num">1</div>
    <div class="tw-step-title">Aggregate Live Signals</div>
    <div class="tw-step-body">
      Pull geocoded events from <b>GDELT</b>, official maritime warnings from
      <b>NGA</b>, vessel positions from <b>AIS</b>, and weather from
      <b>Open-Meteo</b> — every 15 minutes.
    </div>
    <span class="tw-step-tag">9 live feeds</span>
  </div>
  <div class="tw-step">
    <div class="tw-step-num">2</div>
    <div class="tw-step-title">Score Chokepoint Risk</div>
    <div class="tw-step-body">
      For each major chokepoint (Suez, Hormuz, Malacca, Panama, Bosphorus,
      English Channel) compute a 0–100 risk score from nearby events,
      news mentions, NGA severity, and AIS transit-volume drop.
    </div>
    <span class="tw-step-tag">Auto-updates</span>
  </div>
  <div class="tw-step">
    <div class="tw-step-num">3</div>
    <div class="tw-step-title">Plan Routes With Tradeoffs</div>
    <div class="tw-step-body">
      Feed those risk scores into a graph-based router that surfaces four
      named alternatives — <b>Recommended</b>, <b>Fastest</b>, <b>Safest</b>,
      <b>Cheapest</b> — with full economics for each.
    </div>
    <span class="tw-step-tag">MariNav engine</span>
  </div>
  <div class="tw-step">
    <div class="tw-step-num">4</div>
    <div class="tw-step-title">Decide & Document</div>
    <div class="tw-step-body">
      Pick the route that matches the cargo's risk tolerance, urgency, and
      budget. Every choice comes with a "why" narrative + per-leg breakdown
      you can hand to operations.
    </div>
    <span class="tw-step-tag">Audit trail</span>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Feature tour: the 4 pages ─────────────────────────────────────────────────
st.markdown('<div class="tw-section-title">What\'s Inside</div>',
            unsafe_allow_html=True)

f1, f2 = st.columns(2, gap="large")

with f1:
    st.markdown("""
<div class="tw-feature" style="border-top-color:#1a6ea8">
  <span class="tw-feature-icon">🌍</span>
  <div class="tw-feature-title">Main Dashboard</div>
  <div class="tw-feature-sub">Globe view · live status</div>
  <div class="tw-feature-body">
    A 3-D globe of the world with every monitored shipping lane,
    chokepoint, and active event plotted in real time.
  </div>
  <ul class="tw-feature-list">
    <li>Routes coloured by current risk score</li>
    <li>Port markers sized by live anchorage queue</li>
    <li>AIS vessel layer + day/night terminator</li>
    <li>Top 5 live events panel + recommended route</li>
  </ul>
</div>
""", unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    st.markdown("""
<div class="tw-feature" style="border-top-color:#0e6e85">
  <span class="tw-feature-icon">📊</span>
  <div class="tw-feature-title">Market & Costs</div>
  <div class="tw-feature-sub">Bunker · freight · fleet impact</div>
  <div class="tw-feature-body">
    Live oil price, IMF freight index, FX rates, and Ship & Bunker bunker
    prices with daily change indicators.
  </div>
  <ul class="tw-feature-list">
    <li>VLSFO / IFO380 / MGO at 8 major bunker ports</li>
    <li>Fleet-wide cost-impact model (oil × event multipliers)</li>
    <li>Per-chokepoint delay & cost-Δ table</li>
    <li>Port congestion ranked by score</li>
  </ul>
</div>
""", unsafe_allow_html=True)

with f2:
    st.markdown("""
<div class="tw-feature" style="border-top-color:#a855f7">
  <span class="tw-feature-icon">📡</span>
  <div class="tw-feature-title">Intel Feed</div>
  <div class="tw-feature-sub">Events · news · NGA warnings</div>
  <div class="tw-feature-body">
    Every event and news article relevant to maritime shipping, clustered
    by region and topic with a rule-based intelligence brief on top.
  </div>
  <ul class="tw-feature-list">
    <li>Regional risk table + recommended actions</li>
    <li>NGA Maritime Safety Broadcast Warnings (severity ≥ 0.55)</li>
    <li>Live news feed clustered by Suez/Hormuz/Malacca/Panama/etc.</li>
    <li>Topic filters: conflict / shipping / trade / weather</li>
  </ul>
</div>
""", unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    st.markdown("""
<div class="tw-feature" style="border-top-color:#22c55e">
  <span class="tw-feature-icon">🧭</span>
  <div class="tw-feature-title">MariNav Router <span style="font-size:9px;background:#22c55e;color:#fff;padding:1px 6px;border-radius:3px;letter-spacing:0.05em">FLAGSHIP</span></div>
  <div class="tw-feature-sub">Interactive route planner with tradeoffs</div>
  <div class="tw-feature-body">
    Pick origin + destination + vessel, get four ranked alternatives —
    each with full economics, a "why this route" narrative, and a
    per-leg breakdown.
  </div>
  <ul class="tw-feature-list">
    <li>4 named objectives: Recommended / Fastest / Safest / Cheapest</li>
    <li>Full cost: fuel + risk surcharge + canal toll + opex</li>
    <li>Monte Carlo P10 / P50 / P90 confidence on fuel + ETA</li>
    <li>All four routes drawn on the globe — pick yours</li>
  </ul>
</div>
""", unsafe_allow_html=True)


# ── Quick-start: 4 steps to plan your first route ────────────────────────────
st.markdown('<div class="tw-section-title">Quick Start: Plan Your First Route</div>',
            unsafe_allow_html=True)

st.markdown("""
<div class="tw-tutorial">
  <div class="tw-tutorial-step">
    <div class="tw-tutorial-num">1</div>
    <div class="tw-tutorial-text">
      Open <b>MariNav Router</b> from the navigation bar. Pick an
      <b>Origin Port</b> and <b>Destination Port</b> (e.g. Rotterdam → Singapore).
    </div>
  </div>
  <div class="tw-tutorial-step">
    <div class="tw-tutorial-num">2</div>
    <div class="tw-tutorial-text">
      In the sidebar, choose your <b>vessel class</b> (Panamax / Suezmax / VLCC /
      ULCV / MR), <b>service speed</b>, and confirm the <b>daily OPEX</b>. These
      drive the fuel + cost calculations for every alternative.
    </div>
  </div>
  <div class="tw-tutorial-step">
    <div class="tw-tutorial-num">3</div>
    <div class="tw-tutorial-text">
      Click <b>Calculate Route</b>. The router runs Dijkstra under four
      objectives in parallel and shows you four cards: <b>Recommended</b>,
      <b>Fastest</b>, <b>Safest</b>, <b>Cheapest</b> — with distance, days,
      max chokepoint risk, and total cost for each.
    </div>
  </div>
  <div class="tw-tutorial-step">
    <div class="tw-tutorial-num">4</div>
    <div class="tw-tutorial-text">
      Pick the alternative that matches your priorities. The map updates,
      the <b>Why this route</b> narrative explains the tradeoff, and the
      <b>Per-leg breakdown</b> table shows distance / fuel / wind / sea
      state for every segment.
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Priority profiles — explains the 4 named alternatives ────────────────────
st.markdown('<div class="tw-section-title">Pick The Route That Fits Your Priorities</div>',
            unsafe_allow_html=True)

st.markdown("""
<div style="font-size:13px;color:#3d5a7a;line-height:1.65;margin-bottom:8px">
  Different cargo, different priorities. A perishable container has different
  constraints than a crude tanker. TradeWatch surfaces all four objectives so
  you can pick consciously instead of trusting a single "best" path.
</div>
<div class="tw-priority-grid">
  <div class="tw-priority" style="border-top-color:#3b82f6">
    <span class="tw-priority-icon">⚖️</span>
    <div class="tw-priority-name">Recommended</div>
    <div class="tw-priority-body">
      Balanced default. Distance × live risk × weather. Best when you have
      no specific priority and want the lowest expected total exposure.
    </div>
  </div>
  <div class="tw-priority" style="border-top-color:#f97316">
    <span class="tw-priority-icon">⏱</span>
    <div class="tw-priority-name">Fastest</div>
    <div class="tw-priority-body">
      Pure shortest distance. Pick this when contractual ETAs or
      perishable cargo make every day count more than the toll or risk.
    </div>
  </div>
  <div class="tw-priority" style="border-top-color:#22c55e">
    <span class="tw-priority-icon">🛡</span>
    <div class="tw-priority-name">Safest</div>
    <div class="tw-priority-body">
      Cubic risk penalty — heavily avoids active chokepoints. Pick this
      for hazardous cargo, capital-intensive vessels, or insurance-driven
      voyages.
    </div>
  </div>
  <div class="tw-priority" style="border-top-color:#a855f7">
    <span class="tw-priority-icon">💰</span>
    <div class="tw-priority-name">Cheapest</div>
    <div class="tw-priority-body">
      Lowest dollars on the docket. Pools k-shortest paths, then picks
      whichever has the smallest fuel + opex + canal toll + war-risk
      surcharge total.
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Bottom CTA ────────────────────────────────────────────────────────────────
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown(
    '<div style="text-align:center;font-size:12px;color:#6b8faf;'
    'letter-spacing:0.06em;margin-bottom:6px">'
    'Ready when you are.'
    '</div>',
    unsafe_allow_html=True,
)

col_l, col_btn, col_r = st.columns([1, 2, 1])
with col_btn:
    if st.button("Open Main Dashboard →", use_container_width=True, type="primary"):
        st.switch_page("app.py")

st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
