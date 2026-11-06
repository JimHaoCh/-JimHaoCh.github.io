"""Four-track desktop timeline. Simulation only; no access to pump controllers."""
from __future__ import annotations

from dataclasses import replace
import math
import time
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QTimer, Signal, QSignalBlocker
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ne501.timeline_model import Clip, Timeline, UNITS, example_timeline, format_time

COLORS = ('#4387e8', '#2ca77e', '#c88838', '#936cc9')


class TimelineCanvas(QWidget):
    """Paint and interact with time blocks; all changes remain in memory."""
    selection_changed = Signal(str)
    model_changed = Signal(object)  # old model for undo
    seeked = Signal(float)
    add_requested = Signal(int, int)
    notice = Signal(str)

    LEFT = 150
    TOP = 48
    ROW = 85
    RIGHT = 20
    HEIGHT = TOP + 4 * ROW + 10

    def __init__(self, model: Timeline, parent: QWidget | None = None):
        super().__init__(parent)
        self.model = model
        self.selected: str | None = model.clips[0].id if model.clips else None
        self.playhead = 0.0
        self.active_ids: set[str] = set()
        self.editable = True
        self.drag: dict | None = None
        self.setMinimumSize(920, self.HEIGHT)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip('拖曳區塊以移動；拖曳左右邊界可調整時間。雙擊軌道空白處新增區塊。')

    def set_zoom(self, value: float) -> None:
        self.setMinimumWidth(round(920 * value))
        self.updateGeometry()
        self.update()

    def track_width(self) -> float:
        return max(1.0, float(self.width() - self.LEFT - self.RIGHT))

    def tick_to_x(self, tick: float) -> float:
        return self.LEFT + self.track_width() * tick / self.model.total

    def x_to_tick(self, x: float) -> int:
        return max(0, min(self.model.total, round((x - self.LEFT) * self.model.total / self.track_width())))

    def clip_rect(self, clip: Clip) -> QRectF:
        x = self.tick_to_x(clip.start)
        w = max(2.0, self.tick_to_x(clip.end) - x)
        return QRectF(x, self.TOP + clip.pump * self.ROW + 15, w, 52)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#20252c'))
        painter.setPen(QColor('#9aa4b2'))
        painter.drawText(12, 29, '幫浦 / 位址')
        desired = max(1.0, self.model.total * 90.0 / self.track_width())
        candidates = (1, 2, 5, 10, 20, 50, 100, 150, 300, 600, 1200, 3000, 6000, 18000, 36000, 72000, 144000, 288000, 864000)
        spacing = next((x for x in candidates if x >= desired), candidates[-1])
        tick = 0
        while tick <= self.model.total:
            x = self.tick_to_x(tick)
            painter.setPen(QColor('#39424e'))
            painter.drawLine(round(x), self.TOP - 3, round(x), self.HEIGHT - 3)
            painter.setPen(QColor('#aab7c7'))
            painter.drawText(QRectF(x + 2, 17, 90, 20), Qt.AlignmentFlag.AlignLeft, format_time(tick))
            tick += spacing
        for pump in range(4):
            y = self.TOP + pump * self.ROW
            painter.setPen(QColor('#35404c'))
            painter.drawLine(0, y, self.width(), y)
            painter.setBrush(QColor(COLORS[pump]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(14, y + 25, 10, 10)
            painter.setPen(QColor('#eff3f8'))
            painter.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
            painter.drawText(32, y + 34, f'幫浦 {pump + 1}')
            painter.setFont(QFont('Segoe UI', 9))
            painter.setPen(QColor('#a4b0bf'))
            painter.drawText(32, y + 55, f'位址 {self.model.addresses[pump]:02d} · 模擬')
        for clip in self.model.clips:
            rect = self.clip_rect(clip)
            painter.setPen(QPen(QColor('#ffffff'), 2) if clip.id == self.selected else QPen(QColor('#bdc9d8'), 0.7))
            painter.setBrush(QColor(COLORS[clip.pump]))
            painter.drawRoundedRect(rect, 5, 5)
            if clip.direction == 'WDR':
                painter.save()
                painter.setClipRect(rect)
                painter.setPen(QPen(QColor(255, 255, 255, 35), 4))
                x = rect.left() - rect.height()
                while x < rect.right():
                    painter.drawLine(round(x), round(rect.bottom()), round(x + rect.height()), round(rect.top()))
                    x += 16
                painter.restore()
            painter.save()
            painter.setClipRect(rect.adjusted(7, 0, -7, 0))
            painter.setPen(QColor('white'))
            painter.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
            direction = '→ 推注' if clip.direction == 'INF' else '← 抽取'
            painter.drawText(rect.adjusted(10, 5, -5, -23), Qt.AlignmentFlag.AlignLeft, f'{direction}  {clip.rate:g} {clip.unit}')
            painter.setFont(QFont('Segoe UI', 8))
            painter.drawText(rect.adjusted(10, 27, -5, -3), Qt.AlignmentFlag.AlignLeft, f'{format_time(clip.start)} – {format_time(clip.end)}')
            painter.restore()
            if clip.id in self.active_ids:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor('#9effbf'), 2))
                painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 6, 6)
        x = self.tick_to_x(self.playhead)
        painter.setPen(QPen(QColor('#ffd166'), 2))
        painter.drawLine(round(x), self.TOP - 5, round(x), self.HEIGHT - 5)
        painter.end()

    def _hit(self, x: float, y: float) -> Clip | None:
        return next((c for c in reversed(self.model.clips) if self.clip_rect(c).contains(x, y)), None)

    def mousePressEvent(self, event) -> None:
        if not self.editable or event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        if y < self.TOP and x >= self.LEFT:
            self.playhead = float(self.x_to_tick(x))
            self.seeked.emit(self.playhead)
            self.drag = {'kind': 'seek'}
            self.update()
            return
        clip = self._hit(x, y)
        if clip:
            self.selected = clip.id
            self.selection_changed.emit(clip.id)
            rect = self.clip_rect(clip)
            edge = 'left' if abs(x - rect.left()) <= 8 else 'right' if abs(x - rect.right()) <= 8 else 'move'
            self.drag = {'id': clip.id, 'x': x, 'kind': edge, 'original': clip, 'before': self.model.copy()}
        elif x >= self.LEFT:
            self.playhead = float(self.x_to_tick(x))
            self.seeked.emit(self.playhead)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if not self.editable or self.drag is None:
            return
        if self.drag['kind'] == 'seek':
            self.playhead = float(self.x_to_tick(event.position().x()))
            self.seeked.emit(self.playhead)
            self.update()
            return
        original: Clip = self.drag['original']
        delta = round((event.position().x() - self.drag['x']) * self.model.total / self.track_width())
        kind = self.drag['kind']
        if kind == 'left':
            candidate = replace(original, start=max(0, min(original.end - 1, original.start + delta)))
        elif kind == 'right':
            candidate = replace(original, end=min(self.model.total, max(original.start + 1, original.end + delta)))
        else:
            start = max(0, min(self.model.total - (original.end - original.start), original.start + delta))
            candidate = replace(original, start=start, end=start + original.end - original.start)
        try:
            self.model.replace(candidate)
        except ValueError:
            self.notice.emit('同一台幫浦的區塊不可重疊。')
            return
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self.drag is None or event.button() != Qt.MouseButton.LeftButton:
            return
        if self.drag['kind'] == 'seek':
            self.drag = None
            return
        before: Timeline = self.drag['before']
        changed = self.model.get(self.drag['id']) != self.drag['original']
        self.drag = None
        if changed:
            self.model_changed.emit(before)
            self.selection_changed.emit(self.selected or '')
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        if not self.editable or event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        pump = int((y - self.TOP) // self.ROW)
        if x >= self.LEFT and 0 <= pump < 4 and self._hit(x, y) is None:
            self.add_requested.emit(pump, self.x_to_tick(x))


class TimelineEditor(QWidget):
    """Interactive UI preview: can never send commands to physical devices."""
    def __init__(self, addresses: list[int] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.model = example_timeline(addresses)
        self.config_addresses = tuple(self.model.addresses)
        self.history: list[Timeline] = []
        self.checked = False
        self.dirty = False
        self.duration_dirty = False
        self.running = False
        self.paused = False
        self.loading = False
        self.playhead = 0.0
        self.zoom = 1.0
        self.started_at = 0.0
        self.started_tick = 0.0
        self.canvas = TimelineCanvas(self.model)
        self.canvas.selection_changed.connect(self.select_clip)
        self.canvas.model_changed.connect(self.record_drag)
        self.canvas.seeked.connect(self.seek)
        self.canvas.add_requested.connect(self.add_clip_at)
        self.canvas.notice.connect(self.show_notice)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.advance)
        self._build_ui()
        self.select_clip(self.canvas.selected or '')
        self.update_controls()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        banner = QLabel('模擬預覽  •  時間軌目前不會連接或控制幫浦；0.1 秒同步需實機測試。')
        banner.setObjectName('workflowBanner')
        banner.setWordWrap(True)
        root.addWidget(banner)
        header = QHBoxLayout()
        title = QLabel('四幫浦流程編輯')
        title.setStyleSheet('font-size: 18pt; font-weight: 700;')
        header.addWidget(title)
        header.addStretch()
        self.open_button = QPushButton('開啟流程')
        self.save_button = QPushButton('儲存流程')
        header.addWidget(self.open_button)
        header.addWidget(self.save_button)
        root.addLayout(header)
        transport = QHBoxLayout()
        self.check_button = QPushButton('1  檢查流程')
        self.play_button = QPushButton('2  ▶ 播放預覽')
        self.play_button.setObjectName('runButton')
        self.pause_button = QPushButton('Ⅱ 暫停')
        self.stop_button = QPushButton('■ 停止預覽')
        self.stop_button.setObjectName('stopButton')
        self.time_label = QLabel('00:00.0 / 02:00.0')
        for button in (self.check_button, self.play_button, self.pause_button, self.stop_button):
            transport.addWidget(button)
        transport.addWidget(self.time_label)
        transport.addStretch()
        self.speed_combo = QComboBox()
        for label, factor in [('1×', 1), ('5×', 5), ('10×', 10), ('30×', 30)]:
            self.speed_combo.addItem(label, factor)
        self.speed_combo.setCurrentIndex(1)
        transport.addWidget(QLabel('預覽速度'))
        transport.addWidget(self.speed_combo)
        root.addLayout(transport)
        self.guide = QLabel()
        self.guide.setWordWrap(True)
        root.addWidget(self.guide)
        body = QHBoxLayout()
        left = QVBoxLayout()
        tools = QHBoxLayout()
        tools.addWidget(QLabel('時間軌道  ·  拖曳移動，拖動邊界調整長度'))
        tools.addStretch()
        self.pump_combo = QComboBox()
        for i in range(4): self.pump_combo.addItem(f'幫浦 {i + 1}', i)
        self.add_button = QPushButton('＋ 新增區塊')
        self.undo_button = QPushButton('↶ 復原')
        self.minus_button = QPushButton('−')
        self.zoom_label = QLabel('100%')
        self.plus_button = QPushButton('＋')
        self.fit_button = QPushButton('適合視窗')
        for w in (self.pump_combo, self.add_button, self.undo_button, self.minus_button,
                  self.zoom_label, self.plus_button, self.fit_button): tools.addWidget(w)
        left.addLayout(tools)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.canvas)
        self.scroll.setMinimumHeight(TimelineCanvas.HEIGHT + 22)
        left.addWidget(self.scroll)
        legend = QLabel('→ 推注     ← 抽取（斜紋）     黃線：預覽游標     雙擊空白區域：新增區塊')
        legend.setWordWrap(True)
        left.addWidget(legend)
        self.status = QLabel('幫浦 1：等待中   |   幫浦 2：等待中   |   幫浦 3：等待中   |   幫浦 4：等待中')
        self.status.setWordWrap(True)
        left.addWidget(self.status)
        left.addStretch()
        body.addLayout(left, 1)
        self.inspector = QFrame()
        self.inspector.setObjectName('pumpPanel')
        self.inspector.setMinimumWidth(290)
        side = QVBoxLayout(self.inspector)
        self.selected_label = QLabel('區塊設定')
        self.selected_label.setStyleSheet('font-size: 12pt; font-weight: 700;')
        side.addWidget(self.selected_label)
        form = QFormLayout()
        self.start_spin = self._time_spin()
        self.end_spin = self._time_spin()
        self.direction_combo = QComboBox()
        self.direction_combo.addItem('→ 推注 Infuse', 'INF')
        self.direction_combo.addItem('← 抽取 Withdraw', 'WDR')
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setDecimals(4)
        self.rate_spin.setRange(0.0001, 9999)
        self.rate_spin.setValue(10)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(UNITS)
        for name, widget in [('開始（秒）', self.start_spin), ('結束（秒）', self.end_spin),
                             ('方向', self.direction_combo), ('流速', self.rate_spin), ('單位', self.unit_combo)]:
            form.addRow(name, widget)
        side.addLayout(form)
        self.volume_label = QLabel('預估體積：—')
        side.addWidget(self.volume_label)
        self.apply_button = QPushButton('套用區塊設定')
        self.apply_button.setObjectName('applyButton')
        self.cancel_button = QPushButton('取消修改')
        self.copy_button = QPushButton('複製區塊')
        self.delete_button = QPushButton('刪除區塊')
        for button in (self.apply_button, self.cancel_button, self.copy_button, self.delete_button): side.addWidget(button)
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); side.addWidget(line)
        side.addWidget(QLabel('流程總長度（秒）'))
        self.duration_spin = self._time_spin()
        self.duration_spin.setMinimum(1.0)
        self.duration_spin.setValue(self.model.total / 10)
        side.addWidget(self.duration_spin)
        self.duration_apply = QPushButton('套用總長度')
        self.duration_cancel = QPushButton('取消總長修改')
        side.addWidget(self.duration_apply)
        side.addWidget(self.duration_cancel)
        note = QLabel('狀態及預估體積僅供模擬。實際針筒、裝置與時序均需驗證。')
        note.setWordWrap(True)
        side.addWidget(note)
        side.addStretch()
        body.addWidget(self.inspector)
        root.addLayout(body, 1)
        self.notice_label = QLabel('示範數值可直接拖曳或修改。')
        self.notice_label.setWordWrap(True)
        root.addWidget(self.notice_label)
        self.check_button.clicked.connect(self.check_flow)
        self.play_button.clicked.connect(self.start_preview)
        self.pause_button.clicked.connect(self.pause_preview)
        self.stop_button.clicked.connect(self.stop_preview)
        self.open_button.clicked.connect(self.open_file)
        self.save_button.clicked.connect(self.save_file)
        self.add_button.clicked.connect(self.add_clip)
        self.undo_button.clicked.connect(self.undo)
        self.plus_button.clicked.connect(lambda: self.set_zoom(min(4.0, self.zoom * 2)))
        self.minus_button.clicked.connect(lambda: self.set_zoom(max(1.0, self.zoom / 2)))
        self.fit_button.clicked.connect(lambda: self.set_zoom(1.0))
        self.apply_button.clicked.connect(self.apply_clip)
        self.cancel_button.clicked.connect(self.cancel_clip)
        self.copy_button.clicked.connect(self.copy_clip)
        self.delete_button.clicked.connect(self.delete_clip)
        self.duration_apply.clicked.connect(self.apply_duration)
        self.duration_cancel.clicked.connect(self.cancel_duration)
        for control in (self.start_spin, self.end_spin, self.rate_spin):
            control.valueChanged.connect(self.mark_dirty)
            control.lineEdit().textEdited.connect(self.mark_text_pending)
        for control in (self.direction_combo, self.unit_combo): control.currentIndexChanged.connect(self.mark_dirty)
        self.duration_spin.valueChanged.connect(self.mark_duration_dirty)
        self.duration_spin.lineEdit().textEdited.connect(self.mark_duration_text_pending)

    @staticmethod
    def _time_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox(); spin.setDecimals(1); spin.setRange(0, 604800); spin.setSingleStep(0.1); return spin

    def busy(self) -> bool:
        return self.running or self.paused

    def show_notice(self, text: str) -> None:
        self.notice_label.setText(text)

    def set_zoom(self, value: float) -> None:
        if self.busy() or self.dirty or self.duration_dirty: return
        self.zoom = value; self.zoom_label.setText(f'{value * 100:.0f}%'); self.canvas.set_zoom(value); self.update_controls()

    def mark_text_pending(self, *_args) -> None:
        if not self.loading and not self.busy() and not self.duration_dirty:
            self.dirty = True
            self.update_controls()

    def mark_duration_text_pending(self, *_args) -> None:
        if not self.loading and not self.busy() and not self.dirty:
            self.duration_dirty = True
            self.update_controls()

    def mark_dirty(self, *_args) -> None:
        if self.loading or self.busy() or self.duration_dirty: return
        clip = self.model.get(self.canvas.selected)
        if clip:
            self.dirty = (round(self.start_spin.value() * 10) != clip.start or round(self.end_spin.value() * 10) != clip.end
                          or self.direction_combo.currentData() != clip.direction or self.rate_spin.value() != clip.rate
                          or self.unit_combo.currentText() != clip.unit)
        self.update_controls()

    def mark_duration_dirty(self, *_args) -> None:
        if self.loading or self.busy() or self.dirty: return
        self.duration_dirty = round(self.duration_spin.value() * 10) != self.model.total
        self.update_controls()

    def select_clip(self, clip_id: str) -> None:
        if self.dirty or self.duration_dirty or self.busy(): return
        clip = self.model.get(clip_id)
        self.loading = True
        try:
            self.canvas.selected = clip.id if clip else None
            if clip:
                self.pump_combo.setCurrentIndex(clip.pump)
                self.selected_label.setText(f'幫浦 {clip.pump + 1}  ·  區塊設定')
                self.start_spin.setValue(clip.start / 10); self.end_spin.setValue(clip.end / 10)
                self.direction_combo.setCurrentIndex(self.direction_combo.findData(clip.direction))
                self.rate_spin.setValue(clip.rate); self.unit_combo.setCurrentText(clip.unit)
                self.volume_label.setText(f'預估體積：{clip.volume_ul:.5g} µL')
            else:
                self.selected_label.setText('區塊設定'); self.volume_label.setText('預估體積：—')
        finally:
            self.loading = False
        self.canvas.update(); self.update_controls()

    def remember(self, old: Timeline | None = None) -> None:
        self.history.append((old or self.model).copy())
        if len(self.history) > 30: self.history.pop(0)

    def after_change(self, message: str) -> None:
        self.checked = False; self.canvas.model = self.model
        self.show_notice(message + ' 請重新檢查流程。')
        self.select_clip(self.canvas.selected or '')
        self.update_controls(); self.canvas.update()

    def record_drag(self, old: Timeline) -> None:
        self.remember(old); self.after_change('已調整區塊時間。')

    def add_clip_at(self, pump: int, tick: int) -> None:
        if self.busy() or self.dirty or self.duration_dirty: return
        try: clip = self.model.make_clip(pump, tick)
        except ValueError as exc: self.show_notice(str(exc)); return
        self.remember(); self.model.add(clip); self.canvas.selected = clip.id; self.after_change('已新增區塊。')

    def add_clip(self) -> None:
        self.add_clip_at(int(self.pump_combo.currentData()), 0)

    def copy_clip(self) -> None:
        if self.busy() or self.dirty or self.duration_dirty: return
        clip = self.model.get(self.canvas.selected)
        if not clip: return
        try:
            copy = self.model.make_clip(clip.pump, clip.end, clip.end - clip.start, clip.direction, clip.rate, clip.unit)
        except ValueError:
            try: copy = self.model.make_clip(clip.pump, 0, clip.end - clip.start, clip.direction, clip.rate, clip.unit)
            except ValueError as exc: self.show_notice(str(exc)); return
        self.remember(); self.model.add(copy); self.canvas.selected = copy.id; self.after_change('已複製區塊。')

    def delete_clip(self) -> None:
        if self.busy() or self.dirty or self.duration_dirty: return
        clip = self.model.get(self.canvas.selected)
        if not clip: return
        self.remember(); self.model.delete(clip.id); self.canvas.selected = self.model.clips[0].id if self.model.clips else None; self.after_change('已刪除區塊。')

    def undo(self) -> None:
        if self.busy() or self.dirty or self.duration_dirty or not self.history: return
        self.model = self.history.pop()
        if not self.model.get(self.canvas.selected): self.canvas.selected = self.model.clips[0].id if self.model.clips else None
        self.playhead = min(self.playhead, self.model.total)
        self.canvas.playhead = self.playhead
        self.loading = True; self.duration_spin.setValue(self.model.total / 10); self.loading = False
        self.after_change('已復原上一次編輯。')

    def apply_clip(self) -> None:
        if self.busy() or self.duration_dirty or not self.dirty: return
        clip = self.model.get(self.canvas.selected)
        if not clip: return
        if not all(s.hasAcceptableInput() for s in (self.start_spin, self.end_spin, self.rate_spin)):
            self.show_notice('請輸入完整且有效的時間與流速。'); return
        for spin in (self.start_spin, self.end_spin, self.rate_spin): spin.interpretText()
        candidate = replace(clip, start=round(self.start_spin.value() * 10), end=round(self.end_spin.value() * 10),
                            direction=str(self.direction_combo.currentData()), rate=self.rate_spin.value(), unit=self.unit_combo.currentText())
        old = self.model.copy()
        try: self.model.replace(candidate)
        except ValueError as exc: self.show_notice(str(exc)); return
        self.remember(old); self.dirty = False; self.after_change('已套用區塊設定。')

    def cancel_clip(self) -> None:
        if self.busy() or not self.dirty: return
        self.dirty = False; self.select_clip(self.canvas.selected or ''); self.show_notice('已取消未套用的區塊修改。')

    def apply_duration(self) -> None:
        if self.busy() or self.dirty or not self.duration_dirty: return
        if not self.duration_spin.hasAcceptableInput():
            self.show_notice('請輸入完整且有效的總長度。'); return
        self.duration_spin.interpretText()
        old = self.model.copy()
        try: self.model.set_total(round(self.duration_spin.value() * 10))
        except ValueError as exc: self.show_notice(str(exc)); return
        self.remember(old); self.duration_dirty = False
        self.playhead = min(self.playhead, self.model.total); self.canvas.playhead = self.playhead
        self.after_change('已套用總長度。')

    def cancel_duration(self) -> None:
        if self.busy() or not self.duration_dirty: return
        self.loading = True; self.duration_spin.setValue(self.model.total / 10); self.loading = False
        self.duration_dirty = False; self.show_notice('已取消總長度修改。'); self.update_controls()

    def check_flow(self) -> None:
        if self.busy() or self.dirty or self.duration_dirty: return
        try:
            self.model.validate()
            if not self.model.clips: raise ValueError('請先新增至少一個區塊。')
        except ValueError as exc:
            self.checked = False; self.show_notice(str(exc)); self.update_controls(); return
        self.checked = True; self.show_notice('已檢查流程資料。真實幫浦與同步時序尚未驗證。'); self.update_controls()

    def seek(self, ticks: float) -> None:
        if self.busy() or self.dirty or self.duration_dirty: return
        self.playhead = ticks; self.update_controls()

    def start_preview(self) -> None:
        if self.running or self.dirty or self.duration_dirty or not self.checked or not self.model.clips: return
        if self.playhead >= self.model.total: self.playhead = 0
        self.running = True; self.paused = False
        self.started_at = time.monotonic(); self.started_tick = self.playhead
        self.timer.start(); self.show_notice('正在模擬：不會送出任何幫浦命令。'); self.update_controls()

    def advance(self) -> None:
        if not self.running: return
        self.playhead = min(float(self.model.total), self.started_tick + (time.monotonic() - self.started_at) * 10 * float(self.speed_combo.currentData()))
        self.canvas.playhead = self.playhead
        self.canvas.active_ids = {c.id for c in self.model.active(self.playhead)}
        self.canvas.update(); self.update_controls()
        if self.playhead >= self.model.total:
            self.running = False; self.paused = False; self.timer.stop(); self.canvas.active_ids.clear()
            self.show_notice('預覽完成。'); self.update_controls(); self.canvas.update()

    def pause_preview(self) -> None:
        if not self.running: return
        self.advance()
        if not self.running: return
        self.running = False; self.paused = True; self.timer.stop(); self.canvas.active_ids.clear()
        self.show_notice('預覽已暫停；可繼續或停止後再編輯。'); self.update_controls(); self.canvas.update()

    def stop_preview(self) -> None:
        self.timer.stop(); self.running = False; self.paused = False; self.playhead = 0
        self.canvas.playhead = 0; self.canvas.active_ids.clear(); self.canvas.update()
        self.show_notice('已停止預覽並回到起點。'); self.update_controls()

    def save_file(self) -> None:
        if self.busy() or self.dirty or self.duration_dirty: return
        path, _ = QFileDialog.getSaveFileName(self, '儲存流程', 'NE501_timeline.json', 'JSON (*.json)')
        if not path: return
        try: Path(path).write_text(self.model.to_json(), encoding='utf-8')
        except (OSError, ValueError) as exc: QMessageBox.warning(self, '儲存失敗', str(exc)); return
        self.show_notice('流程已儲存。')

    def open_file(self) -> None:
        if self.busy() or self.dirty or self.duration_dirty: return
        path, _ = QFileDialog.getOpenFileName(self, '開啟流程', '', 'JSON (*.json)')
        if not path: return
        try:
            p = Path(path)
            if p.stat().st_size > 1_048_576: raise ValueError('流程檔超過 1 MB。')
            model = Timeline.from_json(p.read_text(encoding='utf-8'))
            if tuple(model.addresses) != self.config_addresses:
                raise ValueError('流程檔幫浦位址與目前程式設定不一致，請先確認各台位址。')
        except (OSError, ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, '開啟失敗', str(exc)); return
        self.remember(); self.model = model; self.canvas.model = model
        self.canvas.selected = model.clips[0].id if model.clips else None
        self.playhead = 0; self.canvas.playhead = 0
        self.loading = True; self.duration_spin.setValue(model.total / 10); self.loading = False
        self.after_change('已開啟流程。')

    def update_controls(self) -> None:
        busy, dirty = self.busy(), self.dirty or self.duration_dirty
        has_clip = self.model.get(self.canvas.selected) is not None
        self.canvas.editable = not busy and not dirty
        self.check_button.setEnabled(not busy and not dirty and bool(self.model.clips))
        self.play_button.setEnabled(not self.running and not dirty and self.checked and bool(self.model.clips))
        self.play_button.setText('▶ 繼續預覽' if self.paused else '2  ▶ 播放預覽')
        self.pause_button.setEnabled(self.running)
        self.stop_button.setEnabled(busy or self.playhead > 0)
        self.speed_combo.setEnabled(not busy)
        for button in (self.open_button, self.save_button, self.add_button, self.pump_combo): button.setEnabled(not busy and not dirty)
        self.undo_button.setEnabled(not busy and not dirty and bool(self.history))
        self.plus_button.setEnabled(not busy and not dirty and self.zoom < 4)
        self.minus_button.setEnabled(not busy and not dirty and self.zoom > 1)
        self.fit_button.setEnabled(not busy and not dirty and self.zoom > 1)
        for field in (self.start_spin, self.end_spin, self.rate_spin, self.direction_combo, self.unit_combo): field.setEnabled(has_clip and not busy and not self.duration_dirty)
        self.apply_button.setEnabled(has_clip and self.dirty and not busy)
        self.cancel_button.setEnabled(has_clip and self.dirty and not busy)
        self.copy_button.setEnabled(has_clip and not busy and not dirty)
        self.delete_button.setEnabled(has_clip and not busy and not dirty)
        self.duration_spin.setEnabled(not busy and not self.dirty)
        self.duration_apply.setEnabled(self.duration_dirty and not busy)
        self.duration_cancel.setEnabled(self.duration_dirty and not busy)
        if self.running: guide = '模擬預覽進行中；可按停止預覽。'
        elif self.paused: guide = '預覽已暫停；可繼續，或停止後再編輯。'
        elif self.dirty: guide = '請先套用或取消區塊修改。'
        elif self.duration_dirty: guide = '請先套用或取消總長度修改。'
        elif not self.model.clips: guide = '請先新增至少一個區塊。'
        elif not self.checked: guide = '編輯後請按「檢查流程」。'
        else: guide = f'流程資料已檢查，可從 {format_time(round(self.playhead))} 播放模擬預覽。'
        self.guide.setText(guide)
        for button, active in ((self.apply_button, self.dirty), (self.duration_apply, self.duration_dirty),
                               (self.add_button, not self.model.clips and not dirty and not busy),
                               (self.check_button, bool(self.model.clips) and not self.checked and not dirty and not busy),
                               (self.play_button, self.checked and not self.running and not dirty)):
            button.setStyleSheet('border: 2px solid #ffd166;' if active and button.isEnabled() else '')
        self.time_label.setText(f'{format_time(round(self.playhead))} / {format_time(self.model.total)}')
        active = {c.pump: c for c in self.model.active(self.playhead)} if self.running else {}
        values = []
        for i in range(4):
            clip = active.get(i)
            state = ('推注' if clip.direction == 'INF' else '抽取') + f' {clip.rate:g} {clip.unit}' if clip else ('預覽暫停' if self.paused else '等待中')
            values.append(f'幫浦 {i + 1}：{state}')
        self.status.setText('模擬狀態  ·  ' + '   |   '.join(values))
