"""Analytics Engine - Business Impact Analysis"""

import pandas as pd
from datetime import datetime, timedelta
from config import ROUTE_FLEET_SIZES

class RiskAnalytics:
    """Calculate and analyze business risks"""
    
    @staticmethod
    def calculate_supply_chain_impact(events_df, oil_price, shipping_index):
        """Calculate supply chain impact from events and costs"""
        
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
    def estimate_delay_impact(events_df, affected_routes):
        """Estimate shipping delays from conflict events"""
        
        delay_estimates = {}
        
        for route in affected_routes:
            # Find events near route
            route_events = events_df  # In real scenario, filter by route coordinates
            
            if len(route_events) > 0:
                max_impact_event = route_events.loc[route_events['impact'].isin(['Critical', 'High']).argmax()]
                
                if len(route_events) >= 3:
                    estimated_delay = 14  # days
                elif len(route_events) >= 1:
                    estimated_delay = 7   # days
                else:
                    estimated_delay = 0   # days
                
                delay_estimates[route] = {
                    'estimated_delay_days': estimated_delay,
                    'affected_events': len(route_events),
                    'cost_increase_percent': estimated_delay * 2,  # Rough estimate
                }
            else:
                delay_estimates[route] = {
                    'estimated_delay_days': 0,
                    'affected_events': 0,
                    'cost_increase_percent': 0,
                }
        
        return delay_estimates

    @staticmethod
    def get_regional_alerts(events_df, threshold_hours=48):
        """Get recent alerts within threshold hours"""
        
        cutoff_time = datetime.now() - timedelta(hours=threshold_hours)
        recent_events = events_df[events_df['date'] > cutoff_time]
        
        alerts = []
        for idx, row in recent_events.iterrows():
            alert = {
                'type': row.get('event_type', 'Unknown'),
                'location': row.get('location', 'Unknown'),
                'time_ago_hours': (datetime.now() - row['date']).total_seconds() / 3600,
                'impact': row.get('impact', 'Unknown'),
                'action': RiskAnalytics._get_recommended_action(row.get('event_type'), row.get('impact')),
            }
            alerts.append(alert)
        
        return alerts

    @staticmethod
    def _get_recommended_action(event_type, impact_level):
        """Get recommended action based on event type and impact"""
        
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
        daily_shipping_rate = 50000  # per vessel
        fuel_daily = 8000  # per vessel
        
        # Adjust for oil price
        oil_multiplier = 1.0
        if oil_price:
            oil_multiplier = oil_price / 90  # baseline $90/barrel
        
        # Adjust for events
        event_multiplier = 1.0
        critical_events = len(events_df[events_df['impact'] == 'Critical'])
        high_events = len(events_df[events_df['impact'] == 'High'])
        
        event_multiplier = 1 + (critical_events * 0.3) + (high_events * 0.15)
        
        # Fleet size based on affected routes (vessels/day reference sizes)
        affected_route_names = []
        if "affected_routes" in events_df.columns:
            affected_route_names = events_df["affected_routes"].explode().dropna().unique().tolist()
        if affected_route_names:
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

        summary = {
            'total_events': len(events_df),
            'critical_events': len(events_df[events_df['impact'] == 'Critical']),
            'high_events': len(events_df[events_df['impact'] == 'High']),
            'events_last_48h': len(events_df[events_df['date'] > datetime.now() - timedelta(hours=48)]),
            'oil_price_usd': round(oil_price, 2) if oil_price else None,
            'shipping_index': shipping_index,
            'worst_affected_region': 'TBD',
            'recommendation': 'Monitor closely',
        }
        
        # Determine worst affected region
        if len(events_df) > 0:
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
