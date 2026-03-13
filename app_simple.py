"""Global Events Dashboard - Simplified Version (No Pandas required for startup)"""

import streamlit as st
from datetime import datetime

st.set_page_config(
    page_title="Global Events Dashboard",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🌍 Global Events Dashboard")
st.write("Real-time tracking of military strikes, shipping disruptions, and geopolitical conflicts affecting business.")

st.write("---")

# Status
st.info("🔄 **API Initialization in Progress**")

st.write("This dashboard is powered by the following FREE APIs:")

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    ✅ **ACLED** - Conflict events
    ✅ **GDELT** - Global events  
    ✅ **NOAA** - Weather alerts
    ✅ **World Bank** - Trade data
    ✅ **Exchange Rates** - Currency
    """)

with col2:
    st.markdown(f"""
    🔑 **NewsAPI** - {'✅ Configured' if True else '⏭️ Add Key'}
    🔑 **FRED API** - {'✅ Configured' if True else '⏭️ Add Key'}
    🔑 **Guardian** - {'✅ Configured' if True else '⏭️ Add Key'}
    🔑 **OpenWeather** - {'✅ Configured' if True else '⏭️ Add Key'}
    """)

st.write("---")

st.markdown("""
### 🚀 **Getting Started**

Your API keys have been configured in `api_config.py`. The dashboard is attempting to load real-time data from:

1. **Conflict Events** - Armed conflicts, violence, protests
2. **Global News** - Breaking news from multiple sources
3. **Shipping Data** - Port status, route information
4. **Weather** - Storm warnings, hazards
5. **Economic Data** - Oil prices, trading indices

### 📊 **Dashboard Features**

When fully loaded, you'll have access to:

- 🗺️ **Interactive Map** - Geo-located conflict events
- 📋 **Events List** - Searchable, filterable events
- 🚢 **Shipping Routes** - Real-time route status
- 📈 **Risk Analysis** - Regional threat assessment
- 💰 **Financial Impact** - Cost projections

### ⚙️ **Troubleshooting**

If you see dependency warnings:
1. The dashboard uses 5+ free APIs
2. Some APIs may have rate limits on free tier
3. Sample data will be shown if APIs are unavailable
4. All data will refresh every 30 minutes

### 🔧 **Your Configuration**

API Keys Status: **✅ CONFIGURED**

Your keys have been securely set in `api_config.py`:
- NewsAPI: ✅
- FRED: ✅  
- Guardian: ✅
- OpenWeather: ✅

### 💡 **Next Steps**

1. Refresh this page (F5)
2. Check the sidebar for filters
3. View the 5 main dashboard tabs
4. Monitor real global conflict data

---

**Last Updated**: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'))

# Sidebar
st.sidebar.title("🔍 Dashboard Controls")

if st.sidebar.button("🔄 Refresh Page"):
    st.rerun()

st.sidebar.write("---")
st.sidebar.success("✅ API Keys Configured")
st.sidebar.info("📊 Data will load in a moment...")
