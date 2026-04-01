"""
models/alert.py  &  models/health_risk.py
Pydantic schemas for alerts, thresholds, and health risk assessments.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
# ALERT MODELS
# ═══════════════════════════════════════════════════════════════════

class AlertSeverity(str, Enum):
    INFO    = "info"
    WARNING = "warning"
    DANGER  = "danger"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    ACTIVE    = "active"
    DISMISSED = "dismissed"
    RESOLVED  = "resolved"


class Alert(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    city: str
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.ACTIVE
    pollutant: str                      # "aqi" | "pm25" | "no2" | …
    current_value: float
    threshold_value: float
    message: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None

    class Config:
        populate_by_name = True


class AlertListResponse(BaseModel):
    total: int
    alerts: List[Alert]


class DismissRequest(BaseModel):
    alert_id: str


# ── Threshold configuration ───────────────────────────────────────────────────

class ThresholdConfig(BaseModel):
    """Per-city or global threshold overrides stored in MongoDB."""
    id: Optional[str] = Field(None, alias="_id")
    city: Optional[str] = None          # None → global default
    aqi_warning: float = 100.0
    aqi_danger: float = 150.0
    pm25_warning: float = 35.4
    pm25_danger: float = 55.4
    no2_warning: float = 100.0
    no2_danger: float = 200.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class ThresholdUpdateRequest(BaseModel):
    city: Optional[str] = None
    aqi_warning: Optional[float] = None
    aqi_danger: Optional[float] = None
    pm25_warning: Optional[float] = None
    pm25_danger: Optional[float] = None
    no2_warning: Optional[float] = None
    no2_danger: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════
# HEALTH RISK MODELS
# ═══════════════════════════════════════════════════════════════════

class VulnerableGroup(str, Enum):
    CHILDREN      = "children"
    ELDERLY       = "elderly"
    PREGNANT      = "pregnant"
    RESPIRATORY   = "respiratory_conditions"
    CARDIOVASCULAR = "cardiovascular_conditions"
    ATHLETES      = "outdoor_athletes"


class HealthRiskLevel(str, Enum):
    MINIMAL    = "minimal"
    LOW        = "low"
    MODERATE   = "moderate"
    HIGH       = "high"
    VERY_HIGH  = "very_high"
    EXTREME    = "extreme"


class RecommendedAction(BaseModel):
    group: str
    action: str
    urgency: str    # "advisory" | "recommended" | "required"


class HealthRiskAssessment(BaseModel):
    city: str
    aqi: float
    aqi_category: str
    risk_level: HealthRiskLevel
    risk_score: float               # 0–100 composite score
    primary_pollutants: List[str]
    outdoor_activity: str           # "safe" | "limit" | "avoid"
    mask_recommended: bool
    recommendations: List[RecommendedAction]
    health_advisory: str            # plain-language summary
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Chat models ───────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str               # "user" | "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    city: Optional[str] = None      # optional context override


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    health_risk: Optional[HealthRiskAssessment] = None
    sources: List[str] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)
