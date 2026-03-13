# Global Events Dashboard

A comprehensive Streamlit-based dashboard for tracking global conflicts, military strikes, and geopolitical events that affect business operations and shipping routes.

## Features

- **Interactive Map**: Visual representation of active conflict zones and shipping route disruptions
- **Events Tracking**: Real-time monitoring of military strikes, port disruptions, and political instability
- **Shipping Route Status**: Current status of major global shipping corridors
- **Risk Analysis**: Regional risk assessment and business impact analysis
- **Event Filtering**: Filter events by type, impact level, and search terms
- **KPI Dashboard**: Key performance indicators for quick risk assessment
- **Data Export**: Export events data in CSV format
- **Automated Risk Assessment**: Automatic calculation of overall business risk level

## Dashboard Sections

### 1. Interactive Map
- Shows locations of conflict events on a global map
- Color-coded markers by event type
- Major shipping routes overlay
- Click on markers for detailed event information

### 2. Events List
- Detailed list of all active events
- Sorted by date (most recent first)
- Full event details including impact and business implications
- Searchable and filterable

### 3. Shipping Routes
- Status of 5 major global shipping routes
- Traffic levels and cost impacts
- Average delay estimates
- Route descriptions and critical trade percentages

### 4. Risk Analysis
- Regional risk assessment by area
- Event type and impact level distributions
- Business risk level calculation
- Recommendations based on current threat level

## Project Structure

```
Logistics_dashboard/
├── app.py                  # Main Streamlit application
├── config.py              # Configuration and constants
├── sample_data.py         # Sample data generation
├── maps.py               # Map visualization functions
├── components.py         # UI components
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

## Installation

1. Navigate to the project directory:
```bash
cd Logistics_dashboard
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

## Running the Dashboard

```bash
streamlit run app.py
```

The dashboard will open in your default browser at `http://localhost:8501`

## Data Source

Currently using sample data for demonstration. To integrate real data:

1. Modify `sample_data.py` to fetch from your actual data sources
2. Update API connections in respective modules
3. Implement data refresh schedule

## Event Types

- **Military Strike**: Armed conflict or military action
- **Port Disruption**: Port or terminal closure/disruption
- **Terrorist Activity**: Reported terrorist incidents
- **Political Instability**: Border tensions or political unrest
- **Supply Chain Alert**: General supply chain disruptions
- **Weather Hazard**: Severe weather affecting shipping

## Impact Levels

- **Critical**: Immediate action required, major business impact
- **High**: Monitor closely, significant impact expected
- **Medium**: Worth monitoring, potential impact
- **Low**: Low priority, minimal impact

## Customization

### Adding New Events

Edit `sample_data.py` and add entries to the `get_sample_events()` function.

### Adding New Shipping Routes

Modify `MAJOR_SHIPPING_ROUTES` in `config.py` with route coordinates and status.

### Changing Map Provider

Edit the `tiles` parameter in `maps.py` `create_base_map()` function:
- "OpenStreetMap" (default)
- "CartoDB positron"
- "CartoDB voyager"

## Requirements

- Python 3.8+
- Streamlit 1.28.1+
- Pandas 2.1.3+
- Folium 0.14.0+

## Features for Real Implementation

When connecting to real data:

1. **Real-time Updates**: Connect to live event APIs
2. **Historical Data**: Store and analyze historical trends
3. **Alerts**: Email/SMS notifications for critical events
4. **User Accounts**: Role-based access control
5. **Custom Routes**: Allow users to define custom shipping routes
6. **Integration**: Connect to supply chain and business systems
7. **Analytics**: Advanced analytics and predictions

## License

Commercial Use - For business intelligence and supply chain management

## Support

For issues or questions, refer to the inline documentation in each module.
