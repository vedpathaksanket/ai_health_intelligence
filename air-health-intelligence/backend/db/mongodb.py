"""
db/mongodb.py
Async MongoDB client using Motor. Provides a singleton database instance
and collection helpers used across repositories.
"""
from __future__ import annotations

import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from backend.core.config import settings

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


async def connect_db() -> None:
    """Open Motor connection pool and create indexes."""
    global _client, _db
    logger.info("Connecting to MongoDB at %s", settings.mongodb_uri)
    _client = AsyncIOMotorClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=5000,
        maxPoolSize=20,
        minPoolSize=2,
    )
    _db = _client[settings.mongodb_db_name]
    await _ensure_indexes()
    logger.info("MongoDB connected — db: %s", settings.mongodb_db_name)


async def close_db() -> None:
    """Close Motor connection pool."""
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB connection closed.")


def get_db() -> AsyncIOMotorDatabase:
    """Return the active database. Raises if not connected."""
    if _db is None:
        raise RuntimeError("Database not initialised. Call connect_db() first.")
    return _db


# ── Collection helpers ────────────────────────────────────────────────────────

def col_air_quality():
    return get_db()["air_quality_readings"]

def col_alerts():
    return get_db()["alerts"]

def col_thresholds():
    return get_db()["alert_thresholds"]

def col_chat_history():
    return get_db()["chat_history"]


# ── Index creation ────────────────────────────────────────────────────────────

async def _ensure_indexes() -> None:
    """Create compound indexes for time-series query performance."""
    db = get_db()

    # air_quality_readings: city + timestamp compound (most common query pattern)
    await db["air_quality_readings"].create_indexes([
        IndexModel([("city", ASCENDING), ("timestamp", DESCENDING)], name="city_ts_desc"),
        IndexModel([("timestamp", DESCENDING)], name="ts_desc"),
        IndexModel([("aqi", DESCENDING)], name="aqi_desc"),
    ])

    # alerts: status + created_at for active alert queries
    await db["alerts"].create_indexes([
        IndexModel([("status", ASCENDING), ("created_at", DESCENDING)], name="status_created"),
        IndexModel([("city", ASCENDING)], name="alert_city"),
    ])

    # chat_history: session_id + timestamp
    await db["chat_history"].create_indexes([
        IndexModel([("session_id", ASCENDING), ("timestamp", ASCENDING)], name="session_ts"),
    ])

    logger.info("Database indexes verified / created.")
