"""Stop each configured pump and report only directly confirmed states."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .protocol import PumpResponse


@dataclass
class StopAllReport:
    results: list[tuple[int, str, PumpResponse]] = field(default_factory=list)
    confirmed: list[int] = field(default_factory=list)
    unconfirmed: dict[int, str] = field(default_factory=dict)


def stop_all_independently(controller: Any, addresses: Iterable[int]) -> StopAllReport:
    """Try each address even if an earlier pump times out or rejects STOP.

    This remains a serial software command, not an independent safety circuit.
    A stopped status must be present in the final valid response for that pump.
    """
    report = StopAllReport()
    for address in addresses:
        try:
            results = controller.stop_pump(address)
            report.results.extend(results)
            if not results:
                report.unconfirmed[address] = "No response"
                continue
            result_address, command, response = results[-1]
            valid_stop = response.ok or (
                command == "STP" and response.status == "S" and response.error_code == "NA"
            )
            if result_address == address and response.address == address and response.status == "S" and valid_stop:
                report.confirmed.append(address)
            else:
                detail = response.error_label or response.alarm_label or response.status_label
                report.unconfirmed[address] = f"Final response: {detail}"
        except Exception as exc:
            report.unconfirmed[address] = str(exc) or type(exc).__name__
    return report
