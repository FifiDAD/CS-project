"""Test script to verify all API keys are working"""

import sys
from api_integrations import APIClient
from api_config import (
    NEWSAPI_KEY, FRED_API_KEY, OPENWEATHER_KEY, GUARDIAN_API_KEY
)

def test_all_apis():
    """Test all configured APIs"""
    
    print("=" * 60)
    print("TESTING ALL APIS")
    print("=" * 60)
    
    # Test ACLED (no key needed)
    print("\n1. Testing ACLED (Armed Conflict Data)...")
    try:
        events = APIClient.get_acled_events(limit=5)
        if len(events) > 0:
            print(f"   ✅ SUCCESS: Retrieved {len(events)} events")
            print(f"   Sample: {events.iloc[0].get('country', 'Unknown')}")
        else:
            print("   ⚠️ No events returned (API working)")
    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
    
    # Test GDELT (no key needed)
    print("\n2. Testing GDELT (Global Events)...")
    try:
        data = APIClient.get_gdelt_events()
        if data:
            print(f"   ✅ SUCCESS: Retrieved GDELT data")
        else:
            print("   ⚠️ No data returned")
    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
    
    # Test NewsAPI
    print("\n3. Testing NewsAPI...")
    if NEWSAPI_KEY == "YOUR_NEWSAPI_KEY_HERE":
        print("   ⏭️  SKIPPED: Add NEWSAPI_KEY to api_config.py")
    else:
        try:
            news = APIClient.get_news_alerts()
            if len(news) > 0:
                print(f"   ✅ SUCCESS: Retrieved {len(news)} articles")
            else:
                print("   ⚠️ No articles found")
        except Exception as e:
            print(f"   ❌ FAILED: {str(e)}")
    
    # Test FRED (Oil prices)
    print("\n4. Testing FRED API (Oil Prices)...")
    if FRED_API_KEY == "YOUR_FRED_KEY_HERE":
        print("   ⏭️  SKIPPED: Add FRED_API_KEY to api_config.py")
    else:
        try:
            oil = APIClient.get_oil_price()
            if oil:
                print(f"   ✅ SUCCESS: WTI Oil = ${oil:.2f}/bbl")
            else:
                print("   ⚠️ Could not get oil price")
        except Exception as e:
            print(f"   ❌ FAILED: {str(e)}")
    
    # Test Shipping Index
    print("\n5. Testing FRED API (Shipping Index)...")
    if FRED_API_KEY == "YOUR_FRED_KEY_HERE":
        print("   ⏭️  SKIPPED: Add FRED_API_KEY to api_config.py")
    else:
        try:
            index = APIClient.get_shipping_index()
            if index:
                print(f"   ✅ SUCCESS: Baltic Dry Index = {index:.0f}")
            else:
                print("   ⚠️ Could not get shipping index")
        except Exception as e:
            print(f"   ❌ FAILED: {str(e)}")
    
    # Test Guardian News
    print("\n6. Testing Guardian API...")
    if GUARDIAN_API_KEY == "YOUR_GUARDIAN_KEY_HERE":
        print("   ⏭️  SKIPPED: Add GUARDIAN_API_KEY to api_config.py")
    else:
        try:
            articles = APIClient.get_guardian_news()
            if len(articles) > 0:
                print(f"   ✅ SUCCESS: Retrieved {len(articles)} articles")
            else:
                print("   ⚠️ No articles found")
        except Exception as e:
            print(f"   ❌ FAILED: {str(e)}")
    
    # Test weather (no key needed)
    print("\n7. Testing NOAA Weather API (no key needed)...")
    try:
        hazards = APIClient.get_weather_hazards(lat=40, lon=-95)
        print(f"   ✅ SUCCESS: API functional")
        if hazards:
            print(f"   Found {len(hazards)} alerts in that region")
    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
    
    # Test World Bank
    print("\n8. Testing World Bank API (no key needed)...")
    try:
        trade = APIClient.get_world_bank_trade("US")
        if trade:
            print(f"   ✅ SUCCESS: Retrieved trade data")
        else:
            print("   ⚠️ Could not get trade data")
    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
    
    # Test Exchange Rates
    print("\n9. Testing Exchange Rates API (no key needed)...")
    try:
        rates = APIClient.get_exchange_rates()
        if rates:
            print(f"   ✅ SUCCESS: Retrieved {len(rates)} currency rates")
        else:
            print("   ⚠️ Could not get rates")
    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print("\n📋 SUMMARY:")
    print("- APIs without keys (ACLED, GDELT, NOAA, World Bank): Always Free")
    print("- APIs requiring keys: Get free tier from:")
    print("  • NewsAPI: https://newsapi.org/")
    print("  • FRED: https://fred.stlouisfed.org/docs/api/")
    print("  • Guardian: https://open-platform.theguardian.com/")
    print("\n✏️  Edit api_config.py with your keys and run again")
    print("=" * 60)

if __name__ == "__main__":
    test_all_apis()
