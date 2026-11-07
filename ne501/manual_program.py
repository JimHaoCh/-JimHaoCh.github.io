"""One verified manual program with independent formal and priming entry points.

Phase 1: formal delivery; phase 2: end.
Phase 3: finite priming; phase 4: end or jump to formal delivery.
RUN 1 never executes priming. Native paused phase 1 resumes with bare RUN.
"""
from dataclasses import dataclass, replace
import math
import re

from .controller import (ProgramSettings, choose_program_volume_unit,
                         CommandCancelled, convert_volume, prime_rate_ml_hr, rate_to_ml_hr)
from .pump_numbers import normalize_rate, format_pump_number


@dataclass(frozen=True)
class PrimingSettings:
    rate: float
    rate_unit: str
    volume: float
    volume_unit: str
    direction: str
    follow_delivery: bool = False
    preset: str | None = None

    def validate(self):
        if self.rate <= 0 or not math.isfinite(self.rate):
            raise ValueError('Enter a positive priming rate.')
        normalize_rate(self.rate, self.rate_unit)
        if self.volume <= 0 or not math.isfinite(self.volume) or self.volume_unit not in ('UL', 'ML'):
            raise ValueError('Enter a positive priming volume.')
        if self.direction not in ('INF', 'WDR'):
            raise ValueError('Select a priming direction.')


@dataclass(frozen=True)
class ManualProof:
    formal: object
    priming: PrimingSettings | None
    program: ProgramSettings


def write_manual_program(controller, address, formal, priming=None):
    """Verify formal delivery and optional priming without issuing RUN."""
    formal = replace(formal, prime_enabled=False)
    if priming is not None:priming.validate()
    combined = replace(formal, prime_enabled=True, prime_volume=priming.volume,
                       prime_volume_unit=priming.volume_unit) if priming else formal
    volume_unit, _ = choose_program_volume_unit(combined)
    base = replace(formal, volume_unit=volume_unit,
                   volume=convert_volume(formal.volume, formal.volume_unit, volume_unit))
    result = controller.configure_program(address, base)
    if not result.verified:
        return result
    results = list(result.commands)

    def send(command):
        response = controller.send_command(address, command)
        results.append((address, command, response))
        if not response.ok:
            raise ValueError(f'{command}: {response.data or response.error_label}')
        return response

    try:
        from .controller import parse_number_and_unit
        # Continuous base programs choose the diameter's default volume unit.
        # Establish the shared unit explicitly before either entry point is armed.
        send('PHN 1');send(f'VOL {volume_unit}')
        formal_text='0' if formal.continuous else format_pump_number(base.volume)
        send(f'VOL {formal_text}')
        value,unit=parse_number_and_unit(send('VOL').data,{'UL','ML'})
        if unit!=volume_unit or value is None or not math.isclose(value,float(formal_text),abs_tol=1e-9):
            raise ValueError('Formal volume read-back does not match.')
        send('PHN 2');send('FUN STP')
        if send('FUN').data.strip()!='STP':raise ValueError('Formal end-phase read-back does not match.')
        if priming is None:
            send('PHN 1')
            return replace(result,commands=results,program_volume_unit=volume_unit)
        actual_rate, actual_unit, rate_text = normalize_rate(priming.rate, priming.rate_unit)
        prime_volume = convert_volume(priming.volume, priming.volume_unit, volume_unit)
        volume_text = format_pump_number(prime_volume)
        send('PHN 3'); send('FUN RAT')
        if priming.preset:
            actual_ml_hr, problem = controller._program_prime_rate(
                address, prime_rate_ml_hr(formal.diameter_mm, priming.preset), results)
            if problem:
                raise ValueError(problem)
            actual_rate, actual_unit, _ = normalize_rate(actual_ml_hr, 'MH')
        else:
            send(f'RAT {rate_text} {actual_unit}')
        send(f'VOL {volume_text}')
        send(f'DIR {priming.direction}')
        send('PHN 4')
        send('FUN JMP 1' if priming.follow_delivery else 'FUN STP')
        send('PHN 3')
        function, rate, volume, direction = (send(c) for c in ('FUN', 'RAT', 'VOL', 'DIR'))
        rv, ru = parse_number_and_unit(rate.data, {'UM','MM','UH','MH'})
        vv, vu = parse_number_and_unit(volume.data, {'UL','ML'})
        if (function.data.strip() != 'RAT' or ru != actual_unit or rv is None
                or not math.isclose(rv, actual_rate, abs_tol=1e-9)
                or vu != volume_unit or vv is None
                or not math.isclose(vv, float(volume_text), abs_tol=1e-9)
                or direction.data.strip() != priming.direction):
            raise ValueError('Priming read-back does not match the requested program.')
        send('PHN 4')
        end = re.sub(r'\s+', '', send('FUN').data.upper())
        if (priming.follow_delivery and not re.fullmatch(r'JMP0*1', end)) or (not priming.follow_delivery and end != 'STP'):
            raise ValueError('Priming end-phase read-back does not match.')
        send('PHN 1')
    except ValueError as exc:
        return replace(result, commands=results, verified=False, message=str(exc))
    return replace(result, commands=results, program_volume_unit=volume_unit,
                   prime_rate_ml_hr=rate_to_ml_hr(actual_rate, actual_unit))


def hold_motor(controller, address, *, reset=False):
    """Confirm motor stationary while preserving native paused progress."""
    if reset:
        results = controller.stop_pump(address)
        if not results:return results, None
        _, command, status = results[-1]
        valid = status.ok or command=='STP' and status.error_code=='NA'
        return results, status if valid and status.status=='S' else None
    results=[]
    try:
        status=controller.send_command(address,'')
        results.append((address,'STATUS',status))
    except CommandCancelled:raise
    except Exception:
        status=None
    # Even a failed status query or an alarm must leave a STOP attempt.
    if status is None or not status.ok or status.status not in ('P', 'S'):
        status = controller.send_command(address, 'STP')
        results.append((address, 'STP', status))
    return results, status if status.ok and status.status in ('P', 'S') else None
