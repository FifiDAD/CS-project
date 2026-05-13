"""Analytics Engine - Business Impact Analysis"""

import pandas as pd
from datetime import datetime, timedelta


def _utc_dates_and_now(events_df):
    """Return (UTC-aware date Series, UTC-aware "now") for time-window math.

    Live event sources mix tz-aware UTC datetimes (USGS, GDELT DOC) with
    naive strptime results, and pandas coerces them inconsistently. This
    helper normalises both sides so comparisons never raise TypeError.
    """
    dates = pd.to_datetime(events_df['date'], utc=True, errors='coerce')
    now = pd.Timestamp.now(tz='UTC')
    return dates, now
from config import ROUTE_FLEET_SIZES

class RiskAnalytics:
    """Calculate and analyze business risks"""
    
    @staticmethod
    def calculate_supply_chain_impact(events_df, oil_price, shipping_index):
        """Calculate supply chain impact from events and costs"""
        
        # Start with safe default values before adding live data.
        metrics = {
            'event_count': len(events_df),
            'critical_zones': 0,
            'cost_impact_percentage': 0,
            'shipping_cost_trend': 'Stable',
            'trade_risk': 'Low',
        }
        
        # Critical zones (conflict areas)
        metrics['critical_zones'] = len(events_df[events_df['impact'] == 'Critical'])
        
        # Oil price impact (if available)
        if oil_price:
            # Baseline is around $90 per barrel
            baseline_oil = 90
            percentage_change = ((oil_price - baseline_oil) / baseline_oil) * 100
            metrics['cost_impact_percentage'] = max(-50, min(percentage_change, 50))
        
        # Shipping index trend
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
        """Get recent alerts within threshold hours"""
        
        dates, now_utc = _utc_dates_and_now(events_df)
        cutoff_time = now_utc - pd.Timedelta(hours=threshold_hours)
        recent_events = events_df[dates > cutoff_time]

        alerts = []
        for idx, row in recent_events.iterrows():
            # Turn each recent event into one alert item for the UI.
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
        """Get recommended action based on event type and impact"""
        
        # Simple action lookup based on event type and severity.
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
        
        return (actions.get(event_type, {}).get(impact_level, '📍 Monitor situation'))

    @staticmethod
    def calculate_cost_impact(events_df, oil_price, exchange_rates):
        """Calculate financial impact of events"""
        
        # Base costs (USD per day)
        # These are rough reference costs used for dashboard estimates.
        daily_shipping_rate = 50000  # per vessel
        fuel_daily = 8000  # per vessel
        
        # Adjust for oil price
        oil_multiplier = 1.0
        if oil_price:
            oil_multiplier = oil_price / 90  # baseline $90/barrel
        
        # Adjust for events
        # Critical and high events increase the route risk multiplier.
        event_multiplier = 1.0
        critical_events = len(events_df[events_df['impact'] == 'Critical'])
        high_events = len(events_df[events_df['impact'] == 'High'])
        
        event_multiplier = 1 + (critical_events * 0.3) + (high_events * 0.15)
        
        # Fleet size based on affected routes (vessels/day reference sizes)
        affected_route_names = []
        if "affected_routes" in events_df.columns:
            affected_route_names = events_df["affected_routes"].explode().dropna().unique().tolist()
        if affected_route_names:
            # Use the largest affected route as the fleet exposure estimate.
            affected_vessels = max(ROUTE_FLEET_SIZES.get(r, 30) for r in affected_route_names)
        else:
            affected_vessels = 30
        
        daily_cost_increase = (
            (fuel_daily * oil_multiplier * affected_vessels) +
            (daily_shipping_rate * event_multiplier * affected_vessels) -
            (daily_shipping_rate * affected_vessels)
        )
        
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
        """Get all summary metrics for dashboard"""

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
        
        # Determine worst affected region
        if len(events_df) > 0:
            # Most frequent location is used as the current hotspot.
            region_counts = events_df.groupby('location').size().sort_values(ascending=False)
            if len(region_counts) > 0:
                summary['worst_affected_region'] = region_counts.index[0]
        
        # Recommendation based on metrics
        if summary['critical_events'] > 2:
            summary['recommendation'] = '🚨 CRITICAL: Multiple critical events detected. Activate contingency protocols.'
        elif summary['high_events'] > 3:
            summary['recommendation'] = '⚠️ HIGH RISK: Several high-impact events. Review shipping routes immediately.'
        elif summary['events_last_48h'] > 5:
            summary['recommendation'] = '📍 ELEVATED: Recent activity uptick. Increase monitoring.'
        else:
            summary['recommendation'] = '✅ NORMAL: Situation stable, continue routine monitoring.'
        
        return summary
