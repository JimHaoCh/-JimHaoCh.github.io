"""Virtual, fixed-header timeline viewport. This widget has no hardware access."""
from __future__ import annotations

from dataclasses import replace
import math

from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget

from ne501.timeline_model import Clip, Timeline, format_time

from .i18n import manager, tr
from .i18n_widgets import Painter as QPainter, Menu as QMenu

COLORS = ('#4387e8', '#2ca77e', '#c88838', '#936cc9')


class TimelineCanvas(QWidget):
    selection_changed = Signal(str)
    model_changed = Signal(object)
    seeked = Signal(float)
    add_requested = Signal(int, int)
    track_selected = Signal(int)
    notice = Signal(str)
    view_changed = Signal()
    zoom_requested = Signal(float, float)
    command = Signal(str)

    LEFT, TOP, ROW, RIGHT = 112, 39, 68, 14
    HEIGHT = TOP + 4 * ROW + 10

    def __init__(self, model: Timeline, parent=None):
        super().__init__(parent)
        self.model = model
        self.selected = model.clips[0].id if model.clips else None
        self.active_track = 0
        self.playhead = 0.0
        self.active_ids: set[str] = set()
        self.editable = True
        self.seek_enabled = True
        self.snapping = True
        self.view_start = 0
        self.visible_ticks = model.total
        self.drag: dict | None = None
        self.snap_tick: int | None = None
        self._last_pointer = None
        self._pan_timer = QTimer(self)
        self._pan_timer.setInterval(35)
        self._pan_timer.timeout.connect(self._edge_pan)
        self.setMinimumSize(350, 230)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(tr('四幫浦時間軌'))
        manager.changed.connect(self._language_changed)
        self.setToolTip('拖曳移動；左右邊界調整長度；Ctrl＋滾輪縮放。')

    def setToolTip(self,text):
        self._tooltip_source=str(text)
        super().setToolTip(tr(text))

    def _language_changed(self):
        self.setAccessibleName(tr('四幫浦時間軌'))
        super().setToolTip(tr(getattr(self,'_tooltip_source','')))
        self.update()

    def row_height(self):
        return (self.height() - self.TOP - 8) / 4

    def track_width(self):
        return max(1.0, float(self.width() - self.LEFT - self.RIGHT))

    def tick_to_x(self, tick):
        return self.LEFT + (tick - self.view_start) * self.track_width() / self.visible_ticks

    def x_to_tick(self, x):
        return max(0, min(self.model.total, round(self.view_start + (x - self.LEFT) * self.visible_ticks / self.track_width())))

    def clip_rect(self, clip):
        return QRectF(self.tick_to_x(clip.start), self.TOP + clip.pump * self.row_height() + 9,
                      max(2.0, self.tick_to_x(clip.end) - self.tick_to_x(clip.start)),
                      min(52.0, self.row_height() - 17))

    def set_view(self, span, start=None):
        self.visible_ticks = max(min(5, self.model.total), min(self.model.total, round(span)))
        self.view_start = max(0, min(self.model.total - self.visible_ticks,
                                     self.view_start if start is None else round(start)))
        self.view_changed.emit()
        self.update()

    def set_zoom(self, value):
        self.set_view(self.model.total / max(1, value))

    def reveal(self, tick):
        margin = self.visible_ticks * .08
        if tick < self.view_start + margin:
            self.set_view(self.visible_ticks, tick - margin)
        elif tick > self.view_start + self.visible_ticks - margin:
            self.set_view(self.visible_ticks, tick - self.visible_ticks + margin)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#20252c'))
        row = self.row_height()
        for pump in range(4):
            y = self.TOP + pump * row
            if pump == self.active_track:
                p.fillRect(QRectF(0, y, self.width(), row), QColor('#26313e'))
            p.setPen(QColor('#3a4450'))
            p.drawLine(0, round(y), self.width(), round(y))
        p.save()
        p.setClipRect(QRectF(self.LEFT, 0, self.track_width() + 1, self.height()))
        desired = max(1, self.visible_ticks * 76 / self.track_width())
        spacing = 10 ** math.floor(math.log10(desired))
        spacing = next(m * spacing for m in (1, 2, 5, 10) if m * spacing >= desired)
        p.setFont(QFont(self.font().family(),9))
        end_reserved = self.tick_to_x(self.model.total)-p.fontMetrics().horizontalAdvance(format_time(self.model.total))-6 if self.view_start+self.visible_ticks==self.model.total else float('inf')
        tick = math.ceil(self.view_start / spacing) * spacing
        while tick <= self.view_start + self.visible_ticks:
            x = self.tick_to_x(tick)
            p.setPen(QColor('#3c4552'))
            p.drawLine(round(x), self.TOP, round(x), self.height())
            p.setPen(QColor('#b6c2d2'))
            if x+3+p.fontMetrics().horizontalAdvance(format_time(tick)) < end_reserved-3:
                p.drawText(QRectF(x + 3, 10, 105, 22), Qt.AlignmentFlag.AlignLeft, format_time(tick))
            tick += spacing
        if self.view_start + self.visible_ticks == self.model.total:
            end_x = self.tick_to_x(self.model.total)
            end_width=p.fontMetrics().horizontalAdvance(format_time(self.model.total))+6
            p.fillRect(QRectF(end_x-end_width,6,end_width,26),QColor('#20252c'))
            p.setPen(QColor('#b6c2d2'))
            p.drawText(QRectF(end_x-end_width,10,end_width-3,22),Qt.AlignmentFlag.AlignRight,format_time(self.model.total))
        clips = list(self.model.clips)
        if self.drag and self.drag.get('candidate'):
            candidate = self.drag['candidate']
            clips = [candidate if c.id == candidate.id else c for c in clips]
        for clip in clips:
            if clip.end < self.view_start or clip.start > self.view_start + self.visible_ticks:
                continue
            r = self.clip_rect(clip)
            selected = clip.id == self.selected
            invalid = self.drag and self.drag.get('candidate') == clip and not self.drag.get('valid', True)
            color = QColor('#ab3f48' if invalid else COLORS[clip.pump])
            if not self.model.used[clip.pump]:
                color = QColor('#37414f')
            p.setPen(QPen(QColor('white' if selected else '#b4c5d4'), 2 if selected else .7))
            p.setBrush(color)
            p.drawRoundedRect(r, 4, 4)
            if clip.direction == 'WDR' and r.width() > 8:
                p.save()
                p.setClipRect(r, Qt.ClipOperation.IntersectClip)
                p.setPen(QPen(QColor(255, 255, 255, 38), 3))
                x = max(r.left() - r.height(), self.LEFT - r.height())
                while x < min(r.right(), self.width()):
                    p.drawLine(round(x), round(r.bottom()), round(x + r.height()), round(r.top()))
                    x += 15
                p.restore()
            if r.width() > 40:
                p.save()
                p.setClipRect(r.adjusted(7, 0, -7, 0), Qt.ClipOperation.IntersectClip)
                text_x = max(r.left() + 9, self.LEFT + 9)
                p.setPen(QColor('white'))
                f = QFont(self.font()); f.setPointSize(9); f.setBold(True); p.setFont(f)
                direction = '→ 推注' if clip.direction == 'INF' else '← 抽取'
                available=max(0,round(min(r.right(),self.width()-self.RIGHT)-text_x-3))
                title=tr(f'{direction}  {clip.rate:g} {clip.unit}')
                if not self.model.used[clip.pump]:
                    title = tr('Not included') + ' · ' + title
                if p.fontMetrics().horizontalAdvance(title)>available:title=f'{"→" if clip.direction=="INF" else "←"} {clip.rate:g} {clip.unit}'
                title=p.fontMetrics().elidedText(title,Qt.TextElideMode.ElideRight,available)
                p.drawText(QRectF(text_x,r.top()+3,available,22),Qt.AlignmentFlag.AlignLeft,title)
                if r.height() > 40:
                    f.setPointSize(8); f.setBold(False); p.setFont(f)
                    p.drawText(QRectF(text_x, r.top() + 26, r.right() - text_x - 3, 20),
                               Qt.AlignmentFlag.AlignLeft, f'{format_time(clip.start)} – {format_time(clip.end)}')
                p.restore()
            if selected and r.width() >= 24:
                p.setPen(QPen(QColor('white'), 2))
                for x in (r.left() + 4, r.right() - 4):
                    p.drawLine(round(x), round(r.center().y() - 7), round(x), round(r.center().y() + 7))
            if clip.id in self.active_ids:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor('#a4ffca'), 2))
                p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 5, 5)
        if self.snap_tick is not None:
            p.setPen(QPen(QColor('#83e8fa'), 1, Qt.PenStyle.DashLine))
            x = round(self.tick_to_x(self.snap_tick))
            p.drawLine(x, self.TOP, x, self.height())
        x = round(self.tick_to_x(self.playhead))
        p.setPen(QPen(QColor('#ffd166'), 2))
        p.drawLine(x, self.TOP - 7, x, self.height())
        p.restore()
        p.fillRect(QRectF(0, 0, self.LEFT, self.TOP), QColor('#20252c'))
        p.setPen(QColor('#adb9c9')); header_font=QFont(self.font());header_font.setPointSize(9);p.setFont(header_font)
        p.drawText(QRectF(8,7,self.LEFT-16,28),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,'幫浦 / 位址')
        p.save()
        p.setClipRect(QRectF(0, self.TOP, self.LEFT - 3, self.height()-self.TOP))
        for pump in range(4):
            y = self.TOP + pump * row
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(COLORS[pump] if self.model.used[pump] else '#758093'))
            p.drawEllipse(QRectF(10, y + 19, 8, 8))
            p.setPen(QColor('#eff3f8'))
            f = QFont(self.font()); f.setBold(True)
            if row < 50: f.setPointSizeF(9.5)
            p.setFont(f)
            name = f'P{pump + 1} ' + self.model.names[pump]
            name = QFontMetrics(f).elidedText(name, Qt.TextElideMode.ElideRight, self.LEFT - 32)
            p.drawText(26, round(y + (28 if row >= 50 else 21)), name)
            f.setBold(False)
            if row < 50: f.setPointSizeF(8.5)
            p.setFont(f); p.setPen(QColor('#a5b3c4'))
            path = f'{self.model.addresses[pump]:02d}'
            if self.model.inlets[pump]:
                path += ' · ' + self.model.inlets[pump]
            if not self.model.used[pump]:
                path = f'{self.model.addresses[pump]:02d} · ' + tr('Not included')
            path = QFontMetrics(f).elidedText(path, Qt.TextElideMode.ElideRight, self.LEFT - 32)
            p.drawText(26, round(y + (48 if row >= 50 else 39)), path)
            if row >= 66:
                diameter=self.model.diameters[pump]
                f.setPointSizeF(8);p.setFont(f)
                p.drawText(26, round(y+65), 'Not included' if not self.model.used[pump] else f'ID {diameter:g} mm' if diameter is not None else 'ID —')
        p.restore()
        p.end()

    def _hit(self, x, y):
        if x < self.LEFT:
            return None
        hits = [c for c in self.model.clips if self.clip_rect(c).adjusted(-3, 0, 3, 0).contains(x, y)]
        return min(hits, key=lambda c: (not self.clip_rect(c).contains(x, y),
                                       abs(self.tick_to_x((c.start+c.end)/2)-x), c.id != self.selected), default=None)

    def _part(self, clip, x):
        r = self.clip_rect(clip)
        if r.width() < 24:
            return 'move' if abs(x - r.center().x()) <= 3 else ('left' if x < r.center().x() else 'right')
        edge = min(8, r.width() / 4)
        return 'left' if x <= r.left() + edge else 'right' if x >= r.right() - edge else 'move'

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        x, y = event.position().x(), event.position().y()
        pump = int((y - self.TOP) // self.row_height())
        if 0 <= pump < 4:
            self.active_track = pump
            self.track_selected.emit(pump)
        if self.seek_enabled and x >= self.LEFT and (y < self.TOP or not self.editable):
            self.playhead = self.x_to_tick(x); self.seeked.emit(self.playhead)
            self.drag = {'kind': 'seek'}; self.update(); return
        if not self.editable:
            return
        clip = self._hit(x, y)
        if clip:
            self.selected = clip.id; self.selection_changed.emit(clip.id)
            self.drag = {'kind': self._part(clip, x), 'original': clip, 'candidate': clip,
                         'grab_tick': self.x_to_tick(x), 'press_x': x, 'press_y': y,
                         'valid': True, 'moved': False}
        elif self.seek_enabled and x >= self.LEFT:
            self.playhead = self.x_to_tick(x); self.seeked.emit(self.playhead)
            self.drag = {'kind': 'seek'}
        self.update()

    def _snap(self, candidate, kind, disabled):
        self.snap_tick = None
        if not self.snapping or disabled:
            return candidate
        targets = {0, self.model.total, round(self.playhead)}
        targets.update(t for c in self.model.clips if c.id != candidate.id for t in (c.start, c.end))
        edges = [candidate.start] if kind == 'left' else [candidate.end] if kind == 'right' else [candidate.start, candidate.end]
        delta, target = min(((t - e, t) for t in targets for e in edges), key=lambda pair: abs(pair[0]))
        tolerance = min(10, 8 * self.visible_ticks / self.track_width())
        if abs(delta) > tolerance:
            return candidate
        self.snap_tick = target
        if kind == 'left': return replace(candidate, start=candidate.start + delta)
        if kind == 'right': return replace(candidate, end=candidate.end + delta)
        return replace(candidate, start=candidate.start + delta, end=candidate.end + delta)

    def _drag_to(self, x, y, alt=False):
        if not self.drag or self.drag['kind'] == 'seek': return
        original = self.drag['original']; kind = self.drag['kind']
        if not self.drag['moved'] and abs(x - self.drag['press_x']) + abs(y - self.drag['press_y']) < 3:
            return
        self.drag['moved'] = True
        delta = self.x_to_tick(x) - self.drag['grab_tick']
        if kind == 'left':
            candidate = replace(original, start=max(0, min(original.end - 1, original.start + delta)))
        elif kind == 'right':
            candidate = replace(original, end=min(self.model.total, max(original.start + 1, original.end + delta)))
        else:
            pump = max(0, min(3, int((y - self.TOP) // self.row_height())))
            start = max(0, min(self.model.total - (original.end - original.start), original.start + delta))
            candidate = replace(original, pump=pump, start=start, end=start + original.end - original.start)
        candidate = self._snap(candidate, kind, alt)
        # Adjacent blocks form a hard boundary when editing on the same track.
        if candidate.pump == original.pump:
            previous = max((c.end for c in self.model.clips if c.pump == original.pump and c.id != original.id and c.end <= original.start), default=0)
            following = min((c.start for c in self.model.clips if c.pump == original.pump and c.id != original.id and c.start >= original.end), default=self.model.total)
            if kind == 'left': candidate = replace(candidate, start=max(previous, min(original.end - 1, candidate.start)))
            elif kind == 'right': candidate = replace(candidate, end=min(following, max(original.start + 1, candidate.end)))
            else:
                duration = original.end-original.start
                others = sorted((c for c in self.model.clips if c.pump == original.pump and c.id != original.id), key=lambda c: c.start)
                gaps = list(zip([0]+[c.end for c in others], [c.start for c in others]+[self.model.total]))
                positions = [max(a, min(b-duration, candidate.start)) for a,b in gaps if b-a >= duration]
                start = min(positions, key=lambda value: abs(value-candidate.start))
                candidate = replace(candidate, start=start, end=start+duration)
        valid = True
        try:
            Timeline(self.model.total, [candidate if c.id == original.id else c for c in self.model.clips], self.model.addresses)
        except ValueError:
            valid = False
        if self.snap_tick not in (candidate.start, candidate.end): self.snap_tick = None
        self.drag.update(candidate=candidate, valid=valid)
        text = f'幫浦 {candidate.pump + 1}  {format_time(candidate.start)} → {format_time(candidate.end)}  ·  {(candidate.end-candidate.start)/10:g} 秒'
        self.notice.emit(text if valid else text + '  ·  此位置與區塊衝突；放開將取消。')
        self.update()

    def mouseMoveEvent(self, event):
        x, y = event.position().x(), event.position().y()
        if self.drag:
            if self.drag['kind'] == 'seek':
                if self.seek_enabled:
                    self.playhead = self.x_to_tick(x); self.seeked.emit(self.playhead); self.update()
                return
            alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            self._last_pointer = (x, y, alt)
            self._drag_to(x, y, alt)
            if x < self.LEFT + 18 or x > self.width() - self.RIGHT - 18: self._pan_timer.start()
            else: self._pan_timer.stop()
            return
        clip = self._hit(x, y)
        if clip:
            part = self._part(clip, x)
            self.setCursor(Qt.CursorShape.SizeHorCursor if self.editable and part != 'move' else Qt.CursorShape.OpenHandCursor if self.editable else Qt.CursorShape.ArrowCursor)
            self.setToolTip(f'幫浦 {clip.pump+1} · {format_time(clip.start)} – {format_time(clip.end)}\n{clip.rate:g} {clip.unit} · {(clip.end-clip.start)/10:g} 秒\n拖曳移動；邊界調整長度；F 放大選取區塊。')
        else:
            self.setCursor(Qt.CursorShape.CrossCursor if x >= self.LEFT and self.seek_enabled else Qt.CursorShape.ArrowCursor)
            self.setToolTip('雙擊空白處新增；Ctrl＋滾輪縮放；左右鍵移動游標 0.1 秒。')

    def _edge_pan(self):
        if not self.drag or self.drag['kind'] == 'seek' or self._last_pointer is None:
            self._pan_timer.stop(); return
        x, y, alt = self._last_pointer
        direction = -1 if x < self.LEFT + 18 else 1 if x > self.width() - self.RIGHT - 18 else 0
        if direction:
            self.set_view(self.visible_ticks, self.view_start + direction * max(1, round(self.visible_ticks / 25)))
            self._drag_to(x, y, alt)

    def cancel_drag(self):
        self._pan_timer.stop(); self.drag = None; self.snap_tick = None; self.update()

    def mouseReleaseEvent(self, event):
        if not self.drag or event.button() != Qt.MouseButton.LeftButton: return
        drag = self.drag
        self.cancel_drag()
        if drag['kind'] == 'seek' or not drag['moved']: return
        candidate = drag['candidate']
        if drag['valid'] and candidate != drag['original']:
            old = self.model.copy(); self.model.replace(candidate)
            self.active_track = candidate.pump
            self.model_changed.emit(old); self.selection_changed.emit(candidate.id)
        elif not drag['valid']:
            self.notice.emit('已取消衝突的拖曳；原區塊保持原位。')

    def mouseDoubleClickEvent(self, event):
        if not self.editable or event.button() != Qt.MouseButton.LeftButton: return
        self.cancel_drag()
        x, y = event.position().x(), event.position().y()
        pump = int((y - self.TOP) // self.row_height())
        clip = self._hit(x, y)
        if clip:
            self.selected = clip.id; self.selection_changed.emit(clip.id); self.command.emit('inspect')
        elif x >= self.LEFT and 0 <= pump < 4:
            self.add_requested.emit(pump, self.x_to_tick(x))

    def wheelEvent(self, event):
        steps = event.angleDelta().y() or event.angleDelta().x()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if steps: self.zoom_requested.emit(2 if steps > 0 else .5, event.position().x())
        else:
            self.set_view(self.visible_ticks, self.view_start - (steps / 120) * max(1, self.visible_ticks / 8))
        event.accept()

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Escape and self.drag:
            self.cancel_drag(); self.notice.emit('已取消拖曳。'); return
        shortcuts = {Qt.Key.Key_Space: 'toggle', Qt.Key.Key_Delete: 'delete', Qt.Key.Key_F: 'focus',
                     Qt.Key.Key_Home: 'home', Qt.Key.Key_End: 'end', Qt.Key.Key_Escape: 'cancel'}
        if ctrl:
            action = {Qt.Key.Key_Z: 'redo' if shift else 'undo', Qt.Key.Key_Y: 'redo',
                      Qt.Key.Key_D: 'copy', Qt.Key.Key_B: 'split', Qt.Key.Key_Plus: 'zoom_in',
                      Qt.Key.Key_Equal: 'zoom_in', Qt.Key.Key_Minus: 'zoom_out'}.get(key)
        else:
            action = shortcuts.get(key)
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            amount = (10 if shift else 1) * (-1 if key == Qt.Key.Key_Left else 1)
            if ctrl: self.command.emit(f'nudge:{amount}')
            elif self.seek_enabled: self.seeked.emit(max(0, min(self.model.total, round(self.playhead) + amount)))
            return
        if action: self.command.emit(action); event.accept()
        else: super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        clip = self._hit(event.pos().x(), event.pos().y())
        if not self.editable or not clip: return
        self.selected = clip.id; self.selection_changed.emit(clip.id)
        menu = QMenu(self)
        for label, command in [('區塊設定', 'inspect'), ('放大選取區塊  F', 'focus'),
                               ('複製  Ctrl+D', 'copy'), ('在游標分割  Ctrl+B', 'split'), ('刪除  Delete', 'delete')]:
            action = menu.addAction(label)
            action.setEnabled(command != 'split' or clip.start < self.playhead < clip.end)
            action.triggered.connect(lambda _checked=False, cmd=command: self.command.emit(cmd))
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(event.globalPos())
