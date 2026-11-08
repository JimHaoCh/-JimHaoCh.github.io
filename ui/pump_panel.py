from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import time
import math
from ne501.syringe import format_diameter

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from .i18n import manager
from .unit_fields import preserve_quantity
from ne501.syringe import FLOW_UL_MIN
from .i18n_widgets import (
    Button as QPushButton, CheckBox as QCheckBox, ComboBox as QComboBox,
    GroupBox, Label as QLabel, SpinBox as QDoubleSpinBox,
)

RATE_UNITS = [("µL/min", "UM"), ("mL/min", "MM"), ("µL/hr", "UH"), ("mL/hr", "MH")]
VOLUME_UNITS = [("µL", "UL"), ("mL", "ML")]
RATE_LABELS = dict((code, label) for label, code in RATE_UNITS)


@dataclass(frozen=True)
class PumpSettings:
    rate: float
    rate_unit: str
    direction: str
    continuous: bool
    volume: float
    volume_unit: str
    prime_enabled: bool
    prime_volume: float
    prime_volume_unit: str
    prime_speed_level: str


class PumpPanel(GroupBox):
    set_diameter_requested = Signal(int, float)
    apply_requested = Signal(int, object)
    run_requested = Signal(int)
    stop_requested = Signal(int)
    active_changed = Signal(int, bool)
    edit_requested = Signal(int)
    state_changed = Signal()
    shared_setup_requested = Signal()
    new_dose_requested = Signal(int)

    def __init__(self, address: int, parent=None, index=None):
        super().__init__('', parent)
        self.address = address
        self.index = index if index is not None else address + 1
        self.workflow_managed = False
        self.station_managed = False
        self.workflow_used = True
        self.planned_diameter = None
        self.external_start_blocker = ""
        self.external_plan_pending = False
        self.confirmed_diameter = None
        self.settings_applied = False
        self.applied_snapshot = None
        self.connection_available = False
        self.online = self.running = self.busy = False
        self._internal_update = False
        self._diameter_editing = True
        self._group_notice = ''
        self._compact = False
        self.last_status = None
        self.last_checked = None
        self.checked_at = 0.0
        self.last_response_source = ''
        self.stop_pending = False
        self.stop_requires_reset = False
        self.setTitle(f'Pump {self.index} | Address {address:02d}')
        self.setObjectName('pumpPanel')
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        for key in ('selected', 'running', 'online', 'active', 'diameterVerified'):
            self.setProperty(key, False)

        self.status_label = QLabel('● Offline')
        self.status_label.setObjectName('offlineStatus')
        self.version_label = QLabel('Not scanned')
        self.version_label.hide()
        self.active_checkbox = QCheckBox('Group')
        self.active_checkbox.setToolTip('Include this pump in group actions.')
        top = QHBoxLayout()
        top.addWidget(self.status_label)
        top.addStretch()
        top.addWidget(self.active_checkbox)
        self.motion_label = QLabel('Reported: Unknown')
        self.motion_label.setObjectName('secondaryLabel')
        self.target_label = QLabel()
        self.target_label.setObjectName('pumpTarget')
        self.target_label.setWordWrap(True)
        self.mode_label = QLabel()
        self.mode_label.setObjectName('secondaryLabel')
        self.mode_label.setWordWrap(True)
        self.ready_label = QLabel()
        self.ready_label.setWordWrap(True)
        self.group_hint_label = QLabel()
        self.group_hint_label.setObjectName('secondaryLabel')
        self.group_hint_label.setWordWrap(True)
        self.last_check_label = QLabel('No confirmed status yet')
        self.last_check_label.setObjectName('secondaryLabel')
        self.last_check_label.setWordWrap(True)
        self.edit_button = QPushButton('Edit')
        self.run_button = QPushButton('Start')
        self.run_button.setObjectName('runButton')
        self.stop_button = QPushButton('Stop')
        self.stop_button.setObjectName('stopButton')
        self.stop_button.setToolTip('Stop available after connecting; verify the response before assuming the pump stopped.')
        actions = QHBoxLayout()
        for button in (self.edit_button, self.run_button, self.stop_button):
            actions.addWidget(button)
        card = QVBoxLayout(self)
        card.setContentsMargins(9, 8, 9, 7)
        card.setSpacing(4)
        card.addLayout(top)
        for label in (self.motion_label, self.target_label, self.mode_label,
                      self.ready_label, self.group_hint_label, self.last_check_label):
            card.addWidget(label)
        card.addLayout(actions)

        self.editor = QWidget()
        detail = QVBoxLayout(self.editor)
        detail.setContentsMargins(10, 6, 10, 8)
        detail.setSpacing(7)
        self.editor_title = QLabel(f'Pump {self.index} settings | Address {address:02d}')
        self.editor_title.setStyleSheet('font-size: 12pt; font-weight: 700;')
        detail.addWidget(self.editor_title)
        steps = QHBoxLayout()
        steps.setSpacing(4)
        self.step_labels = []
        for text in ('1 Diameter', '2 Delivery', '3 Verify', '4 Start'):
            label = QLabel(text)
            label.setObjectName('workflowStep')
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.step_labels.append(label)
            steps.addWidget(label, 1)
        detail.addLayout(steps)
        self.step_banner = QLabel()
        self.step_banner.setObjectName('nextStepBanner')
        self.step_banner.setWordWrap(True)
        detail.addWidget(self.step_banner)

        self.diameter_fields = QWidget()
        diameter = QHBoxLayout(self.diameter_fields)
        diameter.setContentsMargins(0, 0, 0, 0)
        self.diameter_input = QDoubleSpinBox()
        self.diameter_input.setRange(.1, 50)
        self.diameter_input.setDecimals(3)
        self.diameter_input.setSingleStep(.001)
        self.diameter_input.setValue(10)
        self.diameter_input.setSuffix(' mm')
        self.diameter_input.setToolTip('Enter the actual syringe inside diameter in millimetres.')
        self.set_diameter_button = QPushButton('Verify diameter')
        self.set_diameter_button.setObjectName('applyButton')
        diameter.addWidget(self.diameter_input, 1)
        diameter.addWidget(self.set_diameter_button)
        detail.addWidget(self.diameter_fields)
        self.diameter_status = QLabel('Diameter not verified')
        self.diameter_status.setWordWrap(True)
        self.diameter_status.setObjectName('pendingLabel')
        self.change_diameter_button = QPushButton('Change')
        self.change_diameter_button.setObjectName('secondaryButton')
        self.change_diameter_button.clicked.connect(self.open_diameter_editor)
        diameter_summary = QHBoxLayout()
        diameter_summary.addWidget(self.diameter_status, 1)
        diameter_summary.addWidget(self.change_diameter_button)
        detail.addLayout(diameter_summary)

        detail.addWidget(QLabel('2  Delivery settings'))
        self.rate_input = QDoubleSpinBox()
        self.rate_input.setDecimals(4)
        self.rate_input.setRange(.0001, 9999)
        self.rate_input.setValue(1)
        self.rate_unit_combo = QComboBox()
        for label, code in RATE_UNITS:
            self.rate_unit_combo.addItem(label, code)
        self.rate_unit_combo.setCurrentIndex(3)
        rate = QHBoxLayout()
        rate.addWidget(self.rate_input, 1)
        rate.addWidget(self.rate_unit_combo)
        detail.addWidget(QLabel('Rate'))
        detail.addLayout(rate)
        self.unit_notice = QLabel()
        self.unit_notice.setWordWrap(True)
        self.unit_notice.setObjectName('pendingLabel')
        self.unit_notice.hide()
        detail.addWidget(self.unit_notice)
        self.direction_combo = QComboBox()
        self.direction_combo.addItem('Infuse', 'INF')
        self.direction_combo.addItem('Withdraw', 'WDR')
        self.mode_combo = QComboBox()
        self.mode_combo.addItem('Continuous', True)
        self.mode_combo.addItem('Target volume', False)
        self.continuous_checkbox = QCheckBox('Continuous')
        self.continuous_checkbox.setChecked(True)
        self.continuous_checkbox.hide()
        delivery = QGridLayout()
        delivery.addWidget(QLabel('Direction'), 0, 0)
        delivery.addWidget(QLabel('Mode'), 0, 1)
        delivery.addWidget(self.direction_combo, 1, 0)
        delivery.addWidget(self.mode_combo, 1, 1)
        delivery.setColumnStretch(0, 1)
        delivery.setColumnStretch(1, 1)
        detail.addLayout(delivery)
        self.volume_input = QDoubleSpinBox()
        self.volume_input.setRange(.001, 9999)
        self.volume_input.setDecimals(6)
        self.volume_input.setMinimum(.000001)
        self.volume_input.setValue(1)
        self.volume_unit_combo = QComboBox()
        for label, code in VOLUME_UNITS:
            self.volume_unit_combo.addItem(label, code)
        self.volume_unit_combo.setCurrentIndex(1)
        self.target_widget = QWidget()
        target_layout = QVBoxLayout(self.target_widget)
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_layout.addWidget(QLabel('Main target volume'))
        row = QHBoxLayout()
        row.addWidget(self.volume_input, 1)
        row.addWidget(self.volume_unit_combo)
        target_layout.addLayout(row)
        detail.addWidget(self.target_widget)

        self.advanced_checkbox = QCheckBox('Advanced · startup Prime')
        detail.addWidget(self.advanced_checkbox)
        self.prime_enabled_checkbox = QCheckBox('Prime before delivery')
        detail.addWidget(self.prime_enabled_checkbox)
        self.advanced_checkbox.toggled.connect(self._refresh_enabled_state)
        self.prime_details = QWidget()
        prime = QVBoxLayout(self.prime_details)
        prime.setContentsMargins(0, 0, 0, 0)
        self.prime_speed_combo = QComboBox()
        for label, code in [('Max (100%)', 'MAX'), ('High (50%)', 'HIGH'),
                            ('Medium (25%)', 'MEDIUM'), ('Low (10%)', 'LOW'), ('Min (5%)', 'MIN')]:
            self.prime_speed_combo.addItem(label, code)
        self.prime_speed_combo.setCurrentIndex(3)
        prime.addWidget(QLabel('Prime speed'))
        prime.addWidget(self.prime_speed_combo)
        self.prime_rate_preview = QLabel('Calculated Prime rate: —')
        self.prime_rate_preview.setWordWrap(True)
        prime.addWidget(self.prime_rate_preview)
        self.prime_volume_input = QDoubleSpinBox()
        self.prime_volume_input.setRange(.001, 9999)
        self.prime_volume_input.setDecimals(6)
        self.prime_volume_input.setMinimum(.000001)
        self.prime_volume_input.setValue(100)
        self.prime_volume_unit_combo = QComboBox()
        for label, code in VOLUME_UNITS:
            self.prime_volume_unit_combo.addItem(label, code)
        row = QHBoxLayout()
        prime.addWidget(QLabel('Prime volume'))
        row.addWidget(self.prime_volume_input, 1)
        row.addWidget(self.prime_volume_unit_combo)
        prime.addLayout(row)
        self.prime_note = QLabel('Prime uses the selected direction and volume, then switches to the main rate. Percentages refer to the diameter-dependent pump maximum.')
        self.prime_note.setObjectName('secondaryLabel')
        self.prime_note.setWordWrap(True)
        prime.addWidget(self.prime_note)
        detail.addWidget(self.prime_details)
        self.validation_label = QLabel()
        self.validation_label.setObjectName('warningLabel')
        self.validation_label.setWordWrap(True)
        detail.addWidget(self.validation_label)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName('deliverySummary')
        detail.addWidget(self.summary_label)
        self.readback_label = QLabel('No device read-back yet')
        self.readback_label.setWordWrap(True)
        self.readback_label.setObjectName('secondaryLabel')
        detail.addWidget(self.readback_label)
        self.device_details_checkbox = QCheckBox('Show device response')
        detail.addWidget(self.device_details_checkbox)
        self.last_response_label = QLabel('Last response: —')
        self.last_response_label.setWordWrap(True)
        self.last_response_label.setObjectName('secondaryLabel')
        self.last_response_label.hide()
        self.device_details_checkbox.toggled.connect(self.last_response_label.setVisible)
        detail.addWidget(self.last_response_label)
        detail.addStretch()

        # The complete single-pump action path stays in the same fixed footer.
        self.action_bar = QWidget()
        self.action_bar.setObjectName('pumpActionBar')
        bar = QVBoxLayout(self.action_bar)
        bar.setContentsMargins(8, 5, 8, 5)
        bar.setSpacing(5)
        self.footer_target_label = QLabel(f'Pump {self.index} | Address {address:02d}')
        self.footer_target_label.setObjectName('actionTarget')
        bar.addWidget(self.footer_target_label)
        self.footer_hint = QLabel()
        self.footer_hint.setWordWrap(True)
        self.footer_hint.setObjectName('secondaryLabel')
        bar.addWidget(self.footer_hint)
        self.apply_button = QPushButton('3 Apply and verify')
        self.apply_button.setObjectName('applyButton')
        self.apply_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.editor_run_button = QPushButton(f'4 Start pump {self.index}')
        self.editor_run_button.setObjectName('runButton')
        self.editor_run_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.editor_stop_button = QPushButton('Stop this pump')
        self.editor_stop_button.setObjectName('stopButton')
        actions = QHBoxLayout()
        actions.addWidget(self.apply_button, 1)
        actions.addWidget(self.editor_run_button, 1)
        bar.addLayout(actions)
        bar.addWidget(self.editor_stop_button)
        self.new_dose_button = QPushButton('Restart a full dose')
        self.new_dose_button.setObjectName('secondaryButton')
        self.new_dose_button.hide()
        bar.addWidget(self.new_dose_button)
        self.new_dose_button.clicked.connect(lambda:self.new_dose_requested.emit(self.address))

        self.edit_button.clicked.connect(lambda: self.edit_requested.emit(self.address))
        self.set_diameter_button.clicked.connect(self._request_set_diameter)
        self.apply_button.clicked.connect(self._request_apply)
        for button in (self.run_button, self.editor_run_button):
            button.clicked.connect(lambda: self.run_requested.emit(self.address))
        for button in (self.stop_button, self.editor_stop_button):
            button.clicked.connect(lambda: self.stop_requested.emit(self.address))
        self.active_checkbox.toggled.connect(self._on_active_toggled)
        self.diameter_input.valueChanged.connect(self._on_diameter_edited)
        self.diameter_input.lineEdit().textEdited.connect(self._on_diameter_text)
        self.diameter_input.editingFinished.connect(self._refresh_enabled_state)
        self.prime_enabled_checkbox.toggled.connect(self._on_prime_toggled)
        self.continuous_checkbox.toggled.connect(self._on_continuous_changed)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        for widget in (self.rate_input, self.volume_input):
            widget.valueChanged.connect(self.mark_settings_dirty)
            widget.lineEdit().textEdited.connect(self.mark_settings_dirty)
            widget.editingFinished.connect(self._refresh_enabled_state)
        self.prime_volume_input.valueChanged.connect(self._prime_settings_changed)
        self.prime_volume_input.lineEdit().textEdited.connect(self._prime_settings_changed)
        self.prime_volume_input.editingFinished.connect(self._refresh_enabled_state)
        def unit_notice(text):
            self.unit_notice.setText(text)
            self.unit_notice.show()
        preserve_quantity(self.rate_input, self.rate_unit_combo, FLOW_UL_MIN, unit_notice, lambda: self._internal_update)
        preserve_quantity(self.volume_input, self.volume_unit_combo, {'UL': 1, 'ML': 1000}, unit_notice, lambda: self._internal_update)
        preserve_quantity(self.prime_volume_input, self.prime_volume_unit_combo, {'UL': 1, 'ML': 1000}, unit_notice, lambda: self._internal_update)
        for widget in (self.rate_unit_combo,self.direction_combo,self.volume_unit_combo):
            widget.currentIndexChanged.connect(self.mark_settings_dirty)
        for widget in (self.prime_speed_combo,self.prime_volume_unit_combo):
            widget.currentIndexChanged.connect(self._prime_settings_changed)
        manager.changed.connect(self._refresh_summary)
        self._refresh_enabled_state()

    def open_diameter_editor(self):
        if self.workflow_managed:
            self.shared_setup_requested.emit()
            return
        self._diameter_editing = True
        self._refresh_enabled_state()
        self.diameter_input.setFocus()
        self.diameter_input.selectAll()

    def focus_next_step(self):
        if self.running or self.stop_pending:
            self.editor_stop_button.setFocus()
            return self.editor_stop_button
        if self.confirmed_diameter is None:
            self.open_diameter_editor()
            if self.station_managed:
                return None
            return self.diameter_input
        errors = self.input_errors()
        if errors:
            errors[0][0].setFocus()
            return errors[0][0]
        target = self.editor_run_button if not self.start_blocker() else self.apply_button
        target.setFocus()
        return target

    def _request_set_diameter(self):
        if not self.diameter_input.hasAcceptableInput():
            self.diameter_status.setText('Enter a complete inside diameter between 0.10 and 50.00 mm.')
            self.diameter_input.setFocus()
            return
        self.diameter_input.interpretText()
        try:
            format_diameter(self.diameter_input.value())
        except ValueError as exc:
            self.diameter_status.setText(str(exc))
            self.diameter_status.setObjectName('warningLabel')
            return
        self.set_diameter_requested.emit(self.address, self.diameter_input.value())

    def input_errors(self):
        fields = [(self.rate_input, 'Enter a complete main flow rate greater than zero.')]
        if not self.continuous_checkbox.isChecked():
            fields.append((self.volume_input, 'Enter a complete main target volume greater than zero.'))
        if self.prime_enabled_checkbox.isChecked() and not self.station_managed:
            fields.append((self.prime_volume_input, 'Enter a complete Prime volume greater than zero.'))
        return [(field, message) for field, message in fields if not field.hasAcceptableInput()]

    def validated_settings(self):
        errors = self.input_errors()
        if errors:
            self._refresh_validation()
            errors[0][0].setFocus()
            return None
        fields = [self.rate_input]
        if not self.continuous_checkbox.isChecked():
            fields.append(self.volume_input)
        if self.prime_enabled_checkbox.isChecked() and not self.station_managed:
            fields.append(self.prime_volume_input)
        for field in fields:
            field.interpretText()
        return self.current_settings()

    def _request_apply(self):
        settings = self.validated_settings()
        if settings is not None:
            self.apply_requested.emit(self.address, settings)

    def _on_active_toggled(self, checked):
        if checked:
            self._group_notice = ''
        self._refresh_summary()
        self.active_changed.emit(self.address, checked)
        self.state_changed.emit()

    def _on_diameter_text(self, *_):
        if not self._internal_update and self.confirmed_diameter is not None:
            self.invalidate_diameter('Diameter changed — SET & VERIFY again')
        if not self._internal_update:
            if not self.diameter_input.hasAcceptableInput():
                self.diameter_status.setText('Enter a complete inside diameter between 0.10 and 50.00 mm.')
                self.diameter_status.setObjectName('warningLabel')
            elif self.diameter_status.source_text == 'Enter a complete inside diameter between 0.10 and 50.00 mm.':
                self.diameter_status.setText('Diameter not verified')
                self.diameter_status.setObjectName('pendingLabel')
            self._refresh_enabled_state()

    def _on_diameter_edited(self, value):
        if not self._internal_update and self.confirmed_diameter is not None and not math.isclose(value, self.confirmed_diameter, rel_tol=0, abs_tol=1e-9):
            self.invalidate_diameter('Diameter changed — SET & VERIFY again')

    def _on_prime_toggled(self, *_):
        if self.station_managed:
            self.state_changed.emit();return
        if self.prime_enabled_checkbox.isChecked():
            self.advanced_checkbox.setChecked(True)
        self.mark_settings_dirty()

    def _prime_settings_changed(self,*_):
        if self.station_managed:
            self.state_changed.emit()
        else:
            self.mark_settings_dirty()

    def _mode_changed(self, *_):
        self.continuous_checkbox.setChecked(bool(self.mode_combo.currentData()))

    def _on_continuous_changed(self, checked):
        blocker = QSignalBlocker(self.mode_combo)
        self.mode_combo.setCurrentIndex(0 if checked else 1)
        del blocker
        self.mark_settings_dirty()

    def current_settings(self):
        return PumpSettings(
            self.rate_input.value(), str(self.rate_unit_combo.currentData()),
            str(self.direction_combo.currentData()), self.continuous_checkbox.isChecked(),
            self.volume_input.value(), str(self.volume_unit_combo.currentData()),
            False if self.station_managed else self.prime_enabled_checkbox.isChecked(),
            1.0 if self.station_managed else self.prime_volume_input.value(),
            'UL' if self.station_managed else str(self.prime_volume_unit_combo.currentData()),
            'LOW' if self.station_managed else str(self.prime_speed_combo.currentData()),
        )

    def is_active(self):
        return self.active_checkbox.isChecked()

    def set_active(self, checked):
        if not checked or self.active_checkbox.isEnabled():
            self.active_checkbox.setChecked(checked)

    def set_selected(self, selected):
        self.setProperty('selected', selected)
        self._repolish_status_widgets()

    def set_compact(self, compact):
        if self._compact != compact:
            self._compact = compact
            self._refresh_summary()

    def set_connection_available(self, available):
        self.connection_available = available
        self._refresh_enabled_state()

    def set_online(self, online, version=''):
        was_online = self.online
        self.online = online
        self.setProperty('online', online)
        self.status_label.setObjectName('onlineStatus' if online else 'offlineStatus')
        if online and version:
            self.version_label.setText(version)
            self.version_label.setToolTip(version)
        elif online and not was_online:
            self.version_label.setText('Device responding')
        if not online:
            self.last_status = None
            self.version_label.setText('No response')
            self.invalidate_diameter('Pump offline — diameter verification required')
        self._repolish_status_widgets()
        self._refresh_enabled_state()

    def set_busy(self, busy):
        self.busy = busy
        self._refresh_enabled_state()

    def set_stop_pending(self, *, reset=False):
        self.stop_pending = True
        self.stop_requires_reset = self.stop_requires_reset or reset
        self._refresh_enabled_state()

    def confirm_diameter(self, diameter_mm):
        self.confirmed_diameter = diameter_mm
        self._internal_update = True
        self.diameter_input.setValue(diameter_mm)
        self._internal_update = False
        self._diameter_editing = False
        self.diameter_status.setText(f'✓ Verified: {diameter_mm:.3f} mm')
        self.diameter_status.setObjectName('successLabel')
        self.setProperty('diameterVerified', True)
        self.settings_applied = False
        self.applied_snapshot = None
        self._repolish_status_widgets()
        self._refresh_enabled_state()

    def invalidate_diameter(self, message):
        if self.is_active():
            self._group_notice = 'Group selection cleared: verify the diameter and select this pump again.'
        self.confirmed_diameter = None
        self.settings_applied = False
        self.applied_snapshot = None
        self._diameter_editing = True
        self.active_checkbox.setChecked(False)
        self.diameter_status.setText(message)
        self.diameter_status.setObjectName('warningLabel')
        self.setProperty('diameterVerified', False)
        self._repolish_status_widgets()
        self._refresh_enabled_state()

    def _repolish_status_widgets(self):
        for widget in (self, self.status_label, self.diameter_status, self.step_banner, self.ready_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _update_prime_rate_preview(self):
        if self.confirmed_diameter is None:
            self.prime_rate_preview.setText('Calculated Prime rate: verify syringe diameter first')
            return
        from ne501.controller import prime_rate_ml_hr
        rate = prime_rate_ml_hr(self.confirmed_diameter, str(self.prime_speed_combo.currentData()))
        self.prime_rate_preview.setText(f'Calculated Prime rate: {rate:.4g} mL/hr  ({rate * 1000 / 60:.4g} µL/min)')

    def mark_settings_dirty(self, *_):
        if self._internal_update:
            return
        if self.settings_applied:
            self.last_response_label.setText('Last response: Settings changed — apply again')
        self.settings_applied = False
        self._refresh_enabled_state()

    def mark_settings_applied(self):
        self.settings_applied = True
        self.applied_snapshot = self.current_settings()
        self._refresh_enabled_state()

    def set_program_confirmation(self, confirmation):
        value = getattr(confirmation, 'steady_rate_value', None)
        unit = getattr(confirmation, 'steady_rate_unit', None)
        if value is not None and unit:
            self.readback_label.setText(f'Read-back: {value:g} {RATE_LABELS.get(unit, unit)}')

    def update_from_status(self, status):
        from ne501.protocol import STATUS_LABELS, ACTIVE_PROGRAM_STATUSES
        if status in STATUS_LABELS:
            self.last_status = status
            self.last_checked = datetime.now().strftime('%H:%M:%S')
            self.checked_at = time.monotonic()
            self.running = status in ACTIVE_PROGRAM_STATUSES
            if status == 'S' or status == 'P' and not self.stop_requires_reset:
                self.stop_pending = False
                self.stop_requires_reset = False
            if status == 'A':
                self.invalidate_diameter('Alarm — check pump, stop and refresh status')
                self.status_label.setObjectName('warningLabel')
        else:
            self.last_status = None
            self.settings_applied = False
        self.setProperty('running', self.running)
        self._repolish_status_widgets()
        self._refresh_enabled_state()

    def set_last_response(self, text):
        self.last_response_source = str(text)
        self.last_response_label.setText('Last response: ' + str(text))

    def mark_motion_uncertain(self):
        """RUN may have reached the device even when its reply was lost."""
        self.running = True
        self.set_online(False)
        self.setProperty('running', True)
        self._repolish_status_widgets()
        self._refresh_enabled_state()

    def configuration_blocker(self):
        if not self.online:
            return 'No response'
        if self.busy:
            return 'Sending command…'
        if self.stop_pending:
            return 'Stop pending — awaiting response'
        if self.last_status is None:
            return 'Refresh device status first'
        if self.last_status == 'A':
            return 'Alarm — check pump, stop and refresh status'
        if self.running:
            return 'Stop this pump before changing settings.'
        if self.confirmed_diameter is None:
            return 'Verify diameter first'
        errors = self.input_errors()
        return errors[0][1] if errors else ''

    def start_blocker(self):
        if self.workflow_managed and self.external_start_blocker:
            return self.external_start_blocker
        blocker = self.configuration_blocker()
        if blocker:
            return blocker
        return '' if self.settings_applied else 'Apply settings first'

    def readiness(self):
        if self.running and self.last_status is None:
            return 'Motion unconfirmed. Send STOP and confirm the device response.'
        if self.running and self.last_status is not None:
            return 'Reported: ' + self._motion()
        return self.start_blocker() or 'Ready'

    def next_instruction(self):
        if self.running and self.last_status is None:
            return 'Motion unconfirmed. Send STOP and confirm the device response.'
        if self.stop_pending:
            return 'Stop pending — awaiting response'
        if not self.connection_available and not self.online:
            return 'Next: select a COM port, then Connect and detect.'
        if not self.online:
            return 'Next: check the connection, then Rescan pumps.'
        if self.busy:
            return 'Waiting for the current operation to finish.'
        if self.stop_pending:
            return 'Stop pending — awaiting response'
        if self.last_status is None:
            return 'Next: Refresh status to confirm device state.'
        if self.last_status == 'A':
            return 'Alarm — check pump, stop and refresh status'
        if self.running:
            if self.last_status in ('T', 'U'):
                return 'Program active: it may resume automatically. Use Stop this pump to stop it.'
            return 'Running. Use Stop this pump to finish.'
        if self.confirmed_diameter is None:
            if self.station_managed and self.planned_diameter is not None:
                return 'Next: check syringe and tubing, then Write & verify.'
            return 'Next: enter the actual inside diameter, then Verify diameter.'
        if self.input_errors():
            return 'Next: complete the highlighted delivery fields.'
        if not self.settings_applied:
            if self.station_managed:return 'Next: write settings and read back on this console.'
            return 'Next: review delivery settings, then Apply and verify.'
        if self.station_managed:
            paused=self.last_status=='P' and self.station_phase==1 and self.station_context in ('formal','priming_chain')
            return 'Stopped with progress retained. Resume delivery here.' if paused else 'Settings verified. Start or stop this pump here.'
        return f'Next: Start pump {self.index}. Settings are verified.'

    def _motion(self):
        from ne501.protocol import STATUS_LABELS
        return STATUS_LABELS.get(self.last_status, 'Unknown')

    def _refresh_validation(self):
        errors = self.input_errors() if self.confirmed_diameter is not None else []
        bad_fields = {field for field, _ in errors}
        for field in (self.rate_input, self.volume_input, self.prime_volume_input):
            invalid = field in bad_fields
            if field.property('invalid') != invalid:
                field.setProperty('invalid', invalid)
                field.style().unpolish(field)
                field.style().polish(field)
        self.validation_label.setText('\n'.join(message for _, message in errors))
        self.validation_label.setVisible(bool(errors))

    def _refresh_summary(self):
        status_style = 'warningLabel' if self.stop_pending or self.running and self.last_status is None or self.online and self.last_status in (None, 'A') else 'onlineStatus' if self.online else 'offlineStatus'
        if self.status_label.objectName() != status_style:
            self.status_label.setObjectName(status_style)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
        if self.stop_pending:
            self.status_label.setText('● STOP NOT CONFIRMED' if self.last_status is None else 'Stop pending — awaiting response')
        elif self.last_status == 'A':
            self.status_label.setText('● Alarm')
        elif (self.online or self.running) and self.last_status is None:
            self.status_label.setText('● STATUS UNCONFIRMED')
        elif self.online and self.last_status == 'T':
            self.status_label.setText('● Timed wait · program active')
        elif self.online and self.last_status == 'U':
            self.status_label.setText('● Trigger wait · program active')
        elif self.running and self.online:
            self.status_label.setText('● Running')
        elif self.online and self.last_status == 'P':
            self.status_label.setText('● Stopped · progress retained')
        elif self.online:
            self.status_label.setText('● Ready' if not self.start_blocker() else '● Online')
        else:
            self.status_label.setText('● Offline')
        settings = self.applied_snapshot if self.running and self.applied_snapshot is not None else self.current_settings()
        direction = 'Infuse' if settings.direction == 'INF' else 'Withdraw'
        prefix = 'Setpoint' if self.settings_applied or self.running and self.applied_snapshot is not None else 'Draft'
        self.target_label.setText(f'{prefix}: {direction} · {settings.rate:g} {RATE_LABELS[settings.rate_unit]}')
        mode = 'Until stopped' if settings.continuous else f'Target: {settings.volume:g} {dict((c, l) for l, c in VOLUME_UNITS)[settings.volume_unit]}'
        if settings.prime_enabled:
            volume_unit = dict((c, l) for l, c in VOLUME_UNITS)[settings.prime_volume_unit]
            mode = f'Prime: {settings.prime_volume:g} {volume_unit} → {mode}'
        self.mode_label.setText(mode)
        prime = getattr(self, 'station_priming_settings', None)
        if (self.station_managed and prime is not None and self.last_status in ('I','W','X','P','T','U')
                and self.station_context in ('priming','priming_chain') and self.station_phase != 1):
            self.target_label.setText(f'Priming: {prime.rate:.5g} {RATE_LABELS[prime.rate_unit]}')
            self.mode_label.setText('Priming then formal delivery' if prime.follow_delivery else 'Priming only')
        self.target_label.setToolTip(self.mode_label.source_text)
        card_guidance = self.readiness()
        if self._compact and self._group_notice:
            card_guidance = 'Group cleared — verify diameter.'
        elif self._compact and self.input_errors():
            card_guidance = 'Complete the input fields.'
        self.ready_label.setText(card_guidance)
        self.ready_label.setVisible((not self.workflow_managed or not self._compact) and (not self.running or self.stop_pending or self.last_status is None))
        style = 'successLabel' if not self.start_blocker() else 'secondaryLabel' if self.running else 'pendingLabel'
        if self.ready_label.objectName() != style:
            self.ready_label.setObjectName(style)
            self.ready_label.style().unpolish(self.ready_label)
            self.ready_label.style().polish(self.ready_label)
        self.motion_label.setText('Stop pending — awaiting response' if self.stop_pending else 'Reported: ' + self._motion())
        group_hint = self._group_notice
        if not group_hint and self.online and self.confirmed_diameter is None:
            group_hint = 'Verify diameter to enable group selection.'
        self.group_hint_label.setText(group_hint)
        self.group_hint_label.setVisible(bool(group_hint) and not self._compact)
        self._refresh_age_label()
        self.motion_label.setVisible(not self._compact)
        self.mode_label.setVisible(not self._compact)
        self.last_check_label.setVisible(not self._compact)
        self.setToolTip(' | '.join(text for text in (self.next_instruction(),self._group_notice,mode,self.last_check_label.source_text) if text))
        draft = self.current_settings()
        summary_mode = 'Continuous' if draft.continuous else f'Target: {draft.volume:g} {dict((c, l) for l, c in VOLUME_UNITS)[draft.volume_unit]}'
        main = f'Summary: {direction} · {draft.rate:g} {RATE_LABELS[draft.rate_unit]} · {summary_mode}'
        if draft.prime_enabled:
            volume_unit = dict((c, l) for l, c in VOLUME_UNITS)[draft.prime_volume_unit]
            main = f'Prime: {draft.prime_volume:g} {volume_unit} → {main}'
        self.summary_label.setText(main)
        instruction = self.next_instruction()
        self.step_banner.setText(instruction)
        self.footer_hint.setText(self.readiness() if self.start_blocker() else 'Ready to start')
        if self.running:
            current = 3
        elif self.confirmed_diameter is None:
            current = 0
        elif self.input_errors():
            current = 1
        elif not self.settings_applied:
            current = 2
        else:
            current = 3
        for index, label in enumerate(self.step_labels):
            complete = (index == 0 and self.confirmed_diameter is not None) or (index in (1, 2) and self.settings_applied)
            state = 'complete' if complete else 'current' if index == current else 'pending'
            if label.property('state') != state:
                label.setProperty('state', state)
                label.style().unpolish(label)
                label.style().polish(label)

    def refresh_age(self):
        self._refresh_age_label()

    def _refresh_age_label(self):
        if self.last_checked is None:
            self.last_check_label.setText('No confirmed status yet')
        else:
            age = max(0, int(time.monotonic() - self.checked_at))
            self.last_check_label.setText(f'Last checked: {self.last_checked} ({age} s ago)')

    def update_shared_plan(self, used, diameter, blocker, pending=False):
        self.workflow_used = used
        self.external_plan_pending = pending
        changed = self.planned_diameter != diameter
        self.planned_diameter = diameter
        self.external_start_blocker = 'Finish entering a valid inside diameter.' if pending else blocker
        self._internal_update = True
        self.diameter_input.setValue(diameter or 0)
        self._internal_update = False
        if changed and self.confirmed_diameter is not None and (diameter is None or not math.isclose(diameter, self.confirmed_diameter, rel_tol=0, abs_tol=1e-9)):
            self.invalidate_diameter('Diameter changed — SET & VERIFY again')
        if self.station_managed and self.confirmed_diameter is None and diameter is not None:
            self.diameter_status.setText(f'Plan entered: {diameter:g} mm · device confirmation pending')
        self._refresh_enabled_state()

    def _refresh_enabled_state(self):
        can_set = self.online and self.last_status not in (None, 'A') and not self.running and not self.busy and not self.stop_pending
        ready = self.online and self.confirmed_diameter is not None
        configure = ready and self.last_status not in (None, 'A') and not self.running and not self.busy and not self.stop_pending
        self.diameter_fields.setVisible(not self.workflow_managed and (self._diameter_editing or not ready))
        self.change_diameter_button.setVisible(self.workflow_managed or ready and not self._diameter_editing)
        self.change_diameter_button.setEnabled(not self.busy and not self.running if self.workflow_managed else can_set)
        self.diameter_input.setEnabled(can_set)
        self.set_diameter_button.setEnabled(can_set and self.diameter_input.hasAcceptableInput())
        editable = not self.running and not self.busy and not self.stop_pending if self.workflow_managed else configure
        for widget in (self.rate_input, self.rate_unit_combo, self.direction_combo, self.mode_combo,
                       self.continuous_checkbox, self.prime_enabled_checkbox):
            widget.setEnabled(editable)
        self.target_widget.setVisible(not self.continuous_checkbox.isChecked())
        self.volume_input.setEnabled(editable and not self.continuous_checkbox.isChecked())
        self.volume_unit_combo.setEnabled(editable and not self.continuous_checkbox.isChecked())
        prime_on = self.prime_enabled_checkbox.isChecked()
        advanced = self.advanced_checkbox.isChecked()
        self.advanced_checkbox.setVisible(not self.station_managed)
        self.prime_enabled_checkbox.setVisible(advanced and not self.station_managed)
        self.prime_details.setVisible(prime_on and advanced and not self.station_managed)
        if not self.station_managed:
            for widget in (self.prime_speed_combo,self.prime_volume_input,self.prime_volume_unit_combo):
                widget.setEnabled(editable and prime_on)
        group_ready = self.online and self.planned_diameter is not None and not self.external_start_blocker.startswith("Select") if self.workflow_managed else ready
        self.active_checkbox.setEnabled(group_ready and not self.busy)
        writable = can_set and self.workflow_used and self.planned_diameter is not None and not self.external_plan_pending if self.workflow_managed else configure
        self.apply_button.setEnabled(writable and not self.input_errors())
        if self.workflow_managed:
            self.apply_button.setText("Write & verify")
            self.editor_run_button.setText('Start delivery' if self.station_managed else 'Review this pump')
            self.editor_run_button.setObjectName('runButton' if self.station_managed else 'secondaryButton')
        apply_style = 'secondaryButton' if self.settings_applied else 'applyButton'
        if self.apply_button.objectName() != apply_style:
            self.apply_button.setObjectName(apply_style)
            self.apply_button.style().unpolish(self.apply_button)
            self.apply_button.style().polish(self.apply_button)
        can_run = not self.start_blocker()
        self.run_button.setEnabled(can_run)
        self.editor_run_button.setEnabled(can_run)
        can_stop = self.connection_available or self.online
        self.stop_button.setEnabled(can_stop)
        self.editor_stop_button.setEnabled(can_stop)
        self.set_diameter_button.setStyleSheet('border: 2px solid #ffd166;' if can_set and not ready else '')
        self.apply_button.setStyleSheet('border: 2px solid #ffd166;' if configure and not self.settings_applied and not self.input_errors() else '')
        self.editor_run_button.setStyleSheet('border: 2px solid #ffd166;' if can_run else '')
        self._refresh_validation()
        self._update_prime_rate_preview()
        self._refresh_summary()
        self.state_changed.emit()
