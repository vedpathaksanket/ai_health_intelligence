"""
utils/aqi_calculator.py
US EPA AQI calculation for individual pollutants and composite index.
Reference: https://www.airnow.gov/publications/air-quality-index/technical-assistance-document-for-reporting-the-daily-aqi/
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class _Breakpoint:
    c_lo: float
    c_hi: float
    i_lo: int
    i_hi: int


# ── EPA breakpoints ───────────────────────────────────────────────────────────

_PM25_BP: List[_Breakpoint] = [
    _Breakpoint(0.0,   12.0,   0,   50),
    _Breakpoint(12.1,  35.4,  51,  100),
    _Breakpoint(35.5,  55.4, 101,  150),
    _Breakpoint(55.5, 150.4, 151,  200),
    _Breakpoint(150.5, 250.4, 201, 300),
    _Breakpoint(250.5, 350.4, 301, 400),
    _Breakpoint(350.5, 500.4, 401, 500),
]

_PM10_BP: List[_Breakpoint] = [
    _Breakpoint(0,    54,    0,   50),
    _Breakpoint(55,  154,   51,  100),
    _Breakpoint(155, 254,  101,  150),
    _Breakpoint(255, 354,  151,  200),
    _Breakpoint(355, 424,  201,  300),
    _Breakpoint(425, 504,  301,  400),
    _Breakpoint(505, 604,  401,  500),
]

_NO2_BP: List[_Breakpoint] = [
    _Breakpoint(0,    53,    0,   50),
    _Breakpoint(54,  100,   51,  100),
    _Breakpoint(101, 360,  101,  150),
    _Breakpoint(361, 649,  151,  200),
    _Breakpoint(650, 1249, 201,  300),
    _Breakpoint(1250, 1649, 301, 400),
    _Breakpoint(1650, 2049, 401, 500),
]

_O3_BP: List[_Breakpoint] = [
    _Breakpoint(0,    54,    0,   50),
    _Breakpoint(55,  124,   51,  100),
    _Breakpoint(125, 164,  101,  150),
    _Breakpoint(165, 204,  151,  200),
    _Breakpoint(205, 404,  201,  300),
]

_CO_BP: List[_Breakpoint] = [      # CO in ppm × 10 → stored as mg/m³ approx
    _Breakpoint(0.0,   4.4,    0,   50),
    _Breakpoint(4.5,   9.4,   51,  100),
    _Breakpoint(9.5,  12.4,  101,  150),
    _Breakpoint(12.5, 15.4,  151,  200),
    _Breakpoint(15.5, 30.4,  201,  300),
    _Breakpoint(30.5, 40.4,  301,  400),
    _Breakpoint(40.5, 50.4,  401,  500),
]


def _linear_interp(bp: _Breakpoint, c: float) -> float:
    """EPA piecewise linear interpolation formula."""
    return (bp.i_hi - bp.i_lo) / (bp.c_hi - bp.c_lo) * (c - bp.c_lo) + bp.i_lo


def _compute_sub_index(breakpoints: List[_Breakpoint], value: float) -> Optional[float]:
    """Return sub-index AQI for a single pollutant at a given concentration."""
    for bp in breakpoints:
        if bp.c_lo <= value <= bp.c_hi:
            return _linear_interp(bp, value)
    if value > breakpoints[-1].c_hi:
        return 500.0
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def calculate_aqi(
    pm25: Optional[float] = None,
    pm10: Optional[float] = None,
    no2: Optional[float] = None,
    o3: Optional[float] = None,
    co: Optional[float] = None,
    so2: Optional[float] = None,
) -> Tuple[float, str]:
    """
    Compute composite AQI as the maximum sub-index across available pollutants.
    Returns (aqi_value, dominant_pollutant_name).
    """
    sub_indices: Dict[str, float] = {}

    if pm25 is not None and pm25 >= 0:
        v = _compute_sub_index(_PM25_BP, round(pm25, 1))
        if v is not None: sub_indices["PM2.5"] = v

    if pm10 is not None and pm10 >= 0:
        v = _compute_sub_index(_PM10_BP, int(pm10))
        if v is not None: sub_indices["PM10"] = v

    if no2 is not None and no2 >= 0:
        v = _compute_sub_index(_NO2_BP, int(no2))
        if v is not None: sub_indices["NO2"] = v

    if o3 is not None and o3 >= 0:
        v = _compute_sub_index(_O3_BP, int(o3))
        if v is not None: sub_indices["O3"] = v

    if co is not None and co >= 0:
        v = _compute_sub_index(_CO_BP, round(co, 1))
        if v is not None: sub_indices["CO"] = v

    if not sub_indices:
        return 0.0, "unknown"

    dominant = max(sub_indices, key=sub_indices.__getitem__)
    return round(sub_indices[dominant], 1), dominant


def aqi_to_health_risk(aqi: float) -> Dict[str, str]:
    """Map AQI value to health risk metadata."""
    if aqi <= 50:
        return {
            "category": "Good",
            "risk_level": "minimal",
            "color": "#00E400",
            "outdoor_activity": "safe",
            "advisory": "Air quality is satisfactory. Outdoor activities are safe for everyone.",
        }
    elif aqi <= 100:
        return {
            "category": "Moderate",
            "risk_level": "low",
            "color": "#FFFF00",
            "outdoor_activity": "safe",
            "advisory": "Acceptable air quality. Unusually sensitive people should consider limiting prolonged outdoor exertion.",
        }
    elif aqi <= 150:
        return {
            "category": "Unhealthy for Sensitive Groups",
            "risk_level": "moderate",
            "color": "#FF7E00",
            "outdoor_activity": "limit",
            "advisory": "Sensitive groups (children, elderly, asthma patients) should limit outdoor exertion.",
        }
    elif aqi <= 200:
        return {
            "category": "Unhealthy",
            "risk_level": "high",
            "color": "#FF0000",
            "outdoor_activity": "limit",
            "advisory": "Everyone may experience health effects. Sensitive groups should avoid outdoor exertion. Wear N95 masks outdoors.",
        }
    elif aqi <= 300:
        return {
            "category": "Very Unhealthy",
            "risk_level": "very_high",
            "color": "#8F3F97",
            "outdoor_activity": "avoid",
            "advisory": "Health alert: everyone should avoid prolonged outdoor activities. Stay indoors with air purifiers running.",
        }
    else:
        return {
            "category": "Hazardous",
            "risk_level": "extreme",
            "color": "#7E0023",
            "outdoor_activity": "avoid",
            "advisory": "Emergency conditions. Entire population is at risk. Stay indoors, seal windows, use HEPA air purifiers.",
        }
