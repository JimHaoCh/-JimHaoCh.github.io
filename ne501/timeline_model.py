"""Editable timeline data for the simulation-only protocol editor.

Times are integer tenths of a second.  This module never connects to pumps.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from typing import Any
from uuid import uuid4

TICKS_PER_SECOND = 10
MAX_DURATION_TICKS = 7 * 24 * 60 * 60 * TICKS_PER_SECOND
UNITS = ('µL/min', 'mL/min', 'µL/hr', 'mL/hr')
DIRECTIONS = ('INF', 'WDR')
FORMAT = 'ne501-timeline-preview'


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f'{name} must be an integer')
    return value


def tick_from_seconds(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Time must be a finite number')
    tick = round(value * TICKS_PER_SECOND)
    if abs(value * TICKS_PER_SECOND - tick) > 1e-7:
        raise ValueError('Time must be in 0.1-second increments')
    return tick


def format_time(ticks: int) -> str:
    ticks = max(0, int(ticks))
    seconds, tenth = divmod(ticks, TICKS_PER_SECOND)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{tenth}' if hours else f'{minutes:02d}:{seconds:02d}.{tenth}'


@dataclass(frozen=True)
class Clip:
    id: str
    pump: int
    start: int
    end: int
    direction: str
    rate: float
    unit: str

    @property
    def volume_ul(self) -> float:
        scale = {'µL/min': 1 / 60, 'mL/min': 1000 / 60,
                 'µL/hr': 1 / 3600, 'mL/hr': 1000 / 3600}[self.unit]
        return self.rate * ((self.end - self.start) / TICKS_PER_SECOND) * scale


class Timeline:
    """Four channels mapped to logical pump indices 0-3."""

    def __init__(self, total: int = 1200, clips: list[Clip] | None = None, addresses: list[int] | None = None):
        self.total = total
        self.clips = list(clips or [])
        self.addresses = list(addresses if addresses is not None else [0, 1, 2, 3])
        self.validate()

    def validate(self) -> None:
        _integer(self.total, 'Total duration')
        if not TICKS_PER_SECOND <= self.total <= MAX_DURATION_TICKS:
            raise ValueError('總長度須介於 1 秒與 7 天之間。')
        if len(self.addresses) != 4 or any(isinstance(a, bool) or not isinstance(a, int) or not 0 <= a <= 99 for a in self.addresses) or len(set(self.addresses)) != 4:
            raise ValueError('四台幫浦的位址必須介於 00–99，且不可重複。')
        if len(self.clips) > 800:
            raise ValueError('流程區塊超過上限。')
        ids: set[str] = set()
        for clip in self.clips:
            if not isinstance(clip, Clip) or not isinstance(clip.id, str) or not clip.id or len(clip.id) > 100 or clip.id in ids:
                raise ValueError('區塊識別資料不正確。')
            ids.add(clip.id)
            _integer(clip.pump, 'Pump index')
            _integer(clip.start, 'Start')
            _integer(clip.end, 'End')
            if not 0 <= clip.pump < 4 or not 0 <= clip.start < clip.end <= self.total:
                raise ValueError('區塊時間或幫浦軌道超出範圍。')
            if clip.direction not in DIRECTIONS or clip.unit not in UNITS:
                raise ValueError('區塊方向或流速單位不正確。')
            if isinstance(clip.rate, bool) or not isinstance(clip.rate, (int, float)) or not math.isfinite(clip.rate) or not 0.0001 <= clip.rate <= 9999 or abs(clip.rate * 10000 - round(clip.rate * 10000)) > 1e-7:
                raise ValueError('流速須介於 0.0001–9999，最多四位小數。')
        for pump in range(4):
            clips = sorted((c for c in self.clips if c.pump == pump), key=lambda c: c.start)
            if len(clips) > 200:
                raise ValueError(f'幫浦 {pump + 1} 的區塊超過上限。')
            for a, b in zip(clips, clips[1:]):
                if b.start < a.end:
                    raise ValueError(f'幫浦 {pump + 1} 的時間區塊不可重疊。')

    def copy(self) -> Timeline:
        return Timeline(self.total, self.clips.copy(), self.addresses)

    def get(self, clip_id: str | None) -> Clip | None:
        return next((c for c in self.clips if c.id == clip_id), None)

    def replace(self, clip: Clip) -> None:
        if self.get(clip.id) is None:
            raise ValueError('找不到選取區塊。')
        candidate = [clip if c.id == clip.id else c for c in self.clips]
        Timeline(self.total, candidate, self.addresses)
        self.clips = candidate

    def add(self, clip: Clip) -> None:
        candidate = self.clips + [clip]
        Timeline(self.total, candidate, self.addresses)
        self.clips = candidate

    def delete(self, clip_id: str) -> None:
        if self.get(clip_id) is None:
            raise ValueError('找不到選取區塊。')
        self.clips = [c for c in self.clips if c.id != clip_id]

    def set_total(self, total: int) -> None:
        Timeline(total, self.clips, self.addresses)
        self.total = total

    def split(self, clip_id: str, tick: int) -> Clip:
        """Split a block atomically, preserving rate, direction and total volume."""
        _integer(tick, 'Split time')
        clip = self.get(clip_id)
        if clip is None or not clip.start < tick < clip.end:
            raise ValueError('分割位置必須位於區塊內部。')
        left = replace(clip, end=tick)
        right = replace(clip, id=uuid4().hex, start=tick)
        candidate = [left if c.id == clip.id else c for c in self.clips] + [right]
        Timeline(self.total, candidate, self.addresses)
        self.clips = candidate
        return right

    def make_clip(self, pump: int, requested_start: int = 0, duration: int = 150,
                  direction: str = 'INF', rate: float = 10, unit: str = 'µL/min') -> Clip:
        """Find a gap, keeping the requested duration. Never silently truncate."""
        _integer(pump, 'Pump index')
        _integer(requested_start, 'Requested start')
        _integer(duration, 'Duration')
        if not 0 <= pump < 4 or duration < 1:
            raise ValueError('幫浦軌道或持續時間不正確。')
        cursor = max(0, requested_start)
        for existing in sorted((c for c in self.clips if c.pump == pump), key=lambda c: c.start):
            if existing.end <= cursor:
                continue
            if existing.start - cursor >= duration:
                break
            cursor = existing.end
        if cursor + duration > self.total:
            raise ValueError('這條軌道沒有足夠的空白時間。')
        return Clip(uuid4().hex, pump, cursor, cursor + duration, direction, rate, unit)

    def active(self, ticks: float) -> list[Clip]:
        return [c for c in self.clips if c.start <= ticks < c.end]

    def to_json(self) -> str:
        self.validate()
        data = {'format': FORMAT, 'version': 1, 'duration': self.total / 10,
                'tracks': [{'id': p + 1, 'address': f'{self.addresses[p]:02d}',
                            'blocks': [{'id': c.id, 'start': c.start / 10, 'end': c.end / 10,
                                        'direction': c.direction, 'rate': c.rate, 'unit': c.unit}
                                       for c in sorted(self.clips, key=lambda c: c.start) if c.pump == p]}
                           for p in range(4)]}
        return json.dumps(data, ensure_ascii=False, indent=2) + '\n'

    @classmethod
    def from_json(cls, text: str) -> Timeline:
        if len(text.encode('utf-8')) > 1_048_576:
            raise ValueError('流程檔超過 1 MB。')
        try:
            d = json.loads(text)
            if not isinstance(d, dict) or d.get('format') != FORMAT or type(d.get('version')) is not int or d.get('version') != 1:
                raise ValueError('流程檔格式不正確。')
            total = tick_from_seconds(d['duration'])
            tracks = d['tracks']
            if not isinstance(tracks, list) or len(tracks) != 4:
                raise ValueError('流程檔必須包含四條幫浦軌道。')
            clips: list[Clip] = []
            addresses: list[int] = []
            for p, t in enumerate(tracks):
                if not isinstance(t, dict) or type(t.get('id')) is not int or t.get('id') != p + 1 or not isinstance(t.get('address'), str) or len(t['address']) != 2 or not t['address'].isascii() or not t['address'].isdigit() or not isinstance(t.get('blocks'), list):
                    raise ValueError('幫浦軌道資料不正確。')
                addresses.append(int(t['address']))
                if len(t['blocks']) > 200:
                    raise ValueError('單一幫浦的區塊超過 200 個。')
                for b in t['blocks']:
                    if not isinstance(b, dict):
                        raise ValueError('區塊資料必須為物件。')
                    clips.append(Clip(b['id'], p, tick_from_seconds(b['start']), tick_from_seconds(b['end']),
                                      b['direction'], b['rate'], b['unit']))
            return cls(total, clips, addresses)
        except (KeyError, TypeError, json.JSONDecodeError, UnicodeError, RecursionError) as exc:
            raise ValueError('無法讀取流程檔，請確認格式。') from exc


def example_timeline(addresses: list[int] | None = None) -> Timeline:
    return Timeline(1200, [Clip('a', 0, 0, 300, 'INF', 10, 'µL/min'),
                           Clip('b', 0, 550, 800, 'WDR', 5, 'µL/min'),
                           Clip('c', 1, 100, 750, 'INF', 6, 'µL/min'),
                           Clip('d', 2, 200, 450, 'INF', 4, 'µL/min'),
                           Clip('e', 2, 650, 1200, 'INF', 8, 'µL/min'),
                           Clip('f', 3, 850, 1200, 'WDR', 2, 'µL/min')], addresses)
