"""
agents/health_ai_agent.py
Conversational AI agent that answers natural-language questions about
air quality and health risks using live MongoDB data as context.

Supports both Anthropic Claude and OpenAI GPT backends.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.core.config import settings
from backend.db.mongodb import col_air_quality, col_chat_history
from backend.models.alert import ChatMessage, ChatRequest, ChatResponse, HealthRiskAssessment
from backend.utils.aqi_calculator import aqi_to_health_risk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are AirGuard AI, an expert urban air quality and public health intelligence assistant.

Your role:
- Answer questions about air pollution, AQI, and health impacts using the live data provided
- Give clear, actionable health advice based on current conditions
- Explain technical concepts (AQI, PM2.5, NO2, etc.) in plain language
- Recommend protective measures tailored to user's vulnerability (children, elderly, etc.)
- Flag dangerous conditions proactively

Data context format you will receive:
- Current AQI readings per city
- Pollutant breakdown (PM2.5, PM10, NO2, SO2, CO, O3)
- Weather conditions
- Recent trend (improving/stable/worsening)

Guidelines:
- Always ground your response in the provided live data
- Quantify risk clearly (e.g., "PM2.5 of 87 µg/m³ is 2.5× the WHO daily guideline")
- Use structured recommendations when providing health advice
- Be concise but thorough; use bullet points for action items
- If data is unavailable for a city, say so clearly
"""


class HealthAIAgent:
    """LLM-powered agent with live data retrieval."""

    def __init__(self) -> None:
        self._provider = settings.llm_provider
        self._model    = settings.llm_model

    # ── Context retrieval ─────────────────────────────────────────────────────

    async def _build_context(self, city: Optional[str] = None) -> str:
        """Fetch recent readings from MongoDB and serialise as context string."""
        since = datetime.utcnow() - timedelta(hours=6)
        query: Dict[str, Any] = {"timestamp": {"$gte": since}}
        if city:
            query["city"] = city

        cursor = col_air_quality().find(
            query,
            {"city": 1, "aqi": 1, "aqi_category": 1, "pollutants": 1, "weather": 1, "timestamp": 1},
            sort=[("timestamp", -1)],
        ).limit(20)
        docs = await cursor.to_list(length=20)

        if not docs:
            return "No recent air quality data available in the database."

        # Deduplicate: keep latest per city
        seen: Dict[str, Dict] = {}
        for doc in docs:
            c = doc.get("city", "Unknown")
            if c not in seen:
                seen[c] = doc

        lines = ["=== LIVE AIR QUALITY DATA (last 6 hours) ===\n"]
        for city_name, doc in seen.items():
            ts = doc.get("timestamp", datetime.utcnow())
            aqi = doc.get("aqi", 0)
            risk = aqi_to_health_risk(aqi)
            pollutants = doc.get("pollutants", {})
            weather    = doc.get("weather", {})
            lines.append(
                f"City: {city_name}\n"
                f"  AQI: {aqi} ({doc.get('aqi_category', risk['category'])})\n"
                f"  Recorded: {ts.strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"  Pollutants: PM2.5={pollutants.get('pm25', 'N/A')} µg/m³, "
                f"PM10={pollutants.get('pm10', 'N/A')} µg/m³, "
                f"NO2={pollutants.get('no2', 'N/A')} µg/m³, "
                f"O3={pollutants.get('o3', 'N/A')} µg/m³\n"
                f"  Weather: Temp={weather.get('temperature', 'N/A')}°C, "
                f"Humidity={weather.get('humidity', 'N/A')}%, "
                f"Wind={weather.get('wind_speed', 'N/A')} m/s\n"
                f"  Health Risk: {risk['risk_level'].upper()} — {risk['advisory']}\n"
            )

        return "\n".join(lines)

    # ── Session history ───────────────────────────────────────────────────────

    async def _load_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        cursor = col_chat_history().find(
            {"session_id": session_id},
            sort=[("timestamp", -1)],
        ).limit(limit)
        docs = await cursor.to_list(length=limit)
        docs.reverse()
        return [{"role": d["role"], "content": d["content"]} for d in docs]

    async def _save_messages(self, session_id: str, user_msg: str, assistant_msg: str) -> None:
        now = datetime.utcnow()
        await col_chat_history().insert_many([
            {"session_id": session_id, "role": "user",      "content": user_msg,       "timestamp": now},
            {"session_id": session_id, "role": "assistant", "content": assistant_msg,   "timestamp": now},
        ])

    # ── LLM call ──────────────────────────────────────────────────────────────

    async def _call_llm(self, messages: List[Dict], system: str) -> str:
        if self._provider == "anthropic":
            return await self._call_anthropic(messages, system)
        return await self._call_openai(messages, system)

    async def _call_anthropic(self, messages: List[Dict], system: str) -> str:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=self._model,
            max_tokens=settings.llm_max_tokens,
            system=system,
            messages=messages,
        )
        return response.content[0].text

    async def _call_openai(self, messages: List[Dict], system: str) -> str:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        full_messages = [{"role": "system", "content": system}] + messages
        response = await client.chat.completions.create(
            model=self._model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            messages=full_messages,
        )
        return response.choices[0].message.content

    # ── Health risk extraction ────────────────────────────────────────────────

    async def _build_health_risk(self, city: Optional[str]) -> Optional[HealthRiskAssessment]:
        """Return a structured HealthRiskAssessment for the referenced city."""
        if not city:
            return None
        doc = await col_air_quality().find_one(
            {"city": city},
            sort=[("timestamp", -1)],
        )
        if not doc:
            return None

        aqi  = doc.get("aqi", 0)
        risk = aqi_to_health_risk(aqi)
        pollutants = doc.get("pollutants", {})
        primary = [
            p for p, v in [
                ("PM2.5", pollutants.get("pm25")),
                ("PM10",  pollutants.get("pm10")),
                ("NO2",   pollutants.get("no2")),
                ("O3",    pollutants.get("o3")),
            ] if v and v > 0
        ][:3]

        from backend.models.alert import HealthRiskLevel, RecommendedAction
        return HealthRiskAssessment(
            city=city,
            aqi=aqi,
            aqi_category=risk["category"],
            risk_level=HealthRiskLevel(risk["risk_level"]),
            risk_score=min(aqi / 5, 100),
            primary_pollutants=primary,
            outdoor_activity=risk["outdoor_activity"],
            mask_recommended=aqi > 150,
            recommendations=[
                RecommendedAction(group="General Public", action=risk["advisory"], urgency="advisory"),
            ],
            health_advisory=risk["advisory"],
        )

    # ── Public interface ──────────────────────────────────────────────────────

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Process a user message and return an AI-generated response."""
        context   = await self._build_context(request.city)
        history   = await self._load_history(request.session_id)

        system = SYSTEM_PROMPT + "\n\n" + context

        messages = history + [{"role": "user", "content": request.message}]

        try:
            reply = await self._call_llm(messages, system)
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            reply = "I'm having trouble connecting to my AI backend. Please try again in a moment."

        await self._save_messages(request.session_id, request.message, reply)

        health_risk = await self._build_health_risk(request.city)

        return ChatResponse(
            session_id=request.session_id,
            reply=reply,
            health_risk=health_risk,
            sources=["Live MongoDB AQI data", f"LLM: {self._model}"],
        )


health_ai_agent = HealthAIAgent()
