"""Experiment preparation and explicit write/read-back coordination.

Planning and user confirmation never open a connection or start a motor.
Device acknowledgements are kept by the current connection, not the plan file.
"""
from dataclasses import dataclass, replace
from typing import Callable

from .syringe import format_diameter


@dataclass(frozen=True)
class PumpPlan:
    used: bool = False
    diameter: float | None = None
    fluid: str = ''
    inlet: str = ''

    def validate(self):
        if type(self.used) is not bool:
            raise ValueError('Pump selection must be true or false.')
        if self.diameter is not None:
            format_diameter(self.diameter)
        for text in (self.fluid, self.inlet):
            if not isinstance(text, str) or len(text) > 64 or any(ord(c) < 32 for c in text):
                raise ValueError('Use at most 64 characters for a fluid or inlet name.')


class PreparationState:
    def __init__(self, addresses):
        self.plans = {a: PumpPlan() for a in addresses}
        self.tubing = {a: 'pending' for a in addresses}
        self.mapping_confirmed = False
        self.preparation_amounts = {}

    def update(self, address, **changes):
        old = self.plans[address]
        new = replace(old, **changes)
        new.validate()
        if new != old:
            self.plans[address] = new
            self.tubing[address] = 'pending'
            if (new.used, new.fluid, new.inlet) != (old.used, old.fluid, old.inlet):
                self.mapping_confirmed = False
            self.preparation_amounts.pop(address, None)
        return new

    def confirm_tubing(self, address, choice):
        if choice not in ('pending', 'needed', 'done', 'skipped'):
            raise ValueError('Invalid tubing preparation choice.')
        self.tubing[address] = choice

    def reset_session(self):
        self.mapping_confirmed = False
        self.tubing = dict.fromkeys(self.plans, 'pending')
        self.preparation_amounts.clear()

    def used_addresses(self):
        return [a for a, plan in self.plans.items() if plan.used]

    def physical_blocker(self, address):
        if not self.plans[address].used:
            return 'Select this pump for this experiment.'
        if self.plans[address].diameter is None:
            return 'Enter the syringe inside diameter.'
        if not self.mapping_confirmed:
            return 'Confirm the pump-to-inlet mapping.'
        if self.tubing[address] not in ('done', 'skipped'):
            return 'Confirm tubing preparation or explicitly skip it.'
        return ''


@dataclass
class WriteResult:
    diameter: object | None = None
    program: object | None = None
    cancelled: bool = False

    @property
    def verified(self):
        return bool(not self.cancelled and self.diameter and self.diameter.confirmed
                    and self.program and self.program.verified)

    @property
    def message(self):
        if self.cancelled:
            return 'Not sent after STOP request'
        if self.diameter is None or not self.diameter.confirmed:
            return 'The diameter read back from the pump does not match the entered value.'
        return self.program.message if self.program is not None else 'Device verification failed.'


def write_verified_program(controller, address, settings, current: Callable[[], bool] = lambda: True):
    """Write DIA, verify it, then write/verify the program; never send RUN."""
    result = WriteResult()
    if not current():
        result.cancelled = True
        return result
    result.diameter = controller.set_diameter(address, settings.diameter_mm)
    if not result.diameter.confirmed:
        return result
    if not current():
        result.cancelled = True
        return result
    result.program = controller.configure_program(address, settings)
    return result
