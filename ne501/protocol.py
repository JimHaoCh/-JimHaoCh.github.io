from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

STX = b"\x02"
ETX = b"\x03"
CR = b"\r"

STATUS_LABELS = {
    "I": "Infusing",
    "W": "Withdrawing",
    "S": "Stopped",
    "P": "Paused",
    "T": "Pause phase",
    "U": "Waiting for trigger",
    "X": "Purging",
    "A": "Alarm",
}

# A live program can restart its motor after a timer or an external trigger.
# P is different: STP has paused the program and retained its progress.
ACTIVE_PROGRAM_STATUSES = frozenset({'I', 'W', 'X', 'T', 'U'})

ALARM_LABELS = {
    "R": "Pump reset / power interrupted",
    "S": "Motor stalled",
    "T": "Safe-mode communication timeout",
    "E": "Pumping program error",
    "O": "Program phase out of range",
}

ERROR_LABELS = {
    "MALFORMED": "Malformed pump response",
    "NA": "Command not applicable",
    "OOR": "Value out of range",
    "COM": "Invalid command",
    "IGN": "Command ignored",
}


@dataclass(frozen=True)
class PumpResponse:
    address: Optional[int]
    status: Optional[str]
    data: str
    raw: bytes
    error_code: Optional[str] = None
    alarm_code: Optional[str] = None

    @property
    def ok(self) -> bool:
        return (self.status in STATUS_LABELS and self.status != 'A'
                and self.error_code is None and self.alarm_code is None)

    @property
    def status_label(self) -> str:
        if self.status is None:
            return "Unknown"
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def error_label(self) -> str:
        if self.error_code is None:
            return ""
        return ERROR_LABELS.get(self.error_code, self.error_code)

    @property
    def alarm_label(self) -> str:
        if self.alarm_code is None:
            return ""
        return ALARM_LABELS.get(self.alarm_code, self.alarm_code)

    @property
    def raw_hex(self) -> str:
        return " ".join(f"{byte:02X}" for byte in self.raw)


def build_command(address: int, command: str) -> bytes:
    """Build one Basic-mode command packet.

    Normal commands use a two-digit pump address. System commands beginning
    with '*' override the network address and are sent without a prefix.
    """
    if isinstance(address, bool) or not isinstance(address, int) or not 0 <= address <= 99:
        raise ValueError("Pump address must be between 0 and 99")
    if not isinstance(command, str) or any(not 32 <= ord(char) <= 126 for char in command):
        raise ValueError("Pump commands must contain one line of printable ASCII")
    command = command.strip().upper()
    # The NE-500/501 manual defines an addressed packet with no command as a
    # status-only query. It is useful before STP so an already-stopped pump is
    # not sent a command that firmware may reject with ?NA.
    if not command:
        return f"{address:02d}".encode("ascii") + CR
    if command.startswith("*"):
        return command.encode("ascii") + CR
    return f"{address:02d}{command}".encode("ascii") + CR


def _extract_payload(raw: bytes) -> bytes:
    if not raw:
        return b""
    start = raw.find(STX)
    if start >= 0:
        end = raw.find(ETX, start + 1)
        if end >= 0:
            return raw[start + 1 : end]
        return raw[start + 1 :]
    return raw.strip(b"\r\n\x00")


def parse_response(raw: bytes, expected_address: Optional[int] = None) -> PumpResponse:
    payload = _extract_payload(raw)
    text = payload.decode("ascii", errors="replace").strip()

    address: Optional[int] = None
    remainder = text
    if remainder.startswith('*'):
        remainder = remainder[1:]

    if expected_address is not None:
        # Prefer the normal two-digit network address. Some firmware/tools may
        # expose a one-digit address, but accept that form only when the next
        # character is a status prompt. This prevents an expected address 0 from
        # accidentally accepting a response from address 01 (and similarly for
        # other one-digit addresses).
        two_digit = f"{expected_address:02d}"
        if remainder.startswith(two_digit):
            address = expected_address
            remainder = remainder[len(two_digit) :]
        else:
            one_digit = str(expected_address)
            next_index = len(one_digit)
            if (
                remainder.startswith(one_digit)
                and len(remainder) > next_index
                and remainder[next_index] in STATUS_LABELS
            ):
                address = expected_address
                remainder = remainder[next_index:]

    if address is None:
        match = re.match(r"^(\d{1,2})", remainder)
        if match:
            address = int(match.group(1))
            remainder = remainder[match.end() :]

    status: Optional[str] = None
    if remainder and remainder[0] in STATUS_LABELS:
        status = remainder[0]
        remainder = remainder[1:]

    data = remainder.strip()
    error_code: Optional[str] = None
    alarm_code: Optional[str] = None

    if status == "A":
        alarm_code = data[1] if data.startswith("?") and len(data) == 2 else "UNKNOWN"
    elif data.startswith("?"):
        error_code = data[1:].strip() or "UNKNOWN"

    # Keep decoded fields for diagnostics, but only a complete Basic-mode frame
    # with a known status may acknowledge a command. '*' is a system address.
    if re.fullmatch(rb'\x02(?:[0-9]{1,2}|\*)[IWSPTUXA][\x20-\x7e]*\x03', raw) is None:
        error_code = "MALFORMED"

    return PumpResponse(
        address=address,
        status=status,
        data=data,
        raw=raw,
        error_code=error_code,
        alarm_code=alarm_code,
    )


def first_float(text: str) -> Optional[float]:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None
