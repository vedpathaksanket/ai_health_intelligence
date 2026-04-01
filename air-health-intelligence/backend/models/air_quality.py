"""
models/air_quality.py
Pydantic schemas for air-quality readings, responses, and ingestion payloads.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Pollutant sub-model ───────────────────────────────────────────────────────

class Pollutants(BaseModel):
    pm25: Optional[float] = Field(None, description="PM2.5 µg/m³")
    pm10: Optional[float] = Field(None, description="PM10 µg/m³")
    no2: Optional[float] = Field(None, description="NO₂ µg/m³")
    so2: Optional[float] = Field(None, description="SO₂ µg/m³")
    co: Optional[float] = Field(None, description="CO mg/m³")
    o3: Optional[float] = Field(None, description="O₃ µg/m³")


class WeatherData(BaseModel):
    temperature: Optional[float] = Field(None, description="°C")
    humidity: Optional[float] = Field(None, description="%")
    wind_speed: Optional[float] = Field(None, description="m/s")
    wind_direction: Optional[float] = Field(None, description="degrees")
    pressure: Optional[float] = Field(None, description="hPa")
    visibility: Optional[float] = Field(None, description="km")


# ── Core reading ──────────────────────────────────────────────────────────────

class AirQualityReading(BaseModel):
    """A single point-in-time air quality measurement for one city."""
    id: Optional[str] = Field(None, alias="_id")
    city: str
    country: str = "IN"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    aqi: float = Field(..., ge=0, description="Composite AQI (0–500+)")
    aqi_category: str = ""          # populated by validator
    pollutants: Pollutants = Field(default_factory=Pollutants)
    weather: WeatherData = Field(default_factory=WeatherData)
    source: str = "openaq"          # openaq | openweathermap | manual | seeded

    @field_validator("aqi_category", mode="before")
    @classmethod
    def derive_category(cls, v, info):
        # allow explicit override
        if v:
            return v
        aqi = info.data.get("aqi", 0)
        return _aqi_category(aqi)

    class Config:
        populate_by_name = True


def _aqi_category(aqi: float) -> str:
    if aqi <= 50:   return "Good"
    if aqi <= 100:  return "Moderate"
    if aqi <= 150:  return "Unhealthy for Sensitive Groups"
    if aqi <= 200:  return "Unhealthy"
    if aqi <= 300:  return "Very Unhealthy"
    return "Hazardous"


# ── API response shapes ───────────────────────────────────────────────────────

class AirQualityResponse(BaseModel):
    city: str
    current: AirQualityReading
    health_advisory: str = ""


class TrendPoint(BaseModel):
    timestamp: datetime
    aqi: float
    pm25: Optional[float] = None


class TrendStats(BaseModel):
    mean: float
    std: float
    min: float
    max: float
    trend_slope: float          # positive = worsening, negative = improving
    trend_label: str            # "Improving" | "Stable" | "Worsening"
    percentile_95: float


class HistoricalResponse(BaseModel):
    city: str
    period_hours: int
    data_points: List[TrendPoint]
    stats: TrendStats


class HeatmapEntry(BaseModel):
    city: str
    latitude: float
    longitude: float
    aqi: float
    aqi_category: str
    pm25: Optional[float] = None


class HeatmapResponse(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    cities: List[HeatmapEntry]


# ── Ingestion request ─────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    cities: Optional[List[str]] = None     # None → use configured default cities
