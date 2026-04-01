"""
utils/ws_manager.py
WebSocket connection pool with topic-based routing.
Supports concurrent connections and graceful disconnection handling.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections.

    Topics:
        "alerts"     – threshold-crossing alert broadcasts
        "live-data"  – periodic AQI data pushes
        "city:{name}" – city-specific streams
    """

    def __init__(self) -> None:
        # topic → set of websockets
        self._subscriptions: Dict[str, Set[WebSocket]] = defaultdict(set)
        # websocket → set of subscribed topics
        self._connection_topics: Dict[WebSocket, Set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, topics: Optional[List[str]] = None) -> None:
        """Accept the WebSocket and subscribe to one or more topics."""
        await websocket.accept()
        topics = topics or ["alerts"]
        async with self._lock:
            for topic in topics:
                self._subscriptions[topic].add(websocket)
                self._connection_topics[websocket].add(topic)
        logger.info("WS connected | topics=%s | total=%d", topics, self.total_connections)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove websocket from all topics."""
        async with self._lock:
            topics = self._connection_topics.pop(websocket, set())
            for topic in topics:
                self._subscriptions[topic].discard(websocket)
                if not self._subscriptions[topic]:
                    del self._subscriptions[topic]
        logger.info("WS disconnected | total=%d", self.total_connections)

    # ── Sending helpers ───────────────────────────────────────────────────────

    async def send_personal(self, websocket: WebSocket, data: Any) -> None:
        """Send JSON to a single connection."""
        try:
            await websocket.send_json(data)
        except Exception as exc:
            logger.warning("Failed to send to WS: %s", exc)
            await self.disconnect(websocket)

    async def broadcast_topic(self, topic: str, data: Any) -> None:
        """Broadcast JSON payload to all subscribers of a topic."""
        payload = data if isinstance(data, (str, bytes)) else json.dumps(data, default=str)
        dead: List[WebSocket] = []

        async with self._lock:
            connections = list(self._subscriptions.get(topic, set()))

        results = await asyncio.gather(
            *[self._safe_send(ws, payload) for ws in connections],
            return_exceptions=True,
        )

        for ws, result in zip(connections, results):
            if isinstance(result, Exception):
                dead.append(ws)

        for ws in dead:
            await self.disconnect(ws)

        if connections:
            logger.debug("Broadcast to topic=%s | recipients=%d", topic, len(connections) - len(dead))

    async def broadcast_all(self, data: Any) -> None:
        """Broadcast to every connected client across all topics."""
        all_ws: Set[WebSocket] = set()
        async with self._lock:
            for ws_set in self._subscriptions.values():
                all_ws.update(ws_set)
        payload = json.dumps(data, default=str)
        await asyncio.gather(*[self._safe_send(ws, payload) for ws in all_ws], return_exceptions=True)

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _safe_send(ws: WebSocket, payload: str) -> None:
        await ws.send_text(payload)

    @property
    def total_connections(self) -> int:
        return len(self._connection_topics)

    def topic_subscriber_count(self, topic: str) -> int:
        return len(self._subscriptions.get(topic, set()))

    def stats(self) -> Dict[str, Any]:
        return {
            "total_connections": self.total_connections,
            "topics": {t: len(ws) for t, ws in self._subscriptions.items()},
        }


# Singleton instance shared across the application
ws_manager = ConnectionManager()
