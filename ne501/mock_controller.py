from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Iterable, Optional

from .controller import (
    NE501Controller,
    DiameterConfirmation, ProgramConfirmation, ProgramSettings,
    PumpConnectionError, choose_program_volume_unit, convert_rate,
    format_pump_number, maximum_rate_ml_hr, normalize_rate, prime_rate_ml_hr,
    rate_to_ml_hr,
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
    jump_to: int | None = None


@dataclass
class MockPumpState:
    diameter: float = 10.00
    status: str = "S"
    version: str = "NE501-MOCK-2.1"
    current_phase: int = 1
    volume_unit: str = "UL"
    phases: dict[int, MockPhase] = field(default_factory=lambda: {1: MockPhase()})
    phase_ml: float = 0.0
    last_tick: float | None = None
    infused_ml: float = 0.0
    withdrawn_ml: float = 0.0


class MockNE501Controller(NE501Controller):
    def __init__(self, addresses: Iterable[int] = range(4), latency: float = 0.04, clock=None) -> None:
        super().__init__(inter_command_delay=0)
        self.pumps = {address: MockPumpState() for address in addresses}
        self.latency = latency
        self.port: Optional[str] = None
        self.baudrate = 19200
        self._connected = False
        self.clock = clock or time.monotonic

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

    def _advance(self, state):
        if state.status not in ('I', 'W') or state.last_tick is None:
            return
        remaining = max(0., self.clock() - state.last_tick)
        state.last_tick = self.clock()
        for _ in range(64):
            phase = state.phases.setdefault(state.current_phase, MockPhase())
            if phase.function == 'STP':
                state.status = 'S'; state.last_tick = None; return
            if phase.function == 'JMP':
                state.current_phase = phase.jump_to or 1; state.phase_ml = 0.; continue
            rate = rate_to_ml_hr(phase.rate, phase.rate_unit) / 3600
            target = phase.volume * (1 if state.volume_unit == 'ML' else .001)
            needed = max(0., target-state.phase_ml) / rate if target else float('inf')
            elapsed = min(remaining, needed)
            amount = elapsed * rate
            state.phase_ml += amount
            if phase.direction == 'INF': state.infused_ml += amount
            else: state.withdrawn_ml += amount
            state.status = 'I' if phase.direction == 'INF' else 'W'
            remaining -= elapsed
            if not target or needed > elapsed + 1e-9:
                return
            state.current_phase += 1; state.phase_ml = 0.
        state.status = 'S'; state.last_tick = None

    def send_command(self, address: int, command: str) -> PumpResponse:
        self.check_command_current()
        if not self._connected:
            raise PumpConnectionError("Mock serial port is not connected")
        time.sleep(self.latency)
        self.check_command_current()
        if address not in self.pumps:
            raise PumpConnectionError(f"Mock pump {address:02d} does not exist")
        state = self.pumps[address]
        self._advance(state)
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
                phase.jump_to = int(args[1]) if args[0] == 'JMP' and len(args)>1 else None
            function = phase.function + (f'{phase.jump_to:02d}' if phase.jump_to is not None else '')
            return self._response(address, state.status, function)
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
            resume = not args and state.status == 'P'
            if not resume:
                state.current_phase = int(args[0]) if args else 1
                state.phase_ml = 0.
            phase = state.phases.setdefault(state.current_phase, MockPhase())
            state.status = "I" if phase.direction == "INF" else "W"
            state.last_tick = self.clock()
            self._advance(state)
            return self._response(address, state.status)
        if keyword == "STP":
            if state.status == "S":
                return self._response(address, "S", "?NA")
            if state.status in {"I", "W", "X", "T", "U"}:
                state.status = "P"
                state.last_tick = None
                return self._response(address, state.status)
            if state.status == "P":
                state.status = "S"
                state.last_tick = None; state.phase_ml = 0.; state.current_phase = 1
                return self._response(address, state.status)
            state.status = "S"
            return self._response(address, state.status)
        if keyword == 'DIS':
            scale = 1 if state.volume_unit == 'ML' else 1000
            return self._response(address, state.status, f'I{state.infused_ml*scale:.6g}W{state.withdrawn_ml*scale:.6g}{state.volume_unit}')
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
