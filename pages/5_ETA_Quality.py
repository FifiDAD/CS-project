"""TradeWatch — ETA Quality

Live tracking of the chokepoint ETA model: what it actually does, what it's
predicting right now, and how those predictions compare to reality.

NOTE: the model is XGBoost quantile regression (gradient boosting on
decision trees) — explicitly not deep learning. This page never trains
anything; it only inspects, measures, and surfaces the existing model.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from eta_model import (
    CHOKEPOINT_BBOXES,
    HEURISTIC_MEAN_MIN,
    explain_prediction,
    predict_transit_minutes,
)
from eta_quality import (
    compute_confidence_score,
    compute_quality_metrics,
    live_features_for_chokepoint,
    match_open_predictions,
    recent_predictions,
)
from ui_helpers import inject_css, render_footer, render_header, render_nav

st.set_page_config(
    page_title="TradeWatch — ETA Quality",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

# Header uses zero alert counts — this page is a model-inspection tool,
# not a status page. Worst_status="Operational" keeps the chip neutral.
render_header(0, 0, 0, "Operational", 0)
render_nav()


# ── Match any open predictions before computing metrics ────────────────────
match_counts = match_open_predictions()
metrics = compute_quality_metrics(window_days=30)

st.markdown(
    '<div class="tw-label" style="margin-bottom:6px">ETA Prediction Quality</div>',
    unsafe_allow_html=True,
)
st.caption(
    "How accurate have our ETA predictions been? Predictions are logged "
    "automatically every 10 minutes for each live vessel just entering a "
    "monitored chokepoint, and matched against the realised entry/exit "
    "timestamps from AIS once each vessel finishes transiting. This page "
    "summarises the (predicted, actual) pairs into live MAE, interval "
    "coverage, and drift signals."
)


# ══════════════════════════════════════════════════════════════════════════
# 1. How the ETA is calculated
# ══════════════════════════════════════════════════════════════════════════

def _load_meta() -> dict:
    p = Path(__file__).resolve().parent.parent / "models" / "eta_meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


meta = _load_meta()

with st.container(border=True):
    st.markdown("##### 1 — How the ETA is calculated")
    trained_at = meta.get("trained_at")
    trained_str = (
        datetime.fromtimestamp(float(trained_at)).strftime("%Y-%m-%d")
        if trained_at else "—"
    )
    n_real = int(meta.get("real_rows", 0))
    n_synth = int(meta.get("synthetic_rows", 0))
    n_train_total = int(meta.get("n_train", 0))

    st.caption(
        f"Last retrained: {trained_str} · {n_train_total:,} transits "
        f"({n_real:,} real · {n_synth:,} simulated)"
    )
    if st.button("Retrain model", key="eq_retrain_top"):
        try:
            from eta_scheduler import retrain_now as _retrain_now
            with st.spinner("Retraining…"):
                ok, msg = _retrain_now(use_seed_fallback=True, fast=True)
            (st.success if ok else st.error)(msg)
            if ok:
                st.cache_data.clear()
                st.cache_resource.clear()
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Retrain failed: {exc}")

    st.markdown(
        f"""
**What we're predicting.** For each major shipping chokepoint on a route
(Suez Canal, Strait of Malacca, Panama Canal, etc.), how long it will
take a specific vessel to transit it. The prediction comes out as three
numbers: a **Most-likely time**, plus a **Fastest-likely** and
**Slowest-likely** value that bracket the realistic range.

**Where the inputs come from.** Live AIS satellite data tells us how
many vessels are inside each chokepoint right now and how busy traffic
has been over the past 24 hours. The route planner adds the vessel
type the user picked in the sidebar and that vessel's cruise speed.
Time-of-day, day-of-week, and month are also fed in so the system
picks up traffic patterns (e.g. weekday vs weekend) and seasonality.

**How the system learned.** A pattern-finding model was trained on
**{n_train_total:,}** past transits (real AIS history:
{n_real:,} · simulated seed data: {n_synth:,}). For each new request
the model returns the Most-likely / Fastest-likely / Slowest-likely
range described above. If it doesn't have enough data for a particular
vessel/chokepoint combo, it falls back to a simple per-chokepoint
formula (shown below). Last retrained on **{trained_str}**.

**Fallback formula (used when the model can't predict).** A simple
rule of thumb that bumps each chokepoint's typical transit time up or
down depending on how busy the chokepoint is right now:

```
Most likely    = typical transit time × (1 + 0.10 × (vessels_in_chokepoint / 10 − 1))
Fastest likely = Most likely × 0.75
Slowest likely = Most likely × 1.30
```
"""
    )
    if HEURISTIC_MEAN_MIN:
        h_df = pd.DataFrame(
            sorted(HEURISTIC_MEAN_MIN.items(), key=lambda kv: kv[0]),
            columns=["Chokepoint", "Typical transit (min)"],
        )
        st.dataframe(h_df, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════
# 2. Live feature inspector — what would the model predict right now?
# ══════════════════════════════════════════════════════════════════════════

with st.container(border=True):
    st.markdown("##### 2 — Live feature inspector")
    st.caption(
        "Pick a chokepoint and a vessel type below to see exactly what the "
        "system is looking at right now, the Most-likely transit time it "
        "would predict, and which factors are pushing that prediction up "
        "or down."
    )
    cps = sorted(CHOKEPOINT_BBOXES.keys())
    pick_col1, pick_col2, pick_col3 = st.columns([2, 2, 1])
    with pick_col1:
        cp_pick = st.selectbox("Chokepoint", cps, key="eq_cp_pick")
    # Mirror the MariNav Router's vessel options so the inspector predicts
    # for the same {tanker, bulker, container, other} bins. Inline rather
    # than imported from the router page because importing a Streamlit page
    # module re-executes its UI; the list is short enough to duplicate.
    _vessel_options = [
        ("Panamax bulker", "bulker", 14.0),
        ("Suezmax tanker", "tanker", 14.5),
        ("VLCC tanker", "tanker", 15.0),
        ("ULCV container", "container", 22.0),
        ("MR product tanker", "tanker", 14.0),
    ]
    _vessel_labels = [v[0] for v in _vessel_options]
    with pick_col2:
        vessel_pick = st.selectbox("Vessel", _vessel_labels, index=0, key="eq_vessel_pick")
    _ship_bin = next((b for n, b, _ in _vessel_options if n == vessel_pick), "container")
    _speed_default = next((s for n, _, s in _vessel_options if n == vessel_pick), 12.0)
    with pick_col3:
        speed_pick = st.number_input(
            "Speed (kn)", min_value=8.0, max_value=24.0,
            value=float(_speed_default), step=0.5, key="eq_speed_pick",
        )

    feats = live_features_for_chokepoint(
        cp_pick, ship_type=_ship_bin, entry_sog_kn=float(speed_pick),
    )
    if not feats:
        st.warning("Chokepoint not recognised.")
    else:
        col_feat, col_pred = st.columns([3, 2])
        with col_feat:
            st.markdown("**What the system is looking at right now**")
            feat_rows = [
                ("Chokepoint", feats["chokepoint_id"]),
                ("Vessel type", f"{vessel_pick} ({feats['ship_type']})"),
                ("Entry speed", f"{feats['entry_sog_kn']:.1f} kn"),
                ("Vessels in chokepoint right now", feats["queue_depth"]),
                ("Vessels in last 24 h", feats["recent_throughput_24h"]),
                ("Hour of day (UTC)", feats["hour_of_day"]),
                ("Day of week", feats["day_of_week"]),
                ("Month", feats["month"]),
                ("Chokepoint size (km across)", f"{feats['bbox_diagonal_km']:.0f}"),
            ]
            st.dataframe(
                pd.DataFrame(feat_rows, columns=["Input", "Current value"]),
                hide_index=True,
                use_container_width=True,
            )
        with col_pred:
            # log=False so the inspector doesn't pollute the live prediction log.
            pred = predict_transit_minutes(cp_pick, feats, log=False)
            score, _ = compute_confidence_score(cp_pick, pred, metrics)
            st.markdown("**Resulting prediction**")
            st.metric(
                "Most likely",
                f"{pred['p50']/60:.1f} h",
                help=f"{pred['p50']} minutes",
            )
            st.caption(
                f"Fastest likely {pred['p10']/60:.1f}h · "
                f"Slowest likely {pred['p90']/60:.1f}h · "
                f"confidence **{score}%**"
            )

            st.markdown("**Biggest factors moving this prediction up or down**")
            contribs = explain_prediction(feats, top_k=5)
            if not contribs:
                st.caption(
                    "Per-prediction breakdown unavailable — this chokepoint "
                    "is using the fallback formula rather than the learned "
                    "model."
                )
            else:
                contrib_df = pd.DataFrame(contribs, columns=["Factor", "Effect (min)"])
                contrib_df["Effect (min)"] = contrib_df["Effect (min)"].round(1)
                st.dataframe(contrib_df, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════
# 3. Live accuracy KPIs
# ══════════════════════════════════════════════════════════════════════════

with st.container(border=True):
    st.markdown("##### 3 — How accurate have we been? (last 30 days)")
    if metrics["n_closed"] == 0:
        st.info(
            f"No predictions have finished yet — {metrics['n_open']} are still "
            f"in flight, {metrics['n_expired']} timed out without a match. "
            "Generate routes in MariNav Router and let vessels finish "
            "transiting to populate this view."
        )
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Within ±15% of reality",
            f"{metrics['accuracy_pct_15']:.0f}%",
            help="Out of every 100 predictions, how many landed within 15% of the actual transit time.",
        )
        c2.metric(
            "Within ±25% of reality",
            f"{metrics['accuracy_pct_25']:.0f}%",
            help="Same idea, looser tolerance.",
        )
        cov = metrics["coverage_p10_p90"] * 100
        c3.metric(
            "Reality inside our range",
            f"{cov:.0f}%",
            delta=f"{cov - 80:+.0f}pp vs 80% target",
            delta_color="normal" if abs(cov - 80) < 10 else "inverse",
            help="How often the actual transit time landed inside our Fastest–Slowest range. Target: 80%.",
        )
        c4.metric(
            "Average error",
            f"{metrics['rolling_mae_min']:.0f} min",
            delta=(
                f"{metrics['rolling_mae_min'] - metrics['training_mae_min']:+.0f} min vs training"
                if metrics["training_mae_min"] > 0 else None
            ),
            delta_color="inverse",
            help="On average, by how many minutes did the prediction miss the actual transit time.",
        )

    st.caption(
        f"Finished predictions: **{metrics['n_closed']}** · Still in flight: "
        f"**{metrics['n_open']}** · Timed out (no match after 72h): "
        f"**{metrics['n_expired']}** · Matched on this page load: "
        f"**{match_counts['matched']}** (+{match_counts['expired']} timed out)"
    )


# ══════════════════════════════════════════════════════════════════════════
# 4. Predicted vs actual scatter (live data)
# ══════════════════════════════════════════════════════════════════════════

with st.container(border=True):
    st.markdown("##### 4 — Predicted vs actual")
    st.caption(
        "Every dot is one vessel. The dashed line is the perfect-prediction "
        "line: dots above it = the system overestimated; dots below = it "
        "underestimated."
    )
    if metrics["n_closed"] == 0:
        st.caption("Waiting on finished predictions — the chart fills in as vessels complete transits.")
    else:
        try:
            import plotly.express as px
            import sqlite3 as _sql
            db = Path(__file__).resolve().parent.parent / ".ais_positions.db"
            with _sql.connect(db, timeout=5.0) as con:
                scatter_df = pd.read_sql_query(
                    "SELECT chokepoint_id, p50_min, p10_min, p90_min, actual_min, mmsi "
                    "FROM eta_predictions "
                    "WHERE actual_min IS NOT NULL "
                    "AND predicted_at >= ? "
                    "ORDER BY predicted_at DESC LIMIT 1000",
                    con,
                    params=(time.time() - 30 * 86400,),
                )
            # Convert to hours and friendlier column names for the hover card.
            scatter_df["Actual (h)"] = scatter_df["actual_min"] / 60.0
            scatter_df["Most-likely predicted (h)"] = scatter_df["p50_min"] / 60.0
            scatter_df["Off by (h)"] = (scatter_df["p50_min"] - scatter_df["actual_min"]) / 60.0
            scatter_df["Fastest likely (h)"] = scatter_df["p10_min"] / 60.0
            scatter_df["Slowest likely (h)"] = scatter_df["p90_min"] / 60.0
            scatter_df = scatter_df.rename(columns={
                "chokepoint_id": "Chokepoint",
                "mmsi": "Vessel ID",
            })
            fig = px.scatter(
                scatter_df,
                x="Actual (h)",
                y="Most-likely predicted (h)",
                color="Chokepoint",
                hover_data={
                    "Vessel ID": True,
                    "Fastest likely (h)": ":.1f",
                    "Slowest likely (h)": ":.1f",
                    "Off by (h)": ":+.1f",
                    "Actual (h)": ":.1f",
                    "Most-likely predicted (h)": ":.1f",
                },
                labels={
                    "Actual (h)": "Actual transit time (h)",
                    "Most-likely predicted (h)": "Most-likely predicted time (h)",
                },
            )
            # Add y=x reference line
            lo = float(min(scatter_df["Actual (h)"].min(), scatter_df["Most-likely predicted (h)"].min()))
            hi = float(max(scatter_df["Actual (h)"].max(), scatter_df["Most-likely predicted (h)"].max()))
            fig.add_shape(
                type="line", x0=lo, x1=hi, y0=lo, y1=hi,
                line=dict(color="#ef4444", dash="dash", width=1),
            )
            fig.update_layout(
                height=380,
                margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(20,20,20,0.6)",
            )
            st.plotly_chart(fig, use_container_width=True)
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Chart unavailable: {exc}")


# ══════════════════════════════════════════════════════════════════════════
# 4b. Recent logged predictions (raw audit table)
# ══════════════════════════════════════════════════════════════════════════

with st.container(border=True):
    st.markdown("##### 4b — Recent predictions")
    st.caption(
        "One row per prediction the dashboard has made — newest first. "
        "The Actual column fills in once the vessel finishes its transit; "
        "until then, the row's Status reads 'still in flight'."
    )
    cp_filter_options = ["(All)"] + sorted(CHOKEPOINT_BBOXES.keys())
    cp_filter = st.selectbox(
        "Filter by chokepoint", cp_filter_options, key="eq_log_filter"
    )
    log_df = recent_predictions(
        limit=50,
        chokepoint_id=None if cp_filter == "(All)" else cp_filter,
    )
    if log_df.empty:
        st.caption("No predictions logged yet. Generate a route in MariNav Router to populate this.")
    else:
        # Friendly column names + source/status remapping for the user-facing
        # view. The underlying `recent_predictions()` columns stay as-is for
        # programmatic access elsewhere.
        _source_map = {
            "model": "Learned from past transits",
            "heuristic": "Fallback formula",
            "unseen_chokepoint": "Unknown chokepoint",
        }
        _status_map = {
            "bbox_gap_split": "Matched",
            "anonymous_match": "Matched (anonymous)",
            "expired": "Timed out",
            None: "Still in flight",
        }
        display_df = log_df.copy()
        display_df["source"] = display_df["source"].map(lambda v: _source_map.get(v, v))
        display_df["match_method"] = display_df["match_method"].map(
            lambda v: _status_map.get(v, v if v else "Still in flight")
        )
        display_df = display_df.rename(columns={
            "predicted_at": "Predicted at",
            "chokepoint_id": "Chokepoint",
            "mmsi": "Vessel ID",
            "source": "Source",
            "ship_type": "Vessel type",
            "entry_sog_kn": "Entry speed (kn)",
            "queue_depth": "Vessels in chokepoint",
            "recent_throughput_24h": "Vessels in last 24 h",
            "p10_min": "Fastest (min)",
            "p50_min": "Most likely (min)",
            "p90_min": "Slowest (min)",
            "actual_min": "Actual (min)",
            "match_method": "Status",
        })
        st.dataframe(display_df, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════
# 5. Per-chokepoint table
# ══════════════════════════════════════════════════════════════════════════

with st.container(border=True):
    st.markdown("##### 5 — Accuracy by chokepoint")
    by_cp = metrics.get("by_chokepoint") or {}
    training_per_cp = (meta.get("per_chokepoint_mae") or {})
    if not by_cp:
        st.caption("No finished predictions yet — table fills in as transits complete.")
    else:
        rows = []
        for cp, m in by_cp.items():
            train_mae = float(training_per_cp.get(cp, 0.0) or 0.0)
            ratio = (m["rolling_mae_min"] / train_mae) if train_mae > 0 else None
            rows.append({
                "Chokepoint": cp,
                "Finished predictions": m["n_closed"],
                "Average error (min)": round(m["rolling_mae_min"], 1),
                "Average error (%)": round(m["mape_pct"], 1),
                "Within ±15% (%)": round(m["accuracy_pct_15"], 0),
                "Reality inside our range (%)": round(m["coverage_p10_p90"] * 100, 0),
                "On average too high/low (min)": round(m["bias_min"], 1),
                "Error when trained (min)": round(train_mae, 1) if train_mae > 0 else None,
                "Live vs training": round(ratio, 2) if ratio is not None else None,
                "Getting worse?": "⚠️" if (ratio is not None and ratio > 1.25) else "",
            })
        cp_df = pd.DataFrame(rows).sort_values(
            "Live vs training", ascending=False, na_position="last"
        )
        st.dataframe(cp_df, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════
# 6. Drift & retraining
# ══════════════════════════════════════════════════════════════════════════

with st.container(border=True):
    st.markdown("##### 6 — Is the model still accurate?")
    if metrics["drift_flag"]:
        st.error(
            f"⚠️ Live predictions are off by **{metrics['rolling_mae_min']:.0f} min** "
            f"on average — more than 25% worse than when the model was trained "
            f"({metrics['training_mae_min']:.0f} min). Time to refresh."
        )
    elif metrics["n_closed"] < 10:
        st.caption(
            f"Need at least 10 finished predictions before we can spot trends "
            f"(currently {metrics['n_closed']})."
        )
    else:
        st.success(
            f"Predictions are still accurate. Live average error "
            f"{metrics['rolling_mae_min']:.0f} min vs "
            f"{metrics['training_mae_min']:.0f} min when trained."
        )

    try:
        from eta_scheduler import next_retrain_eta, retrain_now
        sched = next_retrain_eta()
        hours_left = sched["seconds_until_cooldown_clears"] / 3600.0
        if sched["cooldown_elapsed"] and sched["enough_data"]:
            next_str = "ready now"
        elif not sched["enough_data"]:
            next_str = f"waiting on data ({sched['real_rows']} real transits / need ≥200)"
        else:
            next_str = f"in {hours_left:.1f} h (24 h cooldown after last refresh)"
        st.caption(
            f"Auto-refresh: **{next_str}** · Real vessel transits collected: "
            f"**{sched['real_rows']}**"
        )
        if st.button("Refresh now", key="eq_retrain"):
            with st.spinner("Refreshing the model — may take a few minutes…"):
                ok, msg = retrain_now(use_seed_fallback=True)
            (st.success if ok else st.error)(msg)
            if ok:
                st.cache_resource.clear()
                st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.caption(f"Refresh scheduler unavailable: {exc}")


render_footer()
