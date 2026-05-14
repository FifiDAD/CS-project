# ⚡ QUICK START GUIDE - Global Events Dashboard

## 🚀 Get Up and Running in 5 Minutes

### Step 1: Install Dependencies
```bash
cd /Users/alexanderovsyannikov/Desktop/Logistics_dashboard
pip install -r requirements.txt
```

### Step 2: Get Free API Keys (Optional but Recommended)
All APIs are completely FREE with these providers:

#### 🔑 **Option A: Get Keys (5 minutes)**

1. **NewsAPI** - Breaking news
   - Visit: https://newsapi.org/
   - Click "Get API Key" 
   - Sign up with email
   - Copy your key to `api_config.py`

2. **FRED API** - Oil prices & shipping costs
   - Visit: https://fred.stlouisfed.org/docs/api/fred-api.html
   - Click "Request an API Key"
   - Get instant key
   - Copy to `api_config.py`

3. **Guardian API** - News articles
   - Visit: https://open-platform.theguardian.com/
   - Request API key
   - Copy to `api_config.py`

#### 🔑 **Option B: Skip Keys (Start with Sample Data)**
- Dashboard will work with ZERO keys
- Uses free APIs (GDELT, NOAA, World Bank, Exchange Rates)
- Add keys later anytime

### Step 3: Configure API Keys
Edit `api_config.py` and replace:
```python
NEWSAPI_KEY = "YOUR_NEWSAPI_KEY_HERE"
FRED_API_KEY = "YOUR_FRED_KEY_HERE"
GUARDIAN_API_KEY = "YOUR_GUARDIAN_KEY_HERE"
OPENWEATHER_KEY = "YOUR_OPENWEATHER_KEY_HERE"
```

### Step 4: Test APIs (Optional)
```bash
python test_apis.py
```

### Step 5: Run Dashboard
```bash
.venv/bin/streamlit run app.py
```

Opens at: **http://localhost:8501**

---

## 📊 What You Get

### 5 Dashboard Tabs:
1. **🗺️ Interactive Map** - Real geo-located events
2. **📋 Events List** - All active conflicts & disruptions
3. **🚢 Shipping Routes** - Port & corridor status
4. **📈 Analytics** - Risk analysis & trends
5. **💰 Financial Impact** - Cost projections

### Real Data Sources:
- ✅ **GDELT** - Global events + armed conflict reporting (FREE)
- ✅ **NewsAPI** - Breaking news (FREE tier)
- ✅ **FRED** - Oil prices, shipping index (FREE)
- ✅ **NOAA** - Weather/storms (FREE)
- ✅ **World Bank** - Trade statistics (FREE)
- ✅ **Guardian** - News articles (FREE)
- ✅ **NGA** - Official maritime safety warnings (FREE)
- ✅ **AISStream** - Live vessel positions over WebSocket (FREE)

---

## 🆓 Total Cost: $0/Month (Free Tier)

All included APIs have free tiers with:
- **GDELT**: Unlimited
- **NOAA**: Unlimited
- **World Bank**: Unlimited
- **NewsAPI**: 500 requests/day
- **FRED**: Unlimited
- **Guardian**: Unlimited
- **NGA**: Unlimited (public maritime broadcast warnings)
- **AISStream**: Unlimited (free WebSocket token)

---

## 💡 API Keys Already Working Without Action

These don't need keys:
```
✅ GDELT - Global events + conflict reporting
✅ NOAA - Weather alerts
✅ World Bank - Trade data
✅ Exchange Rates - Currency data
✅ NGA - Maritime safety warnings
```

Dashboard works RIGHT NOW with just these!

---

## 📝 Adding Keys Later

You can add API keys anytime:

1. Get key from any provider
2. Update `api_config.py`
3. Refresh dashboard (Ctrl+R)
4. New data feeds activate instantly

---

## 🐛 Troubleshooting

**Dashboard not loading?**
```bash
# Kill and restart
pkill -f streamlit
.venv/bin/streamlit run app.py
```

**API returning no data?**
```bash
# Test individual APIs
python test_apis.py

# Check your key is correct
# Copy exact key with no spaces
```

**Rate limited?**
```bash
# Wait 60 seconds or upgrade to paid tier
# Free tiers have limits:
# - NewsAPI: 500 calls/day
# - Others: Usually 5,000+ calls/day
```

---

## 🎯 Next Steps

1. ✅ Run dashboard with sample data
2. ✅ Get free API keys (5 minutes)
3. ✅ Add keys to api_config.py
4. ✅ Refresh dashboard
5. ✅ See real global conflict data

---

## 📚 What's Inside

```
Logistics_dashboard/
├── app.py              # Main dashboard (OPEN THIS)
├── api_integrations.py # Real API calls
├── api_config.py       # INSERT YOUR KEYS HERE
├── analytics.py        # Business impact analysis
├── sample_data.py      # Fallback data
├── maps.py            # Map visualizations
├── components.py      # UI components
├── test_apis.py       # Test your keys
├── .env.example       # Key template
├── requirements.txt   # Dependencies
└── README.md          # Full documentation
```

---

## ✨ Key Features Included

- 🗺️ Interactive map with real conflict locations
- 📊 Advanced analytics & risk scoring
- 💰 Financial impact calculations
- 🚢 Shipping route monitoring
- ⏰ Real-time event timeline
- 📈 Cost impact projections
- 🎯 Region-specific risk assessment
- 📉 Trend analysis

---

## 🚀 You're Ready!

```bash
.venv/bin/streamlit run app.py
```

Visit: **http://localhost:8501**

**No API keys needed to start!**

Enjoy your Global Events Dashboard! 🌍
