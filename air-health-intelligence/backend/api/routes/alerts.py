"""
api/routes/alerts.py
CRUD endpoints for alerts and threshold configuration.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.models.alert import (
    Alert,
    AlertListResponse,
    AlertStatus,
    ThresholdConfig,
    ThresholdUpdateRequest,
)
from backend.services.alert_service import alert_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])


# ── GET /alerts/ ──────────────────────────────────────────────────────────────

@router.get("/", response_model=AlertListResponse)
async def list_alerts(
    city: Optional[str] = Query(None),
    status: AlertStatus = Query(AlertStatus.ACTIVE),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List alerts filtered by city and/or status."""
    alerts = await alert_service.list_alerts(city=city, status=status, limit=limit)
    return AlertListResponse(total=len(alerts), alerts=alerts)


# ── DELETE /alerts/{alert_id} ────────────────────────────────────────────────

@router.delete("/{alert_id}", status_code=200)
async def dismiss_alert(alert_id: str):
    """Dismiss / resolve an active alert by ID."""
    success = await alert_service.dismiss_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found or already resolved.")
    return {"status": "dismissed", "alert_id": alert_id}


# ── GET /alerts/thresholds ────────────────────────────────────────────────────

@router.get("/thresholds", response_model=ThresholdConfig)
async def get_thresholds(city: Optional[str] = Query(None)):
    """Return current threshold configuration (city-specific or global)."""
    return await alert_service.get_thresholds(city or "")


# ── POST /alerts/thresholds ───────────────────────────────────────────────────

@router.post("/thresholds", response_model=ThresholdConfig)
async def update_thresholds(body: ThresholdUpdateRequest):
    """Create or update alert thresholds for a city (or globally if city is None)."""
    existing = await alert_service.get_thresholds(body.city or "")

    updated = ThresholdConfig(
        city=body.city,
        aqi_warning=body.aqi_warning  if body.aqi_warning  is not None else existing.aqi_warning,
        aqi_danger=body.aqi_danger    if body.aqi_danger    is not None else existing.aqi_danger,
        pm25_warning=body.pm25_warning if body.pm25_warning is not None else existing.pm25_warning,
        pm25_danger=body.pm25_danger   if body.pm25_danger  is not None else existing.pm25_danger,
        no2_warning=body.no2_warning   if body.no2_warning  is not None else existing.no2_warning,
        no2_danger=body.no2_danger     if body.no2_danger   is not None else existing.no2_danger,
    )
    return await alert_service.update_thresholds(updated)
