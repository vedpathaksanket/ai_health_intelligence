"""
services/alert_service.py
Evaluates AQI readings against thresholds and pushes WebSocket notifications.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from backend.core.config import settings
from backend.db.mongodb import col_alerts, col_thresholds
from backend.models.alert import Alert, AlertSeverity, AlertStatus, ThresholdConfig
from backend.models.air_quality import AirQualityReading
from backend.utils.ws_manager import ws_manager

logger = logging.getLogger(__name__)


class AlertService:

    # ── Threshold retrieval ───────────────────────────────────────────────────

    async def get_thresholds(self, city: str) -> ThresholdConfig:
        """Return city-specific thresholds, falling back to global defaults."""
        # Try city-specific first
        doc = await col_thresholds().find_one({"city": city})
        if not doc:
            doc = await col_thresholds().find_one({"city": None})   # global
        if doc:
            doc["_id"] = str(doc["_id"])
            return ThresholdConfig(**doc)

        # Fallback to env-configured defaults
        return ThresholdConfig(
            aqi_warning=settings.default_aqi_warning_threshold,
            aqi_danger=settings.default_aqi_danger_threshold,
            pm25_warning=settings.default_pm25_warning_threshold,
            pm25_danger=settings.default_pm25_danger_threshold,
        )

    # ── Alert evaluation ──────────────────────────────────────────────────────

    async def evaluate_reading(self, reading: AirQualityReading) -> List[Alert]:
        """
        Compare a fresh reading against configured thresholds.
        Creates and persists alerts; pushes WebSocket notifications immediately.
        """
        thresh   = await self.get_thresholds(reading.city)
        triggered: List[Alert] = []

        checks = [
            ("aqi",  reading.aqi,                         thresh.aqi_warning,  thresh.aqi_danger,  "AQI"),
            ("pm25", reading.pollutants.pm25 or 0.0,       thresh.pm25_warning, thresh.pm25_danger, "PM2.5"),
            ("no2",  reading.pollutants.no2  or 0.0,       thresh.no2_warning,  thresh.no2_danger,  "NO2"),
        ]

        for pollutant_key, value, warn_thresh, danger_thresh, label in checks:
            if value <= 0:
                continue
            if value >= danger_thresh:
                severity = AlertSeverity.DANGER
                msg = (
                    f"🚨 DANGER: {label} in {reading.city} is {value:.1f} "
                    f"(threshold: {danger_thresh}). Immediate action required."
                )
            elif value >= warn_thresh:
                severity = AlertSeverity.WARNING
                msg = (
                    f"⚠️  WARNING: {label} in {reading.city} is {value:.1f} "
                    f"(threshold: {warn_thresh}). Consider limiting outdoor activities."
                )
            else:
                continue  # below warning — no alert

            alert = Alert(
                city=reading.city,
                severity=severity,
                pollutant=pollutant_key,
                current_value=value,
                threshold_value=danger_thresh if severity == AlertSeverity.DANGER else warn_thresh,
                message=msg,
            )
            triggered.append(alert)

        if triggered:
            await self._persist_alerts(triggered)
            await self._push_ws_alerts(triggered)

        return triggered

    # ── Persistence ───────────────────────────────────────────────────────────

    @staticmethod
    async def _persist_alerts(alerts: List[Alert]) -> None:
        docs = [a.model_dump(exclude={"id"}) for a in alerts]
        if docs:
            await col_alerts().insert_many(docs)

    # ── WebSocket push ────────────────────────────────────────────────────────

    @staticmethod
    async def _push_ws_alerts(alerts: List[Alert]) -> None:
        for alert in alerts:
            payload = {
                "type": "alert",
                "severity": alert.severity.value,
                "city": alert.city,
                "pollutant": alert.pollutant,
                "current_value": alert.current_value,
                "threshold_value": alert.threshold_value,
                "message": alert.message,
                "timestamp": datetime.utcnow().isoformat(),
            }
            await ws_manager.broadcast_topic("alerts", payload)
            await ws_manager.broadcast_topic(f"city:{alert.city}", payload)

    # ── Alert management ──────────────────────────────────────────────────────

    async def list_alerts(
        self,
        city: Optional[str] = None,
        status: AlertStatus = AlertStatus.ACTIVE,
        limit: int = 50,
    ) -> List[Alert]:
        query: dict = {"status": status.value}
        if city:
            query["city"] = city
        cursor = col_alerts().find(query, sort=[("created_at", -1)]).limit(limit)
        docs = await cursor.to_list(length=limit)
        alerts = []
        for doc in docs:
            doc["_id"] = str(doc["_id"])
            alerts.append(Alert(**doc))
        return alerts

    async def dismiss_alert(self, alert_id: str) -> bool:
        from bson import ObjectId
        result = await col_alerts().update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": {"status": AlertStatus.DISMISSED.value, "resolved_at": datetime.utcnow()}},
        )
        return result.modified_count > 0

    async def update_thresholds(self, config: ThresholdConfig) -> ThresholdConfig:
        doc = config.model_dump(exclude={"id"})
        doc["updated_at"] = datetime.utcnow()
        await col_thresholds().replace_one(
            {"city": config.city},
            doc,
            upsert=True,
        )
        return config


alert_service = AlertService()
