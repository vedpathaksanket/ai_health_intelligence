"""
api/routes/air_quality.py
RESTful endpoints for air quality data retrieval and ingestion.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks

from backend.db.mongodb import col_air_quality
from backend.models.air_quality import (
    AirQualityResponse,
    AirQualityReading,
    HeatmapEntry,
    HeatmapResponse,
    HistoricalResponse,
    IngestRequest,
)
from backend.services.ingestion import ingestion_service, CITY_COORDS
from backend.services.trend_engine import trend_engine
from backend.services.alert_service import alert_service
from backend.utils.aqi_calculator import aqi_to_health_risk

router = APIRouter(prefix="/air-quality", tags=["Air Quality"])


# ── GET /current/{city} ───────────────────────────────────────────────────────

@router.get("/current/{city}", response_model=AirQualityResponse)
async def get_current(city: str):
    """Return the most recent AQI reading for a city."""
    doc = await col_air_quality().find_one(
        {"city": city},
        sort=[("timestamp", -1)],
    )
    if not doc:
        # Trigger on-demand ingestion if no cached data
        reading = await ingestion_service.ingest_city(city)
        if not reading:
            raise HTTPException(status_code=404, detail=f"No data found for city: {city}")
        doc = reading.model_dump()
        doc["timestamp"] = reading.timestamp

    doc["_id"] = str(doc.get("_id", ""))
    reading = AirQualityReading(**doc)
    risk    = aqi_to_health_risk(reading.aqi)

    return AirQualityResponse(
        city=city,
        current=reading,
        health_advisory=risk["advisory"],
    )


# ── GET /history/{city} ───────────────────────────────────────────────────────

@router.get("/history/{city}", response_model=HistoricalResponse)
async def get_history(
    city: str,
    hours: int = Query(default=48, ge=1, le=720, description="Look-back window in hours"),
):
    """Return historical AQI data with statistical trend analysis."""
    return await trend_engine.analyse(city, hours=hours)


# ── GET /heatmap ──────────────────────────────────────────────────────────────

@router.get("/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    cities: Optional[str] = Query(None, description="Comma-separated list of cities"),
):
    """Return latest AQI for multiple cities for map visualisation."""
    target_cities = (
        [c.strip() for c in cities.split(",")]
        if cities
        else list(CITY_COORDS.keys())
    )

    since = datetime.utcnow() - timedelta(hours=12)
    entries: List[HeatmapEntry] = []

    for city in target_cities:
        doc = await col_air_quality().find_one(
            {"city": city, "timestamp": {"$gte": since}},
            sort=[("timestamp", -1)],
        )
        if not doc:
            continue
        coord = CITY_COORDS.get(city, (0, 0))
        entries.append(HeatmapEntry(
            city=city,
            latitude=doc.get("latitude") or coord[0],
            longitude=doc.get("longitude") or coord[1],
            aqi=doc.get("aqi", 0),
            aqi_category=doc.get("aqi_category", "Unknown"),
            pm25=doc.get("pollutants", {}).get("pm25"),
        ))

    return HeatmapResponse(cities=entries)


# ── POST /ingest ──────────────────────────────────────────────────────────────

@router.post("/ingest", status_code=202)
async def trigger_ingestion(
    body: IngestRequest,
    background_tasks: BackgroundTasks,
):
    """Manually trigger data ingestion for one or more cities."""
    cities = body.cities or list(CITY_COORDS.keys())

    async def _run():
        readings = await ingestion_service.ingest_cities(cities)
        for r in readings:
            await alert_service.evaluate_reading(r)

    background_tasks.add_task(_run)
    return {"status": "ingestion_started", "cities": cities}


# ── GET /cities ───────────────────────────────────────────────────────────────

@router.get("/cities")
async def list_cities():
    """Return the list of monitored cities with coordinates."""
    return {
        "cities": [
            {"name": k, "latitude": v[0], "longitude": v[1]}
            for k, v in CITY_COORDS.items()
        ]
    }
