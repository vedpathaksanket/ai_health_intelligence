"""
api/routes/websocket.py
WebSocket endpoints for real-time alerts and live AQI data streaming.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from backend.db.mongodb import col_air_quality
from backend.utils.ws_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])


# ── /ws/alerts ────────────────────────────────────────────────────────────────

@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket, city: Optional[str] = Query(None)):
    """
    Subscribe to real-time alert notifications.
    Optional `city` query param to filter to a specific city.
    """
    topics = ["alerts"]
    if city:
        topics.append(f"city:{city}")

    await ws_manager.connect(websocket, topics=topics)

    # Send connection ack
    await ws_manager.send_personal(websocket, {
        "type": "connection_ack",
        "message": "Connected to alert stream",
        "subscribed_topics": topics,
        "timestamp": datetime.utcnow().isoformat(),
    })

    try:
        while True:
            # Keep connection alive, process client pings
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await ws_manager.send_personal(websocket, {
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat(),
                    })
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        logger.info("Client disconnected from /ws/alerts")
    finally:
        await ws_manager.disconnect(websocket)


# ── /ws/live-data ─────────────────────────────────────────────────────────────

@router.websocket("/ws/live-data")
async def ws_live_data(
    websocket: WebSocket,
    city: Optional[str] = Query(None),
    interval: int = Query(default=30, ge=5, le=300),
):
    """
    Push latest AQI readings at a configurable interval (seconds).
    Optional `city` filter; `interval` defaults to 30s.
    """
    topics = ["live-data"]
    if city:
        topics.append(f"city:{city}")

    await ws_manager.connect(websocket, topics=topics)
    await ws_manager.send_personal(websocket, {
        "type": "stream_started",
        "interval_seconds": interval,
        "city_filter": city,
        "timestamp": datetime.utcnow().isoformat(),
    })

    try:
        while True:
            data = await _fetch_latest_snapshot(city)
            await ws_manager.send_personal(websocket, {
                "type": "live_data",
                "timestamp": datetime.utcnow().isoformat(),
                "readings": data,
            })
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        logger.info("Client disconnected from /ws/live-data")
    except asyncio.CancelledError:
        pass
    finally:
        await ws_manager.disconnect(websocket)


# ── /ws/stats ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/stats")
async def ws_stats(websocket: WebSocket):
    """Dev endpoint: stream WebSocket connection statistics every 10s."""
    await ws_manager.connect(websocket, topics=["__stats__"])
    try:
        while True:
            await ws_manager.send_personal(websocket, {
                "type": "ws_stats",
                **ws_manager.stats(),
                "timestamp": datetime.utcnow().isoformat(),
            })
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_latest_snapshot(city: Optional[str]) -> list:
    """Retrieve one latest reading per city for the live-data stream."""
    from backend.services.ingestion import CITY_COORDS
    cities = [city] if city else list(CITY_COORDS.keys())
    results = []
    for c in cities:
        doc = await col_air_quality().find_one(
            {"city": c},
            {"city": 1, "aqi": 1, "aqi_category": 1, "pollutants.pm25": 1, "timestamp": 1},
            sort=[("timestamp", -1)],
        )
        if doc:
            results.append({
                "city": doc["city"],
                "aqi": doc.get("aqi", 0),
                "aqi_category": doc.get("aqi_category", ""),
                "pm25": doc.get("pollutants", {}).get("pm25"),
                "timestamp": doc["timestamp"].isoformat() if doc.get("timestamp") else None,
            })
    return results
