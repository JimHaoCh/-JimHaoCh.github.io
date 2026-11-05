from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import math
import re
import threading
import time
from typing import Iterable, Optional

from .protocol import ETX, PumpResponse, build_command, first_float, parse_response


class PumpConnectionError(RuntimeError):
    pass


class PumpTimeoutError(TimeoutError):
    pass


# NE-500 / NE-501 specified maximum pusher speed: 5.100464828 cm/min.
MAX_LINEAR_SPEED_MM_MIN = 51.00464828
VALID_RATE_UNITS = {"UM", "MM", "UH", "MH"}
VALID_VOLUME_UNITS = {"UL", "ML"}
_RATE_ALTERNATE_UNIT = {"MH": "UH", "UH": "MH", "MM": "UM", "UM": "MM"}

# Application-defined Prime presets. These are fractions of the NE-501
# mechanical maximum pusher speed; they are not manufacturer-defined detents.
# A logarithmic-ish spread gives useful control for microfluidic priming while
# keeping every preset at or below the pump's specified maximum speed.
PRIME_SPEED_LEVELS = {
    "MAX": 1.00,
    "HIGH": 0.50,
    "MEDIUM": 0.25,
    "LOW": 0.10,
    "MIN": 0.05,
}


def format_pump_number(value: float, significant_digits: int = 4, *, round_down: bool = False) -> str:
    """Format numeric data for the NE-501 command parser.

    The pump manual specifies at most four numeric digits and at most three
    digits to the right of the decimal point. Scientific notation is not used.
    Positive values that cannot be represented under those constraints raise
    ValueError so the caller can choose a different unit.
    """
    if significant_digits != 4:
        raise ValueError("NE-501 numeric data must use at most four digits")
    if not math.isfinite(value) or value < 0:
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

    text = f"{rounded:.{decimals}f}".rstrip("0").rstrip(".")
    digit_count = sum(ch.isdigit() for ch in text)
    fractional_digits = len(text.split(".", 1)[1]) if "." in text else 0
    if digit_count > 4 or fractional_digits > 3:
        raise ValueError("Value cannot be represented in NE-501 numeric format")
    return text


def maximum_rate_ml_hr(diameter_mm: float) -> float:
    """Theoretical maximum flow from syringe area and specified pusher speed."""
    if not 0.1 <= diameter_mm <= 50.0:
        raise ValueError("Syringe diameter must be between 0.10 and 50.00 mm")
    area_mm2 = math.pi * (diameter_mm / 2.0) ** 2
    return area_mm2 * MAX_LINEAR_SPEED_MM_MIN * 60.0 / 1000.0


def prime_rate_ml_hr(diameter_mm: float, level: str) -> float:
    """Return the software Prime preset rate for a verified syringe diameter.

    The selected level scales the pump's specified maximum linear pusher speed;
    flow is then derived from syringe cross-sectional area.
    """
    key = level.strip().upper()
    try:
        fraction = PRIME_SPEED_LEVELS[key]
    except KeyError as exc:
        raise ValueError(f"Invalid Prime speed level: {level}") from exc
    return maximum_rate_ml_hr(diameter_mm) * fraction


def rate_to_ml_hr(value: float, unit: str) -> float:
    if unit == "MH":
        return value
    if unit == "UH":
        return value / 1000.0
    if unit == "MM":
        return value * 60.0
    if unit == "UM":
        return value * 60.0 / 1000.0
    raise ValueError("Invalid flow-rate unit")


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


def convert_volume(value: float, from_unit: str, to_unit: str) -> float:
    if from_unit not in VALID_VOLUME_UNITS or to_unit not in VALID_VOLUME_UNITS:
        raise ValueError("Invalid volume unit")
    if from_unit == to_unit:
        return value
    if from_unit == "ML" and to_unit == "UL":
        return value * 1000.0
    if from_unit == "UL" and to_unit == "ML":
        return value / 1000.0
    raise ValueError("Unsupported volume conversion")


def _volume_values_for_settings(settings: "ProgramSettings") -> list[tuple[float, str, str]]:
    values: list[tuple[float, str, str]] = []
    if settings.prime_enabled:
        values.append((settings.prime_volume, settings.prime_volume_unit, "Prime volume"))
    if not settings.continuous:
        values.append((settings.volume, settings.volume_unit, "Target volume"))
    return values


def choose_program_volume_unit(settings: "ProgramSettings") -> tuple[str, dict[str, tuple[float, str]]]:
    """Choose one global VOL unit and convert every phase volume into it.

    On NE-500/501, VOL UL / VOL ML changes the *global* volume unit and affects
    every programmed phase, so mixed per-phase volume units are unsafe.
    """
    values = _volume_values_for_settings(settings)
    if not values:
        default_unit = "UL" if settings.diameter_mm <= 14.0 else "ML"
        return default_unit, {}

    preferred: list[str] = []
    if not settings.continuous:
        preferred.append(settings.volume_unit)
    if settings.prime_enabled:
        preferred.append(settings.prime_volume_unit)
    preferred.extend(["UL", "ML"])

    seen: set[str] = set()
    for candidate_unit in preferred:
        if candidate_unit in seen:
            continue
        seen.add(candidate_unit)
        converted: dict[str, tuple[float, str]] = {}
        valid = True
        for value, source_unit, label in values:
            try:
                converted_value = convert_volume(value, source_unit, candidate_unit)
                text = format_pump_number(converted_value)
                converted[label] = (float(text), text)
            except ValueError:
                valid = False
                break
        if valid:
            return candidate_unit, converted

    raise ValueError(
        "Prime/target volumes cannot share one NE-501 volume unit within the pump's numeric limits"
    )


def parse_number_and_unit(text: str, allowed_units: set[str]) -> tuple[Optional[float], Optional[str]]:
    match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*([A-Z]{2})?", text.upper())
    if not match:
        return None, None
    value = float(match.group(1))
    unit = match.group(2)
    if unit not in allowed_units:
        unit = None
    return value, unit


def describe_rejection(command: str, response: PumpResponse) -> str:
    if response.error_code:
        label = response.error_label or response.error_code
        return f'{command} rejected: {label} (?{response.error_code})'
    if response.alarm_code:
        label = response.alarm_label or response.alarm_code
        return f'{command} blocked by alarm: {label} (A?{response.alarm_code})'
    return f"{command} was not accepted by the pump"


@dataclass(frozen=True)
class DiameterConfirmation:
    requested_mm: float
    confirmed_mm: Optional[float]
    set_response: PumpResponse
    query_response: PumpResponse

    @property
    def confirmed(self) -> bool:
        return (
            self.set_response.ok
            and self.query_response.ok
            and self.confirmed_mm is not None
            and abs(self.requested_mm - self.confirmed_mm) <= 0.01
        )


@dataclass(frozen=True)
class ProgramSettings:
    rate: float
    rate_unit: str
    direction: str
    continuous: bool
    volume: float
    volume_unit: str
    prime_enabled: bool
    prime_volume: float
    prime_volume_unit: str
    prime_speed_level: str
    diameter_mm: float


@dataclass(frozen=True)
class ProgramConfirmation:
    commands: list[tuple[int, str, PumpResponse]]
    verified: bool
    message: str
    prime_rate_ml_hr: Optional[float]
    steady_rate_value: Optional[float] = None
    steady_rate_unit: Optional[str] = None
    program_volume_unit: Optional[str] = None


class NE501Controller:
    """Thread-safe Basic-mode controller for one RS-232 pump network."""

    def __init__(self, timeout: float = 1.0, inter_command_delay: float = 0.06) -> None:
        self.timeout = timeout
        self.inter_command_delay = inter_command_delay
        self._serial = None
        self._lock = threading.RLock()
        self._last_command_at = 0.0
        self.port: Optional[str] = None
        self.baudrate = 19200

    @staticmethod
    def available_ports() -> list[tuple[str, str]]:
        try:
            from serial.tools import list_ports
        except ImportError as exc:
            raise PumpConnectionError("pyserial is not installed") from exc
        ports = [(item.device, item.description or "Serial port") for item in list_ports.comports()]
        return sorted(ports, key=lambda value: value[0])

    @property
    def is_connected(self) -> bool:
        return bool(self._serial is not None and self._serial.is_open)

    def connect(self, port: str, baudrate: int = 19200) -> None:
        try:
            import serial
        except ImportError as exc:
            raise PumpConnectionError("pyserial is not installed") from exc
        with self._lock:
            if self.is_connected:
                self.disconnect()
            try:
                self._serial = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.05,
                    write_timeout=1.0,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                )
            except Exception as exc:
                self._serial = None
                raise PumpConnectionError(f"Unable to open {port}: {exc}") from exc
            self.port = port
            self.baudrate = baudrate
            time.sleep(0.12)

    def disconnect(self) -> None:
        with self._lock:
            if self._serial is not None:
                try:
                    if self._serial.is_open:
                        self._serial.close()
                finally:
                    self._serial = None

    def _wait_inter_command_delay(self) -> None:
        remaining = self.inter_command_delay - (time.monotonic() - self._last_command_at)
        if remaining > 0:
            time.sleep(remaining)

    def _read_packet(self) -> bytes:
        if not self.is_connected:
            raise PumpConnectionError("Serial port is not connected")
        deadline = time.monotonic() + self.timeout
        received = bytearray()
        while time.monotonic() < deadline:
            chunk = self._serial.read(1)
            if not chunk:
                continue
            byte = chunk[0]
            if byte == 0x02:
                received.clear()
                received.append(byte)
                continue
            received.append(byte)
            if byte == ETX[0]:
                return bytes(received)
        if received:
            partial_hex = " ".join(f"{byte:02X}" for byte in received)
            raise PumpTimeoutError(
                f"Incomplete pump response (missing ETX): {partial_hex}"
            )
        raise PumpTimeoutError("Pump did not respond before timeout")

    def send_command(self, address: int, command: str) -> PumpResponse:
        with self._lock:
            if not self.is_connected:
                raise PumpConnectionError("Serial port is not connected")
            self._wait_inter_command_delay()
            packet = build_command(address, command)
            try:
                self._serial.reset_input_buffer()
                self._serial.write(packet)
                self._serial.flush()
                raw = self._read_packet()
            except (PumpTimeoutError, PumpConnectionError):
                raise
            except Exception as exc:
                raise PumpConnectionError(f"Serial communication failed: {exc}") from exc
            finally:
                self._last_command_at = time.monotonic()
            expected = None if command.strip().startswith("*") else address
            response = parse_response(raw, expected_address=expected)
            if expected is not None and response.address != expected:
                actual = "unknown" if response.address is None else f"{response.address:02d}"
                raise PumpConnectionError(
                    f"Response address mismatch: expected {expected:02d}, received {actual}"
                )
            return response

    def send_many(self, commands: Iterable[tuple[int, str]]) -> list[tuple[int, str, PumpResponse]]:
        return [(address, command, self.send_command(address, command)) for address, command in commands]

    def scan(self, addresses: Iterable[int]) -> dict[int, PumpResponse]:
        responses: dict[int, PumpResponse] = {}
        for address in addresses:
            try:
                responses[address] = self.send_command(address, "VER")
            except (PumpTimeoutError, PumpConnectionError):
                continue
        return responses

    @staticmethod
    def _stop_result_ok(command: str, response: PumpResponse) -> bool:
        """Treat a stopped-state STP/?NA response as a successful stop context.

        NE-501 firmware can answer STP with ?NA when the program is already
        stopped. The status prompt is still S, so there is nothing left to
        stop. Other ?NA responses remain errors.
        """
        return response.ok or (command == "STP" and response.status == "S" and response.error_code == "NA")

    def status(self, address: int) -> PumpResponse:
        """Query only the pump status prompt (address + CR, no command)."""
        return self.send_command(address, "")

    def _ensure_program_stopped(self, address: int) -> list[tuple[int, str, PumpResponse]]:
        """Leave the Pumping Program fully stopped/reset and editable.

        Query status first. This avoids sending STP to a pump that is already
        stopped, which NE-501 V3.934 may report as ?NA. A running program gets
        one STP (pause); a paused program gets a second STP (reset).
        """
        results: list[tuple[int, str, PumpResponse]] = []
        status_response = self.status(address)
        results.append((address, "STATUS", status_response))
        if status_response.ok and status_response.status == "S":
            return results

        # A valid alarm response acknowledges the alarm. Query once more before
        # deciding whether a stop is still required.
        if status_response.alarm_code is not None:
            status_response = self.status(address)
            results.append((address, "STATUS", status_response))
            if status_response.ok and status_response.status == "S":
                return results

        response = self.send_command(address, "STP")
        results.append((address, "STP", response))
        if not self._stop_result_ok("STP", response):
            return results

        # STP while operating pauses the program. A second STP cancels pause
        # and resets the program so PHN/FUN/VOL/DIR can be changed safely.
        if response.status == "P":
            response2 = self.send_command(address, "STP")
            results.append((address, "STP", response2))
        return results

    def stop_pump(self, address: int) -> list[tuple[int, str, PumpResponse]]:
        """Stop and reset the program without false ?NA on an idle pump."""
        results: list[tuple[int, str, PumpResponse]] = []
        status_response = self.status(address)
        results.append((address, "STATUS", status_response))
        if status_response.ok and status_response.status == "S":
            return results
        response = self.send_command(address, "STP")
        results.append((address, "STP", response))
        if self._stop_result_ok("STP", response) and response.status == "P":
            response2 = self.send_command(address, "STP")
            results.append((address, "STP", response2))
        return results

    def set_diameter(self, address: int, diameter_mm: float) -> DiameterConfirmation:
        if not 0.1 <= diameter_mm <= 50.0:
            raise ValueError("Syringe diameter must be between 0.10 and 50.00 mm")
        stop_results = self._ensure_program_stopped(address)
        for _, command, response in stop_results:
            if command == "STATUS":
                if not response.ok and response.alarm_code is None:
                    raise PumpConnectionError(describe_rejection(command, response))
                continue
            if not self._stop_result_ok(command, response):
                raise PumpConnectionError(describe_rejection(command, response))
        set_response = self.send_command(address, f"DIA {diameter_mm:.2f}")
        query_response = self.send_command(address, "DIA")
        return DiameterConfirmation(
            requested_mm=diameter_mm,
            confirmed_mm=first_float(query_response.data),
            set_response=set_response,
            query_response=query_response,
        )

    def _program_prime_rate(
        self,
        address: int,
        theoretical_ml_hr: float,
        results: list[tuple[int, str, PumpResponse]],
    ) -> tuple[Optional[float], Optional[str]]:
        """Program a requested Prime preset with automatic OOR backoff.

        The caller supplies a target at or below the calculated hardware
        maximum. The value is rounded down to pump precision. If firmware still
        reports ?OOR, back off by 0.5% and retry.
        """
        candidate = theoretical_ml_hr
        last_problem: Optional[str] = None
        for _ in range(12):
            try:
                _, unit, text = normalize_rate(candidate, "MH", round_down=True)
            except ValueError as exc:
                return None, str(exc)
            command = f"RAT {text} {unit}"
            response = self.send_command(address, command)
            results.append((address, command, response))
            if response.ok:
                actual_ml_hr = convert_rate(float(text), unit, "MH")
                return actual_ml_hr, None
            last_problem = describe_rejection(command, response)
            if response.error_code != "OOR":
                return None, last_problem
            candidate *= 0.995
        return None, last_problem or "Prime rate was rejected by the pump"

    def configure_program(self, address: int, settings: ProgramSettings) -> ProgramConfirmation:
        if settings.rate <= 0:
            raise ValueError("Steady flow rate must be greater than zero")
        if settings.rate_unit not in VALID_RATE_UNITS:
            raise ValueError("Invalid steady flow-rate unit")
        if settings.volume_unit not in VALID_VOLUME_UNITS:
            raise ValueError("Invalid target-volume unit")
        if settings.prime_volume_unit not in VALID_VOLUME_UNITS:
            raise ValueError("Invalid prime-volume unit")
        if settings.direction not in {"INF", "WDR"}:
            raise ValueError("Invalid pumping direction")
        if settings.prime_enabled and settings.prime_volume <= 0:
            raise ValueError("Prime volume must be greater than zero")
        if settings.prime_enabled and settings.prime_speed_level.upper() not in PRIME_SPEED_LEVELS:
            raise ValueError("Invalid Prime speed level")
        if not settings.continuous and settings.volume <= 0:
            raise ValueError("Target volume must be greater than zero")
        if not 0.1 <= settings.diameter_mm <= 50.0:
            raise ValueError("Syringe diameter must be between 0.10 and 50.00 mm")

        steady_rate_value, steady_rate_unit, steady_rate_text = normalize_rate(
            settings.rate, settings.rate_unit
        )
        program_volume_unit, volumes = choose_program_volume_unit(settings)
        prime_volume_value, prime_volume_text = volumes.get("Prime volume", (0.0, "0"))
        steady_volume_value, steady_volume_text = volumes.get("Target volume", (0.0, "0"))

        theoretical_prime_rate = (
            prime_rate_ml_hr(settings.diameter_mm, settings.prime_speed_level)
            if settings.prime_enabled else None
        )
        if theoretical_prime_rate is not None:
            steady_ml_hr = rate_to_ml_hr(steady_rate_value, steady_rate_unit)
            if theoretical_prime_rate <= steady_ml_hr:
                raise ValueError(
                    "Selected Prime speed is not above the steady-flow rate. "
                    "Choose a higher Prime speed level or lower the steady-flow rate."
                )
        results = self._ensure_program_stopped(address)
        failed_stop = next(
            (item for item in results if not (
                item[2].ok
                or (item[1] == "STP" and self._stop_result_ok(item[1], item[2]))
                or (item[1] == "STATUS" and item[2].alarm_code is not None)
            )),
            None,
        )
        if failed_stop is not None:
            _, command, response = failed_stop
            return ProgramConfirmation(
                results, False, describe_rejection(command, response), None,
                steady_rate_value, steady_rate_unit, program_volume_unit,
            )

        prime_rate_actual: Optional[float] = None

        def send_checked(command: str) -> Optional[str]:
            response = self.send_command(address, command)
            results.append((address, command, response))
            if not response.ok:
                return describe_rejection(command, response)
            return None

        if settings.prime_enabled:
            # Select a Rate phase before setting VOL units. Firmware documents
            # VOL as applicable to Rate Data Functions, while the unit itself is
            # global for the whole program.
            for command in ["PHN 1", "FUN RAT", f"VOL {program_volume_unit}"]:
                problem = send_checked(command)
                if problem:
                    return ProgramConfirmation(
                        results, False, problem, None,
                        steady_rate_value, steady_rate_unit, program_volume_unit,
                    )
            assert theoretical_prime_rate is not None
            prime_rate_actual, problem = self._program_prime_rate(address, theoretical_prime_rate, results)
            if problem:
                return ProgramConfirmation(
                    results, False, problem, prime_rate_actual,
                    steady_rate_value, steady_rate_unit, program_volume_unit,
                )
            for command in [
                f"VOL {prime_volume_text}",
                f"DIR {settings.direction}",
                "PHN 2", "FUN RAT",
                f"RAT {steady_rate_text} {steady_rate_unit}",
                "VOL 0" if settings.continuous else f"VOL {steady_volume_text}",
                f"DIR {settings.direction}",
            ]:
                problem = send_checked(command)
                if problem:
                    return ProgramConfirmation(
                        results, False, problem, prime_rate_actual,
                        steady_rate_value, steady_rate_unit, program_volume_unit,
                    )
            if not settings.continuous:
                for command in ["PHN 3", "FUN STP"]:
                    problem = send_checked(command)
                    if problem:
                        return ProgramConfirmation(
                            results, False, problem, prime_rate_actual,
                            steady_rate_value, steady_rate_unit, program_volume_unit,
                        )
        else:
            for command in [
                "PHN 1", "FUN RAT", f"VOL {program_volume_unit}",
                f"RAT {steady_rate_text} {steady_rate_unit}",
                "VOL 0" if settings.continuous else f"VOL {steady_volume_text}",
                f"DIR {settings.direction}",
            ]:
                problem = send_checked(command)
                if problem:
                    return ProgramConfirmation(
                        results, False, problem, None,
                        steady_rate_value, steady_rate_unit, program_volume_unit,
                    )
            if not settings.continuous:
                for command in ["PHN 2", "FUN STP"]:
                    problem = send_checked(command)
                    if problem:
                        return ProgramConfirmation(
                            results, False, problem, None,
                            steady_rate_value, steady_rate_unit, program_volume_unit,
                        )

        verification_commands: list[str] = []
        if settings.prime_enabled:
            verification_commands += ["PHN 1", "FUN", "RAT", "VOL", "DIR"]
            verification_commands += ["PHN 2", "FUN", "RAT", "VOL", "DIR"]
            if not settings.continuous:
                verification_commands += ["PHN 3", "FUN"]
        else:
            verification_commands += ["PHN 1", "FUN", "RAT", "VOL", "DIR"]
            if not settings.continuous:
                verification_commands += ["PHN 2", "FUN"]

        verify_results = self.send_many((address, command) for command in verification_commands)
        results.extend(verify_results)
        for _, command, response in verify_results:
            if not response.ok:
                return ProgramConfirmation(
                    results, False, describe_rejection(command, response), prime_rate_actual,
                    steady_rate_value, steady_rate_unit, program_volume_unit,
                )

        by_phase: dict[int, dict[str, PumpResponse]] = {}
        current_phase: Optional[int] = None
        for _, command, response in verify_results:
            if command.startswith("PHN "):
                current_phase = int(command.split()[1])
                by_phase.setdefault(current_phase, {})["PHN"] = response
            elif current_phase is not None:
                by_phase.setdefault(current_phase, {})[command] = response

        def rate_matches(response: PumpResponse, expected_value: float, expected_unit: str) -> bool:
            value, unit = parse_number_and_unit(response.data, VALID_RATE_UNITS)
            return (
                value is not None and unit == expected_unit
                and math.isclose(value, expected_value, rel_tol=0.001, abs_tol=0.001)
            )

        def volume_matches(response: PumpResponse, expected_value: float) -> bool:
            value, unit = parse_number_and_unit(response.data, VALID_VOLUME_UNITS)
            return (
                value is not None and unit == program_volume_unit
                and math.isclose(value, expected_value, rel_tol=0.001, abs_tol=0.001)
            )

        steady_phase = 2 if settings.prime_enabled else 1
        steady = by_phase.get(steady_phase, {})
        checks: list[tuple[str, bool]] = [
            ("steady FUN", steady.get("FUN") is not None and "RAT" in steady["FUN"].data.upper()),
            ("steady RAT", steady.get("RAT") is not None and rate_matches(steady["RAT"], steady_rate_value, steady_rate_unit)),
            ("steady VOL", steady.get("VOL") is not None and volume_matches(steady["VOL"], 0.0 if settings.continuous else steady_volume_value)),
            ("steady DIR", steady.get("DIR") is not None and settings.direction in steady["DIR"].data.upper()),
        ]

        if settings.prime_enabled:
            prime = by_phase.get(1, {})
            # Prime rate is programmed in an equivalent mL/hr or µL/hr form.
            prime_rate_response = prime.get("RAT")
            prime_rate_ok = False
            if prime_rate_response is not None and prime_rate_actual is not None:
                value, unit = parse_number_and_unit(prime_rate_response.data, VALID_RATE_UNITS)
                if value is not None and unit in {"MH", "UH"}:
                    actual_ml_hr = convert_rate(value, unit, "MH")
                    prime_rate_ok = math.isclose(actual_ml_hr, prime_rate_actual, rel_tol=0.001, abs_tol=0.001)
            checks += [
                ("prime FUN", prime.get("FUN") is not None and "RAT" in prime["FUN"].data.upper()),
                ("prime RAT", prime_rate_ok),
                ("prime VOL", prime.get("VOL") is not None and volume_matches(prime["VOL"], prime_volume_value)),
                ("prime DIR", prime.get("DIR") is not None and settings.direction in prime["DIR"].data.upper()),
            ]

        stop_phase = 3 if settings.prime_enabled else 2
        if not settings.continuous:
            stop = by_phase.get(stop_phase, {})
            checks.append(("stop FUN", stop.get("FUN") is not None and "STP" in stop["FUN"].data.upper()))

        failed_checks = [name for name, passed in checks if not passed]
        verified = not failed_checks
        message = "Program verified" if verified else (
            "Program read-back mismatch: " + ", ".join(failed_checks)
        )
        return ProgramConfirmation(
            results, verified, message, prime_rate_actual,
            steady_rate_value, steady_rate_unit, program_volume_unit,
        )

    def stop_all(self, addresses: Iterable[int]) -> list[tuple[int, str, PumpResponse]]:
        results: list[tuple[int, str, PumpResponse]] = []
        for address in addresses:
            results.extend(self.stop_pump(address))
        return results
