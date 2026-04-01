"""
tests/test_air_quality.py
Unit and integration tests for AQI calculator and API routes.
"""
import pytest
from fastapi.testclient import TestClient
from backend.utils.aqi_calculator import calculate_aqi, aqi_to_health_risk


# ── AQI Calculator tests ──────────────────────────────────────────────────────

class TestAQICalculator:
    def test_good_pm25(self):
        aqi, pol = calculate_aqi(pm25=5.0)
        assert aqi <= 50
        assert pol == "PM2.5"

    def test_moderate_pm25(self):
        aqi, _ = calculate_aqi(pm25=20.0)
        assert 51 <= aqi <= 100

    def test_unhealthy_pm25(self):
        aqi, _ = calculate_aqi(pm25=100.0)
        assert aqi > 150

    def test_composite_takes_max(self):
        aqi_pm25_only, _ = calculate_aqi(pm25=5.0)
        aqi_with_no2, pol = calculate_aqi(pm25=5.0, no2=200.0)
        assert aqi_with_no2 > aqi_pm25_only
        assert pol == "NO2"

    def test_no_pollutants(self):
        aqi, pol = calculate_aqi()
        assert aqi == 0.0
        assert pol == "unknown"

    def test_hazardous_level(self):
        aqi, _ = calculate_aqi(pm25=400.0)
        assert aqi > 300


class TestHealthRisk:
    def test_good_range(self):
        risk = aqi_to_health_risk(25)
        assert risk["risk_level"] == "minimal"
        assert risk["outdoor_activity"] == "safe"

    def test_very_unhealthy(self):
        risk = aqi_to_health_risk(250)
        assert risk["outdoor_activity"] == "avoid"
        assert risk["risk_level"] == "very_high"

    def test_hazardous(self):
        risk = aqi_to_health_risk(350)
        assert risk["risk_level"] == "extreme"

    def test_categories(self):
        categories = {
            25: "Good",
            75: "Moderate",
            125: "Unhealthy for Sensitive Groups",
            175: "Unhealthy",
            250: "Very Unhealthy",
            350: "Hazardous",
        }
        for aqi, expected_cat in categories.items():
            risk = aqi_to_health_risk(aqi)
            assert risk["category"] == expected_cat, f"AQI {aqi}: expected {expected_cat}"


# ── Trend Engine tests ────────────────────────────────────────────────────────

class TestTrendEngine:
    def test_compute_stats_basic(self):
        import numpy as np
        from backend.services.trend_engine import TrendEngine
        engine = TrendEngine()
        aqi    = np.array([50.0, 80.0, 120.0, 90.0, 110.0])
        stats  = engine.compute_stats(aqi)
        assert abs(stats.mean - np.mean(aqi)) < 0.1
        assert stats.max == 120.0
        assert stats.min == 50.0
        assert stats.percentile_95 > stats.mean

    def test_compute_stats_empty(self):
        import numpy as np
        from backend.services.trend_engine import TrendEngine
        engine = TrendEngine()
        stats  = engine.compute_stats(np.array([]))
        assert stats.mean == 0
        assert stats.trend_label == "Stable"

    def test_trend_worsening(self):
        import numpy as np
        from backend.services.trend_engine import TrendEngine
        engine = TrendEngine()
        # Clear upward slope
        aqi    = np.linspace(50, 200, 50)
        stats  = engine.compute_stats(aqi)
        assert stats.trend_label == "Worsening"
        assert stats.trend_slope > 0

    def test_trend_improving(self):
        import numpy as np
        from backend.services.trend_engine import TrendEngine
        engine = TrendEngine()
        aqi    = np.linspace(200, 50, 50)
        stats  = engine.compute_stats(aqi)
        assert stats.trend_label == "Improving"
        assert stats.trend_slope < 0

    def test_anomaly_detection(self):
        import numpy as np
        from backend.services.trend_engine import TrendEngine
        engine = TrendEngine()
        aqi    = np.array([50.0] * 20 + [500.0])   # last is anomaly
        mask   = engine.detect_anomalies(aqi)
        assert mask[-1] == True
        assert mask[:-1].sum() == 0

    def test_smooth(self):
        import numpy as np
        from backend.services.trend_engine import TrendEngine
        engine = TrendEngine()
        noisy  = np.random.normal(100, 30, 100)
        smooth = engine.smooth(noisy, window=10)
        assert smooth.std() < noisy.std()

    def test_rolling_percentiles_shape(self):
        import numpy as np
        from backend.services.trend_engine import TrendEngine
        engine = TrendEngine()
        aqi    = np.arange(100, dtype=float)
        result = engine.rolling_percentiles(aqi, window=12, percentiles=(10, 50, 90))
        assert result.shape == (100 - 12 + 1, 3)


# ── WebSocket manager tests ───────────────────────────────────────────────────

class TestWSManager:
    @pytest.mark.asyncio
    async def test_stats_empty(self):
        from backend.utils.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        s   = mgr.stats()
        assert s["total_connections"] == 0
        assert s["topics"] == {}

    @pytest.mark.asyncio
    async def test_topic_subscriber_count(self):
        from backend.utils.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        assert mgr.topic_subscriber_count("alerts") == 0
