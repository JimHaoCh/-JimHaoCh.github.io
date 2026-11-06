"""NE-500/501 numeric command formatting and rate conversion, without device I/O."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import math

VALID_RATE_UNITS = {"UM", "MM", "UH", "MH"}
_RATE_ALTERNATE_UNIT = {"MH": "UH", "UH": "MH", "MM": "UM", "UM": "MM"}

def format_pump_number(value: float, significant_digits: int = 4, *, round_down: bool = False) -> str:
    """Format numeric data for the NE-501 command parser.

    The pump manual specifies at most four numeric digits and at most three
    digits to the right of the decimal point. Scientific notation is not used.
    Positive values that cannot be represented under those constraints raise
    ValueError so the caller can choose a different unit.
    """
    if significant_digits != 4:
        raise ValueError("NE-501 numeric data must use at most four digits")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 9999:
        raise ValueError("Pump values must be finite and non-negative, and at most 9999")
    if not math.isfinite(value):
        raise ValueError("Pump values must be finite and non-negative")
    if value == 0:
        return "0"
    if value > 9999:
        raise ValueError("Pump numeric value exceeds the four-digit limit")

    integer_digits = int(math.floor(math.log10(value))) + 1 if value >= 1 else 0
    if integer_digits > 4:
        raise ValueError("Pump numeric value exceeds the four-digit limit")
    decimals = min(3, max(0, 4 - integer_digits))

    quantizer = Decimal("1").scaleb(-decimals)
    rounding = ROUND_FLOOR if round_down else ROUND_HALF_UP
    rounded = Decimal(str(value)).quantize(quantizer, rounding=rounding)
    if rounded <= 0:
        raise ValueError("Value is too small for the selected pump unit")
    if rounded > Decimal("9999"):
        raise ValueError("Rounded pump value exceeds the four-digit limit")

    text = f"{rounded:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    digit_count = sum(ch.isdigit() for ch in text)
    fractional_digits = len(text.split(".", 1)[1]) if "." in text else 0
    if digit_count > 4 or fractional_digits > 3:
        raise ValueError("Value cannot be represented in NE-501 numeric format")
    return text


def convert_rate(value: float, from_unit: str, to_unit: str) -> float:
    """Convert rate while preserving the user's time basis (min or hr)."""
    if from_unit not in VALID_RATE_UNITS or to_unit not in VALID_RATE_UNITS:
        raise ValueError("Invalid rate unit")
    if from_unit[1] != to_unit[1]:
        raise ValueError("Rate conversion must preserve min/hr time basis")
    if from_unit == to_unit:
        return value
    if from_unit[0] == "M" and to_unit[0] == "U":
        return value * 1000.0
    if from_unit[0] == "U" and to_unit[0] == "M":
        return value / 1000.0
    raise ValueError("Unsupported rate conversion")


def normalize_rate(value: float, unit: str, *, round_down: bool = False) -> tuple[float, str, str]:
    """Return (programmed value, unit, text), switching mL/µL when needed."""
    if value <= 0:
        raise ValueError("Flow rate must be greater than zero")
    if unit not in VALID_RATE_UNITS:
        raise ValueError("Invalid flow-rate unit")

    candidates = [(value, unit)]
    alt = _RATE_ALTERNATE_UNIT[unit]
    candidates.append((convert_rate(value, unit, alt), alt))
    errors: list[str] = []
    for candidate_value, candidate_unit in candidates:
        try:
            text = format_pump_number(candidate_value, round_down=round_down)
            return float(text), candidate_unit, text
        except ValueError as exc:
            errors.append(str(exc))
    raise ValueError(
        f"Flow rate {value:g} {unit} cannot be represented by the NE-501 numeric format"
    )


