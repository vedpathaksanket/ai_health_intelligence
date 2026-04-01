"""
services/ingestion.py
Async data ingestion from OpenWeatherMap and OpenAQ APIs.
Fetches current air quality & weather, normalises to internal schema,
and persists to MongoDB.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.core.config import settings
from backend.db.mongodb import col_air_quality
from backend.models.air_quality import AirQualityReading, Pollutants, WeatherData
from backend.utils.aqi_calculator import calculate_aqi

logger = logging.getLogger(__name__)

# ── City coordinate lookup (India-focused defaults) ───────────────────────────
CITY_COORDS: Dict[str, tuple] = {
    "Delhi":     (28.6139, 77.2090),
    "Mumbai":    (19.0760, 72.8777),
    "Bangalore": (12.9716, 77.5946),
    "Chennai":   (13.0827, 80.2707),
    "Kolkata":   (22.5726, 88.3639),
    "Hyderabad": (17.3850, 78.4867),
    "Pune":      (18.5204, 73.8567),
    "Ahmedabad": (23.0225, 72.5714),
}


# ── OpenAQ client ─────────────────────────────────────────────────────────────

class OpenAQClient:
    BASE_URL = "https://api.openaq.org/v3"

    def __init__(self, api_key: str = "") -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=headers,
            timeout=15.0,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def fetch_latest(self, city: str, limit: int = 10) -> List[Dict]:
        """Return latest measurements for a city."""
        try:
            resp = await self._client.get(
                "/measurements",
                params={"city": city, "limit": limit, "order_by": "datetime", "sort": "desc"},
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
        except httpx.HTTPStatusError as exc:
            logger.warning("OpenAQ API error for %s: %s", city, exc)
            return []
        except Exception as exc:
            logger.error("OpenAQ unexpected error: %s", exc)
            return []

    async def close(self):
        await self._client.aclose()


# ── OpenWeatherMap client ─────────────────────────────────────────────────────

class OpenWeatherMapClient:
    BASE_URL = "https://api.openweathermap.org/data/2.5"
    AIR_URL  = "https://api.openweathermap.org/data/2.5/air_pollution"

    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._client = httpx.AsyncClient(timeout=15.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def fetch_weather(self, lat: float, lon: float) -> Optional[Dict]:
        try:
            resp = await self._client.get(
                f"{self.BASE_URL}/weather",
                params={"lat": lat, "lon": lon, "appid": self._key, "units": "metric"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("OWM weather fetch failed: %s", exc)
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def fetch_air_quality(self, lat: float, lon: float) -> Optional[Dict]:
        try:
            resp = await self._client.get(
                self.AIR_URL,
                params={"lat": lat, "lon": lon, "appid": self._key},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("OWM air quality fetch failed: %s", exc)
            return None

    async def close(self):
        await self._client.aclose()


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _parse_owm_response(
    weather_data: Optional[Dict],
    aq_data: Optional[Dict],
    city: str,
) -> Optional[AirQualityReading]:
    """Merge OWM weather + air quality API responses into AirQualityReading."""
    if not aq_data:
        return None

    components = aq_data.get("list", [{}])[0].get("components", {})
    owm_aqi_index = aq_data.get("list", [{}])[0].get("main", {}).get("aqi", 1)

    # OWM uses 1-5 scale → rough mapping to US AQI range for display
    aqi_map = {1: 25, 2: 75, 3: 125, 4: 175, 5: 250}

    pm25 = components.get("pm2_5")
    pm10 = components.get("pm10")
    no2  = components.get("no2")
    so2  = components.get("so2")
    co   = components.get("co", 0) / 1000 if components.get("co") else None  # µg→mg
    o3   = components.get("o3")

    aqi, _ = calculate_aqi(pm25=pm25, pm10=pm10, no2=no2, o3=o3, co=co)
    if aqi == 0.0:
        aqi = float(aqi_map.get(owm_aqi_index, 50))

    weather = WeatherData()
    if weather_data:
        main   = weather_data.get("main", {})
        wind   = weather_data.get("wind", {})
        weather = WeatherData(
            temperature=main.get("temp"),
            humidity=main.get("humidity"),
            wind_speed=wind.get("speed"),
            wind_direction=wind.get("deg"),
            pressure=main.get("pressure"),
            visibility=weather_data.get("visibility", 0) / 1000,
        )

    coord = CITY_COORDS.get(city, (0.0, 0.0))
    return AirQualityReading(
        city=city,
        latitude=coord[0],
        longitude=coord[1],
        aqi=aqi,
        pollutants=Pollutants(pm25=pm25, pm10=pm10, no2=no2, so2=so2, co=co, o3=o3),
        weather=weather,
        source="openweathermap",
    )


# ── Ingestion orchestrator ────────────────────────────────────────────────────

class IngestionService:
    def __init__(self) -> None:
        self._owm = OpenWeatherMapClient(settings.openweathermap_api_key)
        self._openaq = OpenAQClient(settings.openaq_api_key)

    async def ingest_city(self, city: str) -> Optional[AirQualityReading]:
        """Fetch, normalise, and store latest reading for one city."""
        coord = CITY_COORDS.get(city)
        if not coord:
            logger.warning("Unknown city: %s — skipping", city)
            return None

        lat, lon = coord
        weather_task   = self._owm.fetch_weather(lat, lon)
        air_qual_task  = self._owm.fetch_air_quality(lat, lon)

        weather_data, aq_data = await asyncio.gather(weather_task, air_qual_task, return_exceptions=False)

        reading = _parse_owm_response(weather_data, aq_data, city)
        if reading is None:
            logger.warning("Could not build reading for %s", city)
            return None

        await self._persist(reading)
        return reading

    async def ingest_cities(self, cities: Optional[List[str]] = None) -> List[AirQualityReading]:
        """Ingest multiple cities concurrently."""
        targets = cities or settings.monitored_cities_list
        results = await asyncio.gather(*[self.ingest_city(c) for c in targets], return_exceptions=True)
        readings = [r for r in results if isinstance(r, AirQualityReading)]
        logger.info("Ingestion complete: %d/%d cities succeeded", len(readings), len(targets))
        return readings

    @staticmethod
    async def _persist(reading: AirQualityReading) -> None:
        doc = reading.model_dump(exclude={"id"})
        doc["timestamp"] = reading.timestamp
        await col_air_quality().insert_one(doc)

    async def close(self):
        await self._owm.close()
        await self._openaq.close()


ingestion_service = IngestionService()
