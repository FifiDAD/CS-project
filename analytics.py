"""Analytics Engine - Business Impact Analysis.

This module turns a DataFrame of risk events plus live market numbers
(oil price, shipping index, FX rates) into the headline KPIs the
dashboard displays: how many critical zones exist right now, how much
extra cost a fleet is bearing today, what action an operator should
take. All functions here are pure math on the inputs they receive —
no API calls, no caching, no side effects — so they are cheap to call
and easy to unit-test.
"""

import pandas as pd
from datetime import datetime, timedelta


def _utc_dates_and_now(events_df):
    """Return (UTC-aware date Series, UTC-aware "now") for time-window math.

    Live event sources mix tz-aware UTC datetimes (USGS, GDELT DOC) with
    naive strptime results, and pandas coerces them inconsistently. This
    helper normalises both sides so comparisons never raise TypeError.
    """
    # `errors='coerce'` turns unparseable strings into NaT instead of raising,
    # and `utc=True` forces every value onto a single timezone so the
    # subtraction below ("now minus event date") always works.
    dates = pd.to_datetime(events_df['date'], utc=True, errors='coerce')
    now = pd.Timestamp.now(tz='UTC')
    return dates, now
from config import ROUTE_FLEET_SIZES

class RiskAnalytics:
    """Calculate and analyze business risks"""

    @staticmethod
    def calculate_supply_chain_impact(events_df, oil_price, shipping_index):
        """Calculate supply chain impact from events and costs.

        Returns a dict the UI plugs straight into the KPI bar. Two live
        market numbers (oil, shipping index) tilt the cost-impact figure
        and the trend label; the events DataFrame contributes the count
        of currently-critical zones.
        """

        # Start with safe default values before adding live data — guarantees
        # the dict always has every key the UI expects, even if an upstream
        # API has failed and oil_price / shipping_index come in as None.
        metrics = {
            'event_count': len(events_df),
            'critical_zones': 0,
            'cost_impact_percentage': 0,
            'shipping_cost_trend': 'Stable',
            'trade_risk': 'Low',
        }

        # Count how many rows are currently flagged 'Critical'. This is the
        # red number on the KPI bar — the operator's "how many fires are
        # burning right now" indicator.
        metrics['critical_zones'] = len(events_df[events_df['impact'] == 'Critical'])

        # Oil price impact: express the current price as a % move away from
        # the $90/bbl baseline, then clamp to ±50 % so a freak spike or
        # crash can never make the KPI bar look broken on screen.
        if oil_price:
            baseline_oil = 90
            percentage_change = ((oil_price - baseline_oil) / baseline_oil) * 100
            metrics['cost_impact_percentage'] = max(-50, min(percentage_change, 50))

        # Shipping cost trend: classify the Baltic Dry / shipping index
        # into three buckets so the UI can show one of three icons. The
        # 2500 / 3500 thresholds are the historical "normal band".
        if shipping_index:
            if shipping_index > 3500:
                metrics['shipping_cost_trend'] = 'Increasing'
            elif shipping_index < 2500:
                metrics['shipping_cost_trend'] = 'Decreasing'
            else:
                metrics['shipping_cost_trend'] = 'Stable'

        return metrics

    @staticmethod
    def get_regional_alerts(events_df, threshold_hours=48):
        """Get recent alerts within threshold hours.

        Filters the event DataFrame to "things that happened in the last
        N hours" and reshapes each row into a dict the alerts panel can
        render. Default window is 48 h — long enough to surface overnight
        events, short enough to keep stale stuff off the screen.
        """

        # Normalise timezone once (see helper) and compute the cutoff
        # timestamp — events older than this get dropped.
        dates, now_utc = _utc_dates_and_now(events_df)
        cutoff_time = now_utc - pd.Timedelta(hours=threshold_hours)
        recent_events = events_df[dates > cutoff_time]

        alerts = []
        for idx, row in recent_events.iterrows():
            # For each surviving row, compute "how long ago" in hours and
            # build a flat dict. NaT-safe: if the date failed to parse we
            # default to 0.0 instead of crashing the UI render.
            row_dt = pd.to_datetime(row['date'], utc=True, errors='coerce')
            time_ago_h = ((now_utc - row_dt).total_seconds() / 3600
                          if pd.notna(row_dt) else 0.0)
            alert = {
                'type': row.get('type', 'Unknown'),
                'location': row.get('location', 'Unknown'),
                'time_ago_hours': time_ago_h,
                'impact': row.get('impact', 'Unknown'),
                'action': RiskAnalytics._get_recommended_action(row.get('type'), row.get('impact')),
            }
            alerts.append(alert)

        return alerts

    @staticmethod
    def _get_recommended_action(event_type, impact_level):
        """Get recommended action based on event type and impact.

        Pure lookup table: for every (event_type, impact_level) pair we
        support, return a short imperative the operator can act on.
        Unknown combinations fall through to a neutral "monitor" message
        so the UI never shows a blank action column.
        """

        # Nested dict keyed first by event type, then by severity.
        # Adding a new event type means adding one entry here — no other
        # files need changing.
        actions = {
            'Military Strike': {
                'Critical': '🚨 Reroute vessels immediately, activate contingency plans',
                'High': '⚠️ Monitor closely, prepare to reroute',
                'Medium': '📍 Monitor situation',
            },
            'Port Disruption': {
                'Critical': '🚨 Contact port authority, arrange alternative port',
                'High': '⚠️ Confirm ETAs with port operator',
                'Medium': '📍 Monitor port status updates',
            },
            'Political Instability': {
                'Critical': '🚨 Review insurance coverage, adjust routes',
                'High': '⚠️ Increase security measures',
                'Medium': '📍 Continue monitoring',
            },
            'Weather Hazard': {
                'Critical': '🚨 Reroute immediately, severe storm warning',
                'High': '⚠️ Prepare for heavy weather',
                'Medium': '📍 Monitor weather service updates',
            },
        }

        # Double `.get()` with a default at the end means "if either the
        # type or the severity is unknown, return the neutral message".
        return (actions.get(event_type, {}).get(impact_level, '📍 Monitor situation'))

    @staticmethod
    def calculate_cost_impact(events_df, oil_price, exchange_rates):
        """Calculate financial impact of events.

        Translates current events + oil price into a USD figure the
        Impact tab can display. The model is deliberately simple — a
        few multipliers on a daily baseline — because exact numbers
        aren't available; the dashboard's job is to show the *direction
        and magnitude* of cost pressure, not to invoice anyone.
        """

        # Base reference costs in USD/day per vessel. These are public
        # rule-of-thumb numbers; the multipliers below scale them.
        daily_shipping_rate = 50000  # per vessel
        fuel_daily = 8000  # per vessel

        # Oil multiplier: today's WTI divided by the $90 baseline.
        # If oil = $108, multiplier = 1.2 → fuel costs rise 20 %.
        oil_multiplier = 1.0
        if oil_price:
            oil_multiplier = oil_price / 90  # baseline $90/barrel

        # Event multiplier: each Critical event adds 30 % to route cost,
        # each High event adds 15 %. Empirical scaling — bigger penalty
        # for confirmed-critical because reroutes are forced, not optional.
        event_multiplier = 1.0
        critical_events = len(events_df[events_df['impact'] == 'Critical'])
        high_events = len(events_df[events_df['impact'] == 'High'])

        event_multiplier = 1 + (critical_events * 0.3) + (high_events * 0.15)

        # Figure out fleet exposure: how many vessels would actually feel
        # this? We look at which routes the events tag as affected and
        # take the *largest* such route's fleet size as a conservative
        # upper bound. If no route info is present, fall back to 30.
        affected_route_names = []
        if "affected_routes" in events_df.columns:
            affected_route_names = events_df["affected_routes"].explode().dropna().unique().tolist()
        if affected_route_names:
            affected_vessels = max(ROUTE_FLEET_SIZES.get(r, 30) for r in affected_route_names)
        else:
            affected_vessels = 30

        # Daily cost increase: extra fuel cost (oil-driven) plus extra
        # shipping cost (event-risk-driven), minus the baseline shipping
        # cost so the result is purely the *delta* due to current
        # conditions — not the absolute spend.
        daily_cost_increase = (
            (fuel_daily * oil_multiplier * affected_vessels) +
            (daily_shipping_rate * event_multiplier * affected_vessels) -
            (daily_shipping_rate * affected_vessels)
        )

        # Clamp at 0 (the delta can't be negative for the UI's purpose),
        # then project out to weekly and monthly figures.
        return {
            'daily_cost_increase_usd': max(0, daily_cost_increase),
            'weekly_cost_increase_usd': max(0, daily_cost_increase * 7),
            'monthly_cost_increase_usd': max(0, daily_cost_increase * 30),
            'affected_vessels': affected_vessels,
            'oil_multiplier': round(oil_multiplier, 2),
            'event_risk_multiplier': round(event_multiplier, 2),
        }

    @staticmethod
    def get_summary_metrics(events_df, oil_price, shipping_index):
        """Get all summary metrics for dashboard.

        Top-level KPI builder called once per render. Returns the dict
        the green/amber/red status bar reads from. Always returns a
        complete dict — even when the event feed is empty — so the UI
        layer never has to null-check individual keys.
        """

        # Empty-feed early exit: if the events DataFrame is missing or
        # doesn't even have the 'impact' column (a degenerate state seen
        # when every upstream is down), return a safe placeholder dict
        # and a message explaining what's still live.
        if events_df is None or len(events_df) == 0 or "impact" not in events_df.columns:
            return {
                'total_events': 0,
                'critical_events': 0,
                'high_events': 0,
                'events_last_48h': 0,
                'oil_price_usd': round(oil_price, 2) if oil_price else None,
                'shipping_index': shipping_index,
                'worst_affected_region': '—',
                'recommendation': 'Live event feed unavailable — chokepoint status driven by NGA + AIS only.',
            }

        # Build the "events in the last 48 h" counter using the same
        # tz-safe helper used elsewhere.
        dates, now_utc = _utc_dates_and_now(events_df)
        events_last_48h = int((dates > (now_utc - pd.Timedelta(hours=48))).sum())

        summary = {
            'total_events': len(events_df),
            'critical_events': len(events_df[events_df['impact'] == 'Critical']),
            'high_events': len(events_df[events_df['impact'] == 'High']),
            'events_last_48h': events_last_48h,
            'oil_price_usd': round(oil_price, 2) if oil_price else None,
            'shipping_index': shipping_index,
            'worst_affected_region': 'TBD',
            'recommendation': 'Monitor closely',
        }

        # Find the most-frequent location and call that the worst-
        # affected region. Crude but informative — shows the operator
        # the single hotspot they should look at first.
        if len(events_df) > 0:
            region_counts = events_df.groupby('location').size().sort_values(ascending=False)
            if len(region_counts) > 0:
                summary['worst_affected_region'] = region_counts.index[0]

        # Recommendation ladder: each branch corresponds to a specific
        # operational posture (contingency / review / elevated / normal).
        # Order matters — the most severe condition wins.
        if summary['critical_events'] > 2:
            summary['recommendation'] = '🚨 CRITICAL: Multiple critical events detected. Activate contingency protocols.'
        elif summary['high_events'] > 3:
            summary['recommendation'] = '⚠️ HIGH RISK: Several high-impact events. Review shipping routes immediately.'
        elif summary['events_last_48h'] > 5:
            summary['recommendation'] = '📍 ELEVATED: Recent activity uptick. Increase monitoring.'
        else:
            summary['recommendation'] = '✅ NORMAL: Situation stable, continue routine monitoring.'

        return summary
