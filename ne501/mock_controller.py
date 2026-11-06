from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Iterable, Optional

from .controller import (
    NE501Controller,
    DiameterConfirmation, ProgramConfirmation, ProgramSettings,
    PumpConnectionError, choose_program_volume_unit, convert_rate,
    format_pump_number, maximum_rate_ml_hr, normalize_rate, prime_rate_ml_hr,
)
from .syringe import format_diameter
from .protocol import PumpResponse, first_float, parse_response


@dataclass
class MockPhase:
    function: str = "RAT"
    rate: float = 1.0
    rate_unit: str = "MH"
    direction: str = "INF"
    volume: float = 0.0


@dataclass
class MockPumpState:
    diameter: float = 10.00
    status: str = "S"
    version: str = "NE501-MOCK-2.1"
    current_phase: int = 1
    volume_unit: str = "UL"
    phases: dict[int, MockPhase] = field(default_factory=lambda: {1: MockPhase()})


class MockNE501Controller(NE501Controller):
    def __init__(self, addresses: Iterable[int] = range(4), latency: float = 0.04) -> None:
        self.pumps = {address: MockPumpState() for address in addresses}
        self.latency = latency
        self.port: Optional[str] = None
        self.baudrate = 19200
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, port: str = "MOCK", baudrate: int = 19200) -> None:
        self.port, self.baudrate, self._connected = port, baudrate, True

    def disconnect(self) -> None:
        self._connected = False

    def _response(self, address: int, status: str, data: str = "") -> PumpResponse:
        raw = b"\x02" + f"{address:02d}{status}{data}".encode("ascii") + b"\x03"
        return parse_response(raw, expected_address=address)

    def send_command(self, address: int, command: str) -> PumpResponse:
        if not self._connected:
            raise PumpConnectionError("Mock serial port is not connected")
        time.sleep(self.latency)
        if address not in self.pumps:
            raise PumpConnectionError(f"Mock pump {address:02d} does not exist")
        state = self.pumps[address]
        command = command.strip().upper()
        if not command:
            return self._response(address, state.status)
        parts = command.split()
        keyword, args = parts[0], parts[1:]
        phase = state.phases.setdefault(state.current_phase, MockPhase())

        if keyword == "VER":
            return self._response(address, state.status, state.version)
        if keyword == "DIA":
            if args:
                if state.status in {"I", "W", "X"}:
                    return self._response(address, state.status, "?NA")
                value = first_float(args[0])
                if value is None or not 0.1 <= value <= 50.0:
                    return self._response(address, state.status, "?OOR")
                state.diameter = value
                state.volume_unit = "UL" if value <= 14.0 else "ML"
            return self._response(address, state.status, format_diameter(state.diameter))
        if keyword == "PHN":
            if args:
                if state.status in {"I", "W", "X"}:
                    return self._response(address, state.status, "?NA")
                state.current_phase = int(args[0])
                phase = state.phases.setdefault(state.current_phase, MockPhase())
            return self._response(address, state.status, f"{state.current_phase:02d}")
        if keyword == "FUN":
            if args:
                if state.status in {"I", "W", "X"}:
                    return self._response(address, state.status, "?NA")
                phase.function = args[0]
            return self._response(address, state.status, phase.function)
        if keyword == "RAT":
            if args:
                value = first_float(args[0])
                if value is None or value <= 0:
                    return self._response(address, state.status, "?OOR")
                unit = args[1] if len(args) >= 2 else phase.rate_unit
                rate_ml_hr = value
                if unit == "UH":
                    rate_ml_hr = value / 1000.0
                elif unit == "MM":
                    rate_ml_hr = value * 60.0
                elif unit == "UM":
                    rate_ml_hr = value * 60.0 / 1000.0
                if rate_ml_hr > maximum_rate_ml_hr(state.diameter) * 1.00001:
                    return self._response(address, state.status, "?OOR")
                phase.rate = value
                phase.rate_unit = unit
            return self._response(address, state.status, f"{format_pump_number(phase.rate)}{phase.rate_unit}")
        if keyword == "DIR":
            if args:
                if args[0] not in {"INF", "WDR"}:
                    return self._response(address, state.status, "?OOR")
                phase.direction = args[0]
            return self._response(address, state.status, phase.direction)
        if keyword == "VOL":
            if args:
                if state.status in {"I", "W", "X"}:
                    return self._response(address, state.status, "?NA")
                if args[0] in {"UL", "ML"}:
                    state.volume_unit = args[0]
                else:
                    value = first_float(args[0])
                    if value is None or value < 0:
                        return self._response(address, state.status, "?OOR")
                    phase.volume = value
            return self._response(address, state.status, f"{format_pump_number(phase.volume)}{state.volume_unit}")
        if keyword == "RUN":
            state.current_phase = int(args[0]) if args else 1
            phase = state.phases.setdefault(state.current_phase, MockPhase())
            state.status = "I" if phase.direction == "INF" else "W"
            return self._response(address, state.status)
        if keyword == "STP":
            if state.status == "S":
                return self._response(address, "S", "?NA")
            if state.status in {"I", "W", "X", "T", "U"}:
                state.status = "P"
                return self._response(address, state.status)
            if state.status == "P":
                state.status = "S"
                return self._response(address, state.status)
            state.status = "S"
            return self._response(address, state.status)
        return self._response(address, state.status, "?COM")

    def send_many(self, commands):
        return [(address, command, self.send_command(address, command)) for address, command in commands]

    def scan(self, addresses: Iterable[int]) -> dict[int, PumpResponse]:
        return {address: self.send_command(address, "VER") for address in addresses if address in self.pumps}

    def set_diameter(self, address: int, diameter_mm: float) -> DiameterConfirmation:
        return NE501Controller.set_diameter(self, address, diameter_mm)

    def configure_program(self, address: int, settings: ProgramSettings) -> ProgramConfirmation:
        # Use the exact production validation and read-back path with simulated I/O.
        return NE501Controller.configure_program(self, address, settings)

    def stop_pump(self, address: int):
        status = self.send_command(address, "")
        results = [(address, "STATUS", status)]
        if status.status == "S" and status.ok:
            return results
        first = self.send_command(address, "STP")
        results.append((address, "STP", first))
        if first.status == "P" and first.ok:
            results.append((address, "STP", self.send_command(address, "STP")))
        return results

    def stop_all(self, addresses: Iterable[int]):
        results = []
        for address in addresses:
            results.extend(self.stop_pump(address))
        return results
