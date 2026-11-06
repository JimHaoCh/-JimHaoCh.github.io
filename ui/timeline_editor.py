"""Desktop four-pump timeline editor and simulator; no hardware references."""
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import time

from PySide6.QtCore import Qt, QTimer, QSaveFile, QIODevice
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QScrollBar, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from ne501.timeline_model import Clip, Timeline, UNITS, example_timeline, format_time
from .timeline_canvas import TimelineCanvas


class FocusSpinBox(QDoubleSpinBox):
    """Scrolling an inspector must not silently change a pump setting."""
    def wheelEvent(self, event):
        event.ignore()


class FocusComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class TimelineEditor(QWidget):
    def __init__(self, addresses: list[int] | None = None, parent=None):
        super().__init__(parent)
        self.model = example_timeline(addresses)
        self.config_addresses = tuple(self.model.addresses)
        self.history: list[Timeline] = []
        self.future: list[Timeline] = []
        self.current_path: Path | None = None
        self.saved_snapshot = self.model.to_json()
        self.checked = False
        self.dirty = self.duration_dirty = self.loading = False
        self.running = self.paused = False
        self.playhead = 0.0
        self.zoom = 1.0
        self.started_at = self.started_tick = 0.0
        self.canvas = TimelineCanvas(self.model)
        self.canvas.selection_changed.connect(self.select_clip)
        self.canvas.model_changed.connect(self.record_drag)
        self.canvas.seeked.connect(self.seek)
        self.canvas.add_requested.connect(self.add_clip_at)
        self.canvas.track_selected.connect(self._select_track)
        self.canvas.notice.connect(self.show_notice)
        self.canvas.command.connect(self.handle_command)
        self.canvas.zoom_requested.connect(self.zoom_at)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.advance)
        self._build_ui()
        self.canvas.view_changed.connect(self.sync_view)
        self.select_clip(self.canvas.selected or '')
        self.sync_view()
        self.update_controls()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        banner = QLabel('時間軌模擬預覽  ·  0.1 秒編輯刻度；裝置同步誤差待量測。')
        banner.setObjectName('workflowBanner'); banner.setWordWrap(True)
        root.addWidget(banner)
        header = QHBoxLayout()
        self.file_label = QLabel('示範流程')
        self.file_label.setStyleSheet('font-size: 12pt; font-weight: 700;')
        self.file_label.setMinimumWidth(80)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header.addWidget(self.file_label, 1)
        self.new_button = QPushButton('新建')
        self.open_button = QPushButton('開啟')
        self.save_button = QPushButton('儲存')
        self.save_as_button = QPushButton('另存')
        self.inspector_button = QPushButton('區塊設定')
        self.inspector_button.setCheckable(True); self.inspector_button.setChecked(True)
        for b in (self.new_button, self.open_button, self.save_button, self.save_as_button, self.inspector_button): header.addWidget(b)
        root.addLayout(header)
        transport = QHBoxLayout()
        self.home_button = QPushButton('|◀ 起點')
        self.check_button = QPushButton('1 檢查流程')
        self.play_button = QPushButton('2 ▶ 播放')
        self.play_button.setObjectName('runButton')
        self.pause_button = QPushButton('Ⅱ 暫停')
        self.stop_button = QPushButton('■ 停止')
        self.stop_button.setObjectName('stopButton')
        for b in (self.home_button, self.check_button, self.play_button, self.pause_button, self.stop_button): transport.addWidget(b)
        transport.addStretch()
        self.speed_combo = FocusComboBox()
        for label, factor in [('1×', 1), ('5×', 5), ('10×', 10), ('30×', 30)]: self.speed_combo.addItem(label, factor)
        self.speed_combo.setToolTip('模擬播放速度；預設為實際時間 1×。')
        transport.addWidget(self.speed_combo)
        root.addLayout(transport)
        self.guide = QLabel(); self.guide.setWordWrap(True); root.addWidget(self.guide)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget(); left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0); left_layout.setSpacing(5)
        tools = QHBoxLayout()
        self.pump_combo = FocusComboBox()
        for i in range(4): self.pump_combo.addItem(f'幫浦 {i+1}', i)
        self.add_button = QPushButton('＋ 區塊')
        self.undo_button = QPushButton('↶')
        self.redo_button = QPushButton('↷')
        self.split_button = QPushButton('分割')
        self.snap_check = QCheckBox('吸附'); self.snap_check.setChecked(True)
        for w in (self.pump_combo, self.add_button, self.undo_button, self.redo_button, self.split_button): tools.addWidget(w)
        tools.addStretch(); tools.addWidget(self.snap_check)
        left_layout.addLayout(tools)
        navigation = QHBoxLayout()
        self.position_spin = self._time_spin(); self.position_spin.setMaximum(self.model.total / 10)
        self.position_spin.setMinimumWidth(85)
        self.position_spin.setToolTip('游標秒數；左右方向鍵移動 0.1 秒，Shift＋方向鍵移動 1 秒。')
        self.time_label = QLabel(); self.time_label.setMinimumWidth(85)
        navigation.addWidget(QLabel('游標 s'))
        navigation.addWidget(self.position_spin)
        navigation.addWidget(self.time_label)
        navigation.addStretch()
        self.minus_button = QPushButton('−'); self.plus_button = QPushButton('＋')
        for b in (self.minus_button, self.plus_button):
            b.setFixedWidth(34)
            b.setStyleSheet('padding-left: 4px; padding-right: 4px;')
        self.zoom_label = QLabel('100%'); self.zoom_label.setMinimumWidth(48)
        self.fit_button = QPushButton('全程')
        self.focus_button = QPushButton('選取')
        for w in (self.minus_button, self.zoom_label, self.plus_button, self.fit_button, self.focus_button): navigation.addWidget(w)
        left_layout.addLayout(navigation)
        left_layout.addWidget(self.canvas, 1)
        self.hscroll = QScrollBar(Qt.Orientation.Horizontal)
        self.hscroll.valueChanged.connect(lambda v: self.canvas.set_view(self.canvas.visible_ticks, v))
        left_layout.addWidget(self.hscroll)
        status_grid = QHBoxLayout()
        self.status_labels = []
        for pump in range(4):
            label = QLabel(); label.setWordWrap(True)
            status_grid.addWidget(label, 1)
            self.status_labels.append(label)
        left_layout.addLayout(status_grid)
        self.status = QLabel()  # Text mirror for accessibility and automation.
        self.status.hide()
        self.splitter.addWidget(left)
        self.inspector = QFrame(); self.inspector.setObjectName('timelineInspector')
        side = QVBoxLayout(self.inspector); side.setContentsMargins(10, 5, 10, 5)
        self.selected_label = QLabel('區塊設定'); self.selected_label.setStyleSheet('font-weight: 700;')
        side.addWidget(self.selected_label)
        form = QFormLayout(); form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.start_spin = self._time_spin(); self.end_spin = self._time_spin()
        self.direction_combo = FocusComboBox()
        self.direction_combo.addItem('→ 推注', 'INF'); self.direction_combo.addItem('← 抽取', 'WDR')
        self.rate_spin = FocusSpinBox(); self.rate_spin.setDecimals(4); self.rate_spin.setRange(.0001, 9999)
        self.rate_spin.setKeyboardTracking(False)
        self.unit_combo = FocusComboBox(); self.unit_combo.addItems(UNITS)
        for label, field in [('開始 s', self.start_spin), ('結束 s', self.end_spin), ('方向', self.direction_combo), ('流速', self.rate_spin), ('單位', self.unit_combo)]: form.addRow(label, field)
        side.addLayout(form)
        self.length_label = QLabel(); self.volume_label = QLabel()
        side.addWidget(self.length_label); side.addWidget(self.volume_label)
        row = QHBoxLayout()
        self.apply_button = QPushButton('套用'); self.apply_button.setObjectName('applyButton')
        self.cancel_button = QPushButton('取消')
        row.addWidget(self.apply_button); row.addWidget(self.cancel_button); side.addLayout(row)
        row = QHBoxLayout()
        self.copy_button = QPushButton('複製'); self.delete_button = QPushButton('刪除')
        row.addWidget(self.copy_button); row.addWidget(self.delete_button); side.addLayout(row)
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); side.addWidget(line)
        side.addWidget(QLabel('流程總長度（秒）'))
        self.duration_spin = self._time_spin(); self.duration_spin.setMinimum(1); self.duration_spin.setValue(self.model.total / 10)
        side.addWidget(self.duration_spin)
        row = QHBoxLayout()
        self.duration_apply = QPushButton('套用總長'); self.duration_cancel = QPushButton('取消')
        row.addWidget(self.duration_apply); row.addWidget(self.duration_cancel); side.addLayout(row)
        self.demo_button = QPushButton('載入示範'); side.addWidget(self.demo_button)
        note = QLabel('預估體積依設定計算。實際針筒、管路與裝置時序需驗證。')
        note.setObjectName('secondaryLabel'); note.setWordWrap(True); side.addWidget(note)
        side.addStretch()
        self.inspector_scroll = QScrollArea()
        self.inspector_scroll.setWidgetResizable(True); self.inspector_scroll.setWidget(self.inspector)
        self.inspector_scroll.setMinimumWidth(250); self.inspector_scroll.setMaximumWidth(330)
        self.inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.splitter.addWidget(self.inspector_scroll)
        self.splitter.setStretchFactor(0, 1); self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([850, 280])
        root.addWidget(self.splitter, 1)
        self.notice_label = QLabel('示範流程：可先拖曳區塊，再檢查並播放。')
        self.notice_label.setWordWrap(True); root.addWidget(self.notice_label)
        self.check_button.clicked.connect(self.check_flow)
        self.play_button.clicked.connect(self.start_preview)
        self.pause_button.clicked.connect(self.pause_preview)
        self.stop_button.clicked.connect(self.stop_preview)
        self.home_button.clicked.connect(self.return_to_start)
        self.new_button.clicked.connect(self.new_file)
        self.open_button.clicked.connect(self.open_file)
        self.save_button.clicked.connect(lambda: self.save_file())
        self.save_as_button.clicked.connect(lambda: self.save_file(save_as=True))
        self.demo_button.clicked.connect(self.load_demo)
        self.inspector_button.toggled.connect(self.inspector_scroll.setVisible)
        self.add_button.clicked.connect(self.add_clip)
        self.undo_button.clicked.connect(self.undo); self.redo_button.clicked.connect(self.redo)
        self.split_button.clicked.connect(self.split_clip)
        self.plus_button.clicked.connect(lambda: self.zoom_at(2))
        self.minus_button.clicked.connect(lambda: self.zoom_at(.5))
        self.fit_button.clicked.connect(self.fit_view); self.focus_button.clicked.connect(self.focus_clip)
        self.snap_check.toggled.connect(lambda enabled: setattr(self.canvas, 'snapping', enabled))
        self.pump_combo.currentIndexChanged.connect(self._track_from_combo)
        self.position_spin.valueChanged.connect(lambda value: self.seek(round(value * 10)))
        self.apply_button.clicked.connect(self.apply_clip); self.cancel_button.clicked.connect(self.cancel_clip)
        self.copy_button.clicked.connect(self.copy_clip); self.delete_button.clicked.connect(self.delete_clip)
        self.duration_apply.clicked.connect(self.apply_duration); self.duration_cancel.clicked.connect(self.cancel_duration)
        for control in (self.start_spin, self.end_spin, self.rate_spin):
            control.valueChanged.connect(self.mark_dirty)
            control.lineEdit().textEdited.connect(self.mark_text_pending)
            control.lineEdit().returnPressed.connect(self.apply_clip)
        for control in (self.direction_combo, self.unit_combo): control.currentIndexChanged.connect(self.mark_dirty)
        self.duration_spin.valueChanged.connect(self.mark_duration_dirty)
        self.duration_spin.lineEdit().textEdited.connect(self.mark_duration_text_pending)
        self.duration_spin.lineEdit().returnPressed.connect(self.apply_duration)
        self._shortcuts = []
        for key, callback in [('Ctrl+S', lambda: self.save_file()), ('Ctrl+Shift+S', lambda: self.save_file(save_as=True)), ('Ctrl+O', self.open_file)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback); self._shortcuts.append(shortcut)
        tips = {self.undo_button: '復原 Ctrl+Z（時間軌取得焦點時）', self.redo_button: '重做 Ctrl+Y',
                self.add_button: '在所選幫浦的游標位置尋找空位；也可雙擊軌道空白處。',
                self.split_button: '在游標處分割選取區塊 Ctrl+B', self.focus_button: '放大選取區塊 F',
                self.snap_check: '拖曳時吸附到區塊邊界或游標；按住 Alt 暫時關閉。',
                self.stop_button: '停止模擬並保留游標位置；「起點」回到 0。',
                self.apply_button: '套用區塊設定 Enter', self.cancel_button: '取消尚未套用的設定'}
        for widget, tip in tips.items(): widget.setToolTip(tip)

    @staticmethod
    def _time_spin():
        spin = FocusSpinBox(); spin.setDecimals(1); spin.setRange(0, 604800)
        spin.setSingleStep(.1); spin.setKeyboardTracking(False)
        return spin

    def heightForWidth(self, width):
        # QScrollArea otherwise reserves the inspector's full preferred height,
        # even though that inspector already has its own vertical scrollbar.
        return self.layout().minimumHeightForWidth(width)

    def busy(self): return self.running or self.paused
    def pending(self): return self.dirty or self.duration_dirty
    def modified(self): return self.model.to_json() != self.saved_snapshot
    def show_notice(self, text): self.notice_label.setText(text)

    def _select_track(self, pump):
        self.pump_combo.blockSignals(True); self.pump_combo.setCurrentIndex(pump); self.pump_combo.blockSignals(False)

    def _track_from_combo(self, index):
        self.canvas.active_track = index; self.canvas.update()

    def sync_view(self):
        self.hscroll.blockSignals(True)
        self.hscroll.setRange(0, self.model.total - self.canvas.visible_ticks)
        self.hscroll.setPageStep(self.canvas.visible_ticks)
        self.hscroll.setSingleStep(max(1, self.canvas.visible_ticks // 10))
        self.hscroll.setValue(self.canvas.view_start)
        self.hscroll.setEnabled(self.canvas.visible_ticks < self.model.total)
        self.hscroll.blockSignals(False)
        self.zoom = self.model.total / self.canvas.visible_ticks
        self.zoom_label.setText(f'{self.zoom:.1f}×')
        self.minus_button.setEnabled(self.canvas.visible_ticks < self.model.total)
        self.fit_button.setEnabled(self.canvas.visible_ticks < self.model.total)
        self.plus_button.setEnabled(self.canvas.visible_ticks > 5)

    def zoom_at(self, factor, anchor_x=None):
        if self.canvas.drag: return
        x = self.canvas.tick_to_x(self.playhead) if anchor_x is None else anchor_x
        x = max(self.canvas.LEFT, min(self.canvas.width() - self.canvas.RIGHT, x))
        fraction = (x - self.canvas.LEFT) / self.canvas.track_width()
        tick = self.canvas.view_start + fraction * self.canvas.visible_ticks
        span = max(5, min(self.model.total, round(self.canvas.visible_ticks / factor)))
        self.canvas.set_view(span, tick - fraction * span)

    def set_zoom(self, value): self.zoom_at(value / self.zoom)
    def fit_view(self): self.canvas.set_view(self.model.total, 0)

    def focus_clip(self):
        clip = self.model.get(self.canvas.selected)
        if not clip: return
        span = max(5, min(self.model.total, round((clip.end - clip.start) * 1.6)))
        self.canvas.set_view(span, (clip.start + clip.end - span) / 2)
        self.canvas.setFocus()

    def mark_text_pending(self, *_):
        if not self.loading and not self.busy() and not self.duration_dirty:
            self.dirty = True; self.update_controls()

    def mark_duration_text_pending(self, *_):
        if not self.loading and not self.busy() and not self.dirty:
            self.duration_dirty = True; self.update_controls()

    def mark_dirty(self, *_):
        if self.loading or self.busy() or self.duration_dirty: return
        clip = self.model.get(self.canvas.selected)
        if clip:
            self.dirty = (round(self.start_spin.value()*10) != clip.start or round(self.end_spin.value()*10) != clip.end
                          or self.rate_spin.value() != clip.rate or self.direction_combo.currentData() != clip.direction
                          or self.unit_combo.currentText() != clip.unit)
        self.update_controls()

    def mark_duration_dirty(self, *_):
        if not self.loading and not self.busy() and not self.dirty:
            self.duration_dirty = round(self.duration_spin.value()*10) != self.model.total
            self.update_controls()

    def select_clip(self, clip_id):
        if self.pending() or self.busy(): return
        clip = self.model.get(clip_id)
        self.loading = True
        try:
            self.canvas.selected = clip.id if clip else None
            if clip:
                self.canvas.active_track = clip.pump; self._select_track(clip.pump)
                self.selected_label.setText(f'幫浦 {clip.pump+1} · 區塊設定')
                self.start_spin.setMaximum(self.model.total / 10); self.end_spin.setMaximum(self.model.total / 10)
                self.start_spin.setValue(clip.start/10); self.end_spin.setValue(clip.end/10)
                self.direction_combo.setCurrentIndex(self.direction_combo.findData(clip.direction))
                self.rate_spin.setValue(clip.rate); self.unit_combo.setCurrentText(clip.unit)
                self.length_label.setText(f'持續時間：{(clip.end-clip.start)/10:g} 秒')
                self.volume_label.setText(f'預估體積：{clip.volume_ul:.5g} µL')
            else:
                self.selected_label.setText('點選區塊以設定'); self.length_label.setText('持續時間：—'); self.volume_label.setText('預估體積：—')
        finally: self.loading = False
        self.canvas.update(); self.update_controls()

    def remember(self, old=None):
        self.history.append((old or self.model).copy())
        if len(self.history) > 100: self.history.pop(0)
        self.future.clear()

    def after_change(self, message):
        self.checked = False
        self.canvas.model = self.model
        self.playhead = min(self.playhead, self.model.total)
        self.canvas.playhead = self.playhead; self.canvas.active_ids.clear()
        self.canvas.set_view(min(self.canvas.visible_ticks, self.model.total))
        self.loading = True; self.duration_spin.setValue(self.model.total/10); self.loading = False
        self.select_clip(self.canvas.selected or '')
        self.show_notice(message + ' 請重新檢查流程。')
        self.update_controls()

    def record_drag(self, old):
        self.remember(old); self.after_change('已調整區塊。')

    def add_clip_at(self, pump, tick):
        if self.busy() or self.pending(): return
        # A double click inserts exactly in that gap, with a visible default length.
        next_start = min((c.start for c in self.model.clips if c.pump == pump and c.start > tick), default=self.model.total)
        if any(c.pump == pump and c.start <= tick < c.end for c in self.model.clips) or tick >= self.model.total:
            self.show_notice('此位置已有區塊，請選擇空白時間。'); return
        length = min(150, next_start-tick)
        if length < 1: return
        clip = self.model.make_clip(pump, tick, length)
        try: self.model.copy().add(clip)
        except ValueError as exc: self.show_notice(str(exc)); return
        self.remember(); self.model.add(clip); self.canvas.selected = clip.id
        self.after_change(f'已新增 {length/10:g} 秒區塊。'); self.canvas.reveal(clip.start)

    def add_clip(self):
        if self.busy() or self.pending(): return
        pump = int(self.pump_combo.currentData()); tick = round(self.playhead)
        try: clip = self.model.make_clip(pump, tick)
        except ValueError as exc: self.show_notice(str(exc)); return
        try: self.model.copy().add(clip)
        except ValueError as exc: self.show_notice(str(exc)); return
        self.remember(); self.model.add(clip); self.canvas.selected = clip.id
        self.after_change(f'已在 {format_time(clip.start)} 新增 15 秒區塊。'); self.canvas.reveal(clip.start)

    def copy_clip(self):
        if self.busy() or self.pending(): return
        clip = self.model.get(self.canvas.selected)
        if not clip: return
        try:
            try: copied = self.model.make_clip(clip.pump, clip.end, clip.end-clip.start, clip.direction, clip.rate, clip.unit)
            except ValueError: copied = self.model.make_clip(clip.pump, 0, clip.end-clip.start, clip.direction, clip.rate, clip.unit)
            self.model.copy().add(copied)
        except ValueError as exc: self.show_notice(str(exc)); return
        self.remember(); self.model.add(copied); self.canvas.selected = copied.id
        self.after_change(f'已複製到 {format_time(copied.start)}。'); self.canvas.reveal(copied.start)

    def split_clip(self):
        if self.busy() or self.pending(): return
        clip = self.model.get(self.canvas.selected)
        if not clip or not clip.start < round(self.playhead) < clip.end:
            self.show_notice('請將游標放在選取區塊內部，再按分割。'); return
        old = self.model.copy()
        try: right = self.model.split(clip.id, round(self.playhead))
        except ValueError as exc: self.show_notice(str(exc)); return
        self.remember(old); self.canvas.selected = right.id
        self.after_change('已分割為相鄰兩個區塊；方向與流速均保留。')

    def delete_clip(self):
        if self.busy() or self.pending(): return
        clip = self.model.get(self.canvas.selected)
        if not clip: return
        self.remember(); self.model.delete(clip.id)
        same = [c for c in self.model.clips if c.pump == clip.pump]
        nearest = min(same or self.model.clips, key=lambda c: abs(c.start-clip.start), default=None)
        self.canvas.selected = nearest.id if nearest else None
        self.after_change('已刪除區塊；Ctrl+Z 可復原。')

    def _restore(self, model, message):
        self.model = model
        if not self.model.get(self.canvas.selected): self.canvas.selected = self.model.clips[0].id if self.model.clips else None
        self.after_change(message)

    def undo(self):
        if self.busy() or self.pending() or not self.history: return
        self.future.append(self.model.copy()); self._restore(self.history.pop(), '已復原。')

    def redo(self):
        if self.busy() or self.pending() or not self.future: return
        self.history.append(self.model.copy()); self._restore(self.future.pop(), '已重做。')

    def apply_clip(self):
        if self.busy() or self.duration_dirty or not self.dirty: return False
        clip = self.model.get(self.canvas.selected)
        if not clip: return False
        if not all(s.hasAcceptableInput() for s in (self.start_spin, self.end_spin, self.rate_spin)):
            self.show_notice('請輸入完整且有效的時間與流速。'); return False
        self.loading = True
        for spin in (self.start_spin, self.end_spin, self.rate_spin): spin.interpretText()
        self.loading = False
        candidate = replace(clip, start=round(self.start_spin.value()*10), end=round(self.end_spin.value()*10),
                            direction=str(self.direction_combo.currentData()), rate=self.rate_spin.value(), unit=self.unit_combo.currentText())
        old = self.model.copy()
        try: self.model.replace(candidate)
        except ValueError as exc: self.show_notice(str(exc)); return False
        if candidate != clip: self.remember(old)
        self.dirty = False; self.after_change('已套用設定。'); return True

    def cancel_clip(self):
        if self.busy() or not self.dirty: return
        self.dirty = False; self.select_clip(self.canvas.selected or ''); self.show_notice('已取消未套用的區塊修改。')

    def apply_duration(self):
        if self.busy() or self.dirty or not self.duration_dirty: return False
        if not self.duration_spin.hasAcceptableInput(): self.show_notice('請輸入有效的總長度。'); return False
        self.loading = True; self.duration_spin.interpretText(); self.loading = False
        old = self.model.copy()
        try: self.model.set_total(round(self.duration_spin.value()*10))
        except ValueError as exc: self.show_notice(str(exc)); return False
        self.remember(old); self.duration_dirty = False
        self.after_change('已套用總長度。'); return True

    def cancel_duration(self):
        if self.busy() or not self.duration_dirty: return
        self.loading = True; self.duration_spin.setValue(self.model.total/10); self.loading = False
        self.duration_dirty = False; self.show_notice('已取消總長度修改。'); self.update_controls()

    def check_flow(self):
        if self.busy() or self.pending(): return
        try:
            self.model.validate()
            if not self.model.clips: raise ValueError('請先新增至少一個區塊。')
        except ValueError as exc:
            self.checked = False; self.show_notice(str(exc)); self.update_controls(); return
        self.checked = True; self.show_notice('流程資料檢查完成。播放為模擬；尚未量測實際幫浦同步。'); self.update_controls()

    def seek(self, ticks):
        if self.running or self.pending(): return
        self.playhead = max(0, min(self.model.total, round(ticks)))
        self.canvas.playhead = self.playhead
        self.canvas.active_ids = {c.id for c in self.model.active(self.playhead)} if self.paused else set()
        self.canvas.reveal(self.playhead); self.canvas.update(); self.update_controls()

    def return_to_start(self):
        self.stop_preview(); self.seek(0)

    def start_preview(self):
        if self.running or self.pending() or not self.checked or not self.model.clips: return
        if self.playhead >= self.model.total: self.playhead = 0
        self.running = True; self.paused = False
        self.started_at = time.monotonic(); self.started_tick = self.playhead
        self.canvas.active_ids = {c.id for c in self.model.active(self.playhead)}
        self.timer.start(); self.show_notice('模擬播放中。停止會保留游標；「起點」回到 0。'); self.update_controls(); self.canvas.update()

    def advance(self):
        if not self.running: return
        self.playhead = min(float(self.model.total), self.started_tick + (time.monotonic()-self.started_at)*10*float(self.speed_combo.currentData()))
        self.canvas.playhead = self.playhead
        self.canvas.active_ids = {c.id for c in self.model.active(self.playhead)}
        self.canvas.reveal(self.playhead); self.canvas.update()
        self.update_transport()
        if self.playhead >= self.model.total:
            self.running = self.paused = False; self.timer.stop(); self.canvas.active_ids.clear()
            self.show_notice('模擬播放完成。'); self.update_controls(); self.canvas.update()

    def pause_preview(self):
        if not self.running: return
        self.advance()
        if not self.running: return
        self.running = False; self.paused = True; self.timer.stop()
        self.show_notice('已暫停；可移動游標再繼續，或停止後編輯。'); self.update_controls(); self.canvas.update()

    def stop_preview(self):
        self.timer.stop(); self.running = self.paused = False
        self.canvas.playhead = self.playhead; self.canvas.active_ids.clear(); self.canvas.cancel_drag()
        self.show_notice(f'已停止，游標保留在 {format_time(math.floor(self.playhead))}。'); self.update_controls(); self.canvas.update()

    def handle_command(self, command):
        if self.canvas.drag:
            self.canvas.cancel_drag()
        if command == 'toggle':
            if self.running: self.pause_preview()
            elif not self.pending():
                if not self.checked: self.check_flow()
                self.start_preview()
        elif command == 'inspect':
            self.inspector_button.setChecked(True); self.start_spin.setFocus(); self.start_spin.selectAll()
        elif command == 'cancel':
            if self.dirty: self.cancel_clip()
            elif self.duration_dirty: self.cancel_duration()
        elif command.startswith('nudge:'):
            if self.busy() or self.pending(): return
            clip = self.model.get(self.canvas.selected)
            if not clip: return
            delta = int(command.split(':')[1])
            candidate = replace(clip, start=clip.start+delta, end=clip.end+delta)
            old = self.model.copy()
            try: self.model.replace(candidate)
            except ValueError as exc: self.show_notice(str(exc)); return
            self.remember(old); self.after_change('已微調區塊。'); self.canvas.reveal(candidate.start)
        else:
            actions = {'delete': self.delete_clip, 'copy': self.copy_clip, 'split': self.split_clip,
                       'undo': self.undo, 'redo': self.redo, 'focus': self.focus_clip,
                       'home': self.return_to_start, 'end': lambda: self.seek(self.model.total),
                       'zoom_in': lambda: self.zoom_at(2), 'zoom_out': lambda: self.zoom_at(.5)}
            if command in actions: actions[command]()

    def prepare_to_leave(self):
        """Resolve pending inspector edits and unsaved project changes explicitly."""
        self.canvas.cancel_drag()
        if self.busy(): self.stop_preview()
        if self.pending():
            choice = QMessageBox.question(self, '尚有未套用的設定', '先套用目前設定？\n「否」會捨棄這次欄位修改。',
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if choice == QMessageBox.StandardButton.Cancel: return False
            if choice == QMessageBox.StandardButton.Yes:
                if not (self.apply_clip() if self.dirty else self.apply_duration()): return False
            elif self.dirty: self.cancel_clip()
            else: self.cancel_duration()
        if not self.modified(): return True
        choice = QMessageBox.question(self, '流程尚未儲存', '要儲存目前流程嗎？',
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Save)
        if choice == QMessageBox.StandardButton.Cancel: return False
        return self.save_file() if choice == QMessageBox.StandardButton.Save else True

    def save_file(self, save_as=False):
        self.canvas.cancel_drag()
        if self.busy() or self.pending():
            self.show_notice('請先停止播放，並套用或取消欄位修改後儲存。'); return False
        path = self.current_path
        if save_as or path is None:
            chosen, _ = QFileDialog.getSaveFileName(self, '儲存流程', str(path or 'NE501_timeline.json'), 'JSON (*.json)')
            if not chosen: return False
            path = Path(chosen)
            if not path.suffix: path = path.with_suffix('.json')
        try:
            contents = self.model.to_json()
            output = QSaveFile(str(path))
            if not output.open(QIODevice.OpenModeFlag.WriteOnly): raise OSError(output.errorString())
            data = contents.encode('utf-8')
            if output.write(data) != len(data):
                output.cancelWriting(); raise OSError(output.errorString())
            if not output.commit(): raise OSError(output.errorString())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '儲存失敗', str(exc)); return False
        self.current_path = path; self.saved_snapshot = contents
        self.show_notice(f'已儲存：{path.name}'); self.update_controls(); return True

    def _load_model(self, model, path=None):
        self.model = model; self.current_path = path; self.saved_snapshot = model.to_json()
        self.history.clear(); self.future.clear(); self.checked = False
        self.canvas.model = model; self.canvas.selected = model.clips[0].id if model.clips else None
        self.playhead = self.canvas.playhead = 0; self.canvas.active_ids.clear()
        self.canvas.set_view(model.total, 0)
        self.loading = True; self.duration_spin.setValue(model.total/10); self.loading = False
        self.select_clip(self.canvas.selected or ''); self.update_controls()

    def open_file(self):
        if self.busy(): return
        self.canvas.cancel_drag()
        chosen, _ = QFileDialog.getOpenFileName(self, '開啟流程', str(self.current_path.parent) if self.current_path else '', 'JSON (*.json)')
        if not chosen: return
        try:
            path = Path(chosen)
            if path.stat().st_size > 1_048_576: raise ValueError('流程檔超過 1 MB。')
            model = Timeline.from_json(path.read_text(encoding='utf-8'))
            if tuple(model.addresses) != self.config_addresses:
                raise ValueError(f'流程幫浦位址 {model.addresses} 與目前設定 {list(self.config_addresses)} 不一致。')
        except (OSError, ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, '開啟失敗', str(exc)); return
        if not self.prepare_to_leave(): return
        self._load_model(model, path); self.show_notice(f'已開啟：{path.name}')

    def new_file(self):
        if self.busy() or not self.prepare_to_leave(): return
        self._load_model(Timeline(1200, addresses=list(self.config_addresses)))
        self.show_notice('新流程：先選擇幫浦，再新增區塊。')

    def load_demo(self):
        if self.busy() or not self.prepare_to_leave(): return
        self._load_model(example_timeline(list(self.config_addresses))); self.show_notice('已載入示範流程。')

    def update_transport(self):
        # Floor prevents the displayed clock announcing a boundary before it occurs.
        tick = math.floor(self.playhead + 1e-8)
        self.position_spin.blockSignals(True)
        self.position_spin.setMaximum(self.model.total/10); self.position_spin.setValue(tick/10)
        self.position_spin.blockSignals(False)
        self.time_label.setText('/ ' + format_time(self.model.total))
        active = {c.pump: c for c in self.model.active(self.playhead)} if self.busy() else {}
        values = []
        for i, label in enumerate(self.status_labels):
            clip = active.get(i)
            if clip:
                state = ('推注' if clip.direction == 'INF' else '抽取') + f' {clip.rate:g} {clip.unit}'
                if self.paused: state = '暫停於 ' + state
            else: state = '暫停' if self.paused else '等待' if self.running else '停止'
            value = f'模擬 {i+1}：{state}'; label.setText(value); values.append(value)
        self.status.setText(' | '.join(values))

    def update_controls(self):
        busy, pending = self.busy(), self.pending()
        has_clip = self.model.get(self.canvas.selected) is not None
        self.canvas.editable = not busy and not pending
        self.canvas.seek_enabled = not self.running and not pending
        self.check_button.setEnabled(not busy and not pending and bool(self.model.clips))
        self.play_button.setEnabled(not self.running and not pending and self.checked and bool(self.model.clips))
        self.play_button.setText('▶ 繼續' if self.paused else '2 ▶ 播放')
        self.pause_button.setEnabled(self.running); self.stop_button.setEnabled(busy)
        self.home_button.setEnabled(not pending and (busy or self.playhead > 0))
        self.speed_combo.setEnabled(not busy)
        self.position_spin.setEnabled(not self.running and not pending)
        for b in (self.new_button, self.open_button, self.demo_button): b.setEnabled(not busy)
        for b in (self.save_button, self.save_as_button): b.setEnabled(not busy and not pending)
        for b in (self.add_button, self.pump_combo): b.setEnabled(not busy and not pending)
        self.undo_button.setEnabled(not busy and not pending and bool(self.history))
        self.redo_button.setEnabled(not busy and not pending and bool(self.future))
        clip = self.model.get(self.canvas.selected)
        self.split_button.setEnabled(bool(clip and clip.start < self.playhead < clip.end) and not busy and not pending)
        self.focus_button.setEnabled(has_clip)
        for field in (self.start_spin, self.end_spin, self.rate_spin, self.direction_combo, self.unit_combo): field.setEnabled(has_clip and not busy and not self.duration_dirty)
        self.apply_button.setEnabled(has_clip and self.dirty and not busy); self.cancel_button.setEnabled(has_clip and self.dirty and not busy)
        self.copy_button.setEnabled(has_clip and not busy and not pending); self.delete_button.setEnabled(has_clip and not busy and not pending)
        self.duration_spin.setEnabled(not busy and not self.dirty)
        self.duration_apply.setEnabled(self.duration_dirty and not busy); self.duration_cancel.setEnabled(self.duration_dirty and not busy)
        if self.running: guide = '模擬播放中 · 可暫停或停止。'
        elif self.paused: guide = '已暫停 · 可定位游標並繼續；停止後可編輯。'
        elif self.dirty: guide = '請先套用或取消右側區塊設定。'
        elif self.duration_dirty: guide = '請先套用或取消流程總長度。'
        elif not self.model.clips: guide = '請選擇幫浦並新增區塊。'
        elif not self.checked: guide = '編輯後，按「1 檢查流程」再播放。'
        else: guide = '資料已檢查 · 按播放或時間軌空白鍵開始模擬。'
        self.guide.setText(guide)
        for button, highlight in ((self.apply_button, self.dirty), (self.duration_apply, self.duration_dirty),
                                  (self.add_button, not self.model.clips and not pending and not busy),
                                  (self.check_button, bool(self.model.clips) and not self.checked and not pending and not busy),
                                  (self.play_button, self.checked and not self.running and not pending)):
            button.setStyleSheet('border: 2px solid #ffd166;' if highlight and button.isEnabled() else '')
        name = self.current_path.name if self.current_path else '示範／未命名流程'
        self.file_label.setText(('● ' if self.modified() or pending else '') + name)
        self.file_label.setToolTip(str(self.current_path or '尚未指定儲存檔案'))
        self.update_transport()
