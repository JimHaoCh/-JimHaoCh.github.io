"""Syringe geometry and NE-500/501 mechanical limits; no device I/O.

Source: NE-1000/500/501 Rates and Specifications, SyringePump.com.
One microlitre is one cubic millimetre, so Q = area * plunger speed.
"""
from __future__ import annotations

import math

MAX_LINEAR_SPEED_MM_MIN = 51.00464828
MIN_LINEAR_SPEED_MM_MIN = 0.004204478 * 10 / 60
FLOW_UL_MIN = {'µL/min': 1, 'mL/min': 1000, 'µL/hr': 1 / 60, 'mL/hr': 1000 / 60,
               'UM': 1, 'MM': 1000, 'UH': 1 / 60, 'MH': 1000 / 60}


def validate_diameter(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.1 <= value <= 50:
        raise ValueError('Syringe diameter must be between 0.10 and 50.00 mm')
    return float(value)


def format_diameter(value: float) -> str:
    value = validate_diameter(value)
    text = f'{value:.3f}'.rstrip('0').rstrip('.')
    if not math.isclose(float(text), value, rel_tol=0, abs_tol=1e-9) or sum(c.isdigit() for c in text) > 4:
        raise ValueError('Syringe diameter supports four numeric digits and up to three decimal places.')
    return text


def flow_ul_min(rate: float, unit: str) -> float:
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 <= rate <= 1e12:
        raise ValueError('Flow rate must be finite and non-negative.')
    if unit not in FLOW_UL_MIN:
        raise ValueError('Invalid flow-rate unit')
    return rate * FLOW_UL_MIN[unit]


def plunger_speed_mm_min(rate: float, unit: str, diameter_mm: float) -> float:
    diameter = validate_diameter(diameter_mm)
    return flow_ul_min(rate, unit) / (math.pi * diameter * diameter / 4)


def flow_limits_ul_min(diameter_mm: float) -> tuple[float, float]:
    diameter = validate_diameter(diameter_mm)
    area = math.pi * diameter * diameter / 4
    return area * MIN_LINEAR_SPEED_MM_MIN, area * MAX_LINEAR_SPEED_MM_MIN
