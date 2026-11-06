from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import time
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QFormLayout, QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from .i18n import manager
from .i18n_widgets import GroupBox, Label as QLabel, Button as QPushButton, CheckBox as QCheckBox, ComboBox as QComboBox, SpinBox as QDoubleSpinBox

RATE_UNITS=[("µL/min","UM"),("mL/min","MM"),("µL/hr","UH"),("mL/hr","MH")]
VOLUME_UNITS=[("µL","UL"),("mL","ML")]
RATE_LABELS=dict((code,label) for label,code in RATE_UNITS)

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
    set_diameter_requested=Signal(int,float)
    apply_requested=Signal(int,object)
    run_requested=Signal(int)
    stop_requested=Signal(int)
    active_changed=Signal(int,bool)
    edit_requested=Signal(int)
    state_changed=Signal()

    def __init__(self,address:int,parent=None,index=None):
        super().__init__('',parent)
        self.address=address
        self.index=index if index is not None else address+1
        self.confirmed_diameter=None
        self.settings_applied=False
        self.applied_snapshot=None
        self.connection_available=False
        self.online=self.running=self.busy=False
        self._internal_update=False
        self.last_status=None
        self.last_checked=None
        self.checked_at=0.0
        self.last_response_source=''
        self.stop_pending=False
        self.setTitle(f'Pump {self.index} | Address {address:02d}')
        self.setObjectName('pumpPanel')
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        for key in ('selected','running','online','active','diameterVerified'): self.setProperty(key,False)
        self.status_label=QLabel('● Offline');self.status_label.setObjectName('offlineStatus')
        self.version_label=QLabel('Not scanned');self.version_label.setObjectName('secondaryLabel')
        self.version_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        top=QHBoxLayout();top.addWidget(self.status_label);top.addStretch();self.version_label.hide()
        self.motion_label=QLabel('Reported: Unknown');self.motion_label.setWordWrap(True)
        self.ready_label=QLabel('Verify diameter first');self.ready_label.setWordWrap(True)
        self.target_label=QLabel();self.target_label.setWordWrap(True)
        self.mode_label=QLabel()
        self.last_check_label=QLabel('No confirmed status yet');self.last_check_label.setObjectName('secondaryLabel')
        self.active_checkbox=QCheckBox('Group')
        self.active_checkbox.setToolTip('Include this pump in group actions.');top.addWidget(self.active_checkbox)
        self.edit_button=QPushButton('Edit')
        self.run_button=QPushButton('Start');self.run_button.setObjectName('runButton')
        self.stop_button=QPushButton('Stop');self.stop_button.setObjectName('stopButton')
        self.stop_button.setToolTip('Stop available after connecting; verify the response before assuming the pump stopped.')
        actions=QHBoxLayout()
        for button in (self.edit_button,self.run_button,self.stop_button): actions.addWidget(button)
        card=QVBoxLayout(self);card.setSpacing(3);card.setContentsMargins(8,12,8,6)
        card.addLayout(top);card.addWidget(self.motion_label);card.addWidget(self.target_label)
        card.addWidget(self.mode_label);self.ready_label.hide();card.addWidget(self.last_check_label)
        card.addLayout(actions)

        self.editor=QWidget()
        detail=QVBoxLayout(self.editor);detail.setContentsMargins(10,8,10,8);detail.setSpacing(7)
        self.editor_title=QLabel(f'Pump {self.index} settings');self.editor_title.setStyleSheet('font-size: 12pt; font-weight: 700;')
        detail.addWidget(self.editor_title)
        self.step_banner=QLabel('1  Verify syringe diameter');self.step_banner.setObjectName('diameterRequiredBanner');self.step_banner.setWordWrap(True)
        detail.addWidget(self.step_banner)
        self.diameter_input=QDoubleSpinBox();self.diameter_input.setRange(.1,50);self.diameter_input.setDecimals(2)
        self.diameter_input.setSingleStep(.01);self.diameter_input.setValue(10);self.diameter_input.setSuffix(' mm')
        self.set_diameter_button=QPushButton('Set and verify');self.set_diameter_button.setObjectName('diameterButton')
        row=QHBoxLayout();row.addWidget(self.diameter_input,1);row.addWidget(self.set_diameter_button);detail.addLayout(row)
        self.diameter_status=QLabel('Diameter not verified');self.diameter_status.setObjectName('warningLabel');self.diameter_status.setWordWrap(True)
        detail.addWidget(self.diameter_status)
        detail.addWidget(QLabel('2  Delivery settings'))
        self.rate_input=QDoubleSpinBox();self.rate_input.setDecimals(4);self.rate_input.setRange(.0001,9999);self.rate_input.setValue(1)
        self.rate_unit_combo=QComboBox()
        for label,code in RATE_UNITS:self.rate_unit_combo.addItem(label,code)
        self.rate_unit_combo.setCurrentIndex(3)
        rate=QWidget();layout=QHBoxLayout(rate);layout.setContentsMargins(0,0,0,0);layout.addWidget(self.rate_input,1);layout.addWidget(self.rate_unit_combo)
        self.direction_combo=QComboBox();self.direction_combo.addItem('Infuse','INF');self.direction_combo.addItem('Withdraw','WDR')
        self.mode_combo=QComboBox();self.mode_combo.addItem('Continuous',True);self.mode_combo.addItem('Target volume',False)
        self.continuous_checkbox=QCheckBox('Continuous');self.continuous_checkbox.setChecked(True);self.continuous_checkbox.hide()
        form=QFormLayout();form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for label,field in [('Rate',rate),('Direction',self.direction_combo),('Mode',self.mode_combo)]:form.addRow(QLabel(label),field)
        detail.addLayout(form)
        self.volume_input=QDoubleSpinBox();self.volume_input.setRange(.001,9999);self.volume_input.setDecimals(3);self.volume_input.setValue(1)
        self.volume_unit_combo=QComboBox()
        for label,code in VOLUME_UNITS:self.volume_unit_combo.addItem(label,code)
        self.volume_unit_combo.setCurrentIndex(1)
        self.target_widget=QWidget();row=QHBoxLayout(self.target_widget);row.setContentsMargins(0,0,0,0)
        row.addWidget(QLabel('Volume'));row.addWidget(self.volume_input,1);row.addWidget(self.volume_unit_combo)
        detail.addWidget(self.target_widget)
        self.prime_enabled_checkbox=QCheckBox('Prime before delivery');detail.addWidget(self.prime_enabled_checkbox)
        self.prime_details=QWidget();prime=QVBoxLayout(self.prime_details);prime.setContentsMargins(0,0,0,0)
        self.prime_speed_combo=QComboBox()
        for label,code in [('Max (100%)','MAX'),('High (50%)','HIGH'),('Medium (25%)','MEDIUM'),('Low (10%)','LOW'),('Min (5%)','MIN')]:self.prime_speed_combo.addItem(label,code)
        self.prime_speed_combo.setCurrentIndex(3)
        prime.addWidget(QLabel('Prime speed'));prime.addWidget(self.prime_speed_combo)
        self.prime_rate_preview=QLabel('Calculated Prime rate: —');self.prime_rate_preview.setWordWrap(True);prime.addWidget(self.prime_rate_preview)
        self.prime_volume_input=QDoubleSpinBox();self.prime_volume_input.setRange(.001,9999);self.prime_volume_input.setDecimals(3);self.prime_volume_input.setValue(100)
        self.prime_volume_unit_combo=QComboBox()
        for label,code in VOLUME_UNITS:self.prime_volume_unit_combo.addItem(label,code)
        row=QHBoxLayout();row.addWidget(QLabel('Prime volume'));row.addWidget(self.prime_volume_input,1);row.addWidget(self.prime_volume_unit_combo);prime.addLayout(row)
        self.prime_note=QLabel('Prime uses the selected direction and volume, then switches to the main rate. Percentages refer to the diameter-dependent pump maximum.')
        self.prime_note.setWordWrap(True);self.prime_note.setObjectName('secondaryLabel');prime.addWidget(self.prime_note);detail.addWidget(self.prime_details)
        self.summary_label=QLabel();self.summary_label.setWordWrap(True);detail.addWidget(self.summary_label)
        self.apply_button=QPushButton('Apply and verify');self.apply_button.setObjectName('applyButton');detail.addWidget(self.apply_button)
        self.readback_label=QLabel('No device read-back yet');self.readback_label.setWordWrap(True);detail.addWidget(self.readback_label)
        self.last_response_label=QLabel('Last response: —');self.last_response_label.setWordWrap(True);self.last_response_label.setObjectName('secondaryLabel');detail.addWidget(self.last_response_label)
        detail.addStretch()

        self.edit_button.clicked.connect(lambda:self.edit_requested.emit(self.address))
        self.set_diameter_button.clicked.connect(self._request_set_diameter)
        self.apply_button.clicked.connect(self._request_apply)
        self.run_button.clicked.connect(lambda:self.run_requested.emit(self.address))
        self.stop_button.clicked.connect(lambda:self.stop_requested.emit(self.address))
        self.active_checkbox.toggled.connect(self._on_active_toggled)
        self.diameter_input.valueChanged.connect(self._on_diameter_edited)
        self.diameter_input.lineEdit().textEdited.connect(self._on_diameter_text)
        self.prime_enabled_checkbox.toggled.connect(self._on_prime_toggled)
        self.continuous_checkbox.toggled.connect(self._on_continuous_changed)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        for widget in (self.rate_input,self.prime_volume_input,self.volume_input):
            widget.valueChanged.connect(self.mark_settings_dirty)
            widget.lineEdit().textEdited.connect(self.mark_settings_dirty)
        for widget in (self.prime_speed_combo,self.prime_volume_unit_combo,self.rate_unit_combo,self.direction_combo,self.volume_unit_combo):
            widget.currentIndexChanged.connect(self.mark_settings_dirty)
        manager.changed.connect(self._refresh_summary)
        self._refresh_enabled_state()

    def _request_set_diameter(self):
        if not self.diameter_input.hasAcceptableInput():return
        self.diameter_input.interpretText()
        self.set_diameter_requested.emit(self.address,self.diameter_input.value())
    def _request_apply(self):
        for spin in (self.rate_input,self.volume_input,self.prime_volume_input):
            if not spin.hasAcceptableInput():return
            spin.interpretText()
        self.apply_requested.emit(self.address,self.current_settings())
    def _on_active_toggled(self,checked):
        self.active_changed.emit(self.address,checked);self.state_changed.emit()
    def _on_diameter_text(self,*_):
        if not self._internal_update and self.confirmed_diameter is not None:self.invalidate_diameter('Diameter changed — SET & VERIFY again')
    def _on_diameter_edited(self,value):
        if not self._internal_update and self.confirmed_diameter is not None and abs(value-self.confirmed_diameter)>.005:self.invalidate_diameter('Diameter changed — SET & VERIFY again')
    def _on_prime_toggled(self,*_):
        self.mark_settings_dirty()
    def _mode_changed(self,*_):
        self.continuous_checkbox.setChecked(bool(self.mode_combo.currentData()))
    def _on_continuous_changed(self,checked):
        blocker=QSignalBlocker(self.mode_combo);self.mode_combo.setCurrentIndex(0 if checked else 1);del blocker
        self.mark_settings_dirty()
    def current_settings(self):
        return PumpSettings(self.rate_input.value(),str(self.rate_unit_combo.currentData()),str(self.direction_combo.currentData()),
            self.continuous_checkbox.isChecked(),self.volume_input.value(),str(self.volume_unit_combo.currentData()),
            self.prime_enabled_checkbox.isChecked(),self.prime_volume_input.value(),str(self.prime_volume_unit_combo.currentData()),
            str(self.prime_speed_combo.currentData()))
    def is_active(self):return self.active_checkbox.isChecked()
    def set_active(self,checked):
        if not checked or self.active_checkbox.isEnabled():self.active_checkbox.setChecked(checked)
    def set_selected(self,selected):
        self.setProperty('selected',selected);self._repolish_status_widgets()
    def set_connection_available(self,available):
        self.connection_available=available;self._refresh_enabled_state()
    def set_online(self,online,version=''):
        self.online=online;self.setProperty('online',online)
        self.status_label.setText('● Online' if online else '● Offline')
        self.status_label.setObjectName('onlineStatus' if online else 'offlineStatus')
        if online and version:
            self.version_label.setText(version);self.version_label.setToolTip(version)
        if not online:
            self.last_status=None;self.stop_pending=False;self.version_label.setText('No response')
            self.invalidate_diameter('Pump offline — diameter verification required')
        self._repolish_status_widgets();self._refresh_enabled_state()
    def set_busy(self,busy):
        self.busy=busy;self._refresh_enabled_state()
    def set_stop_pending(self):
        self.stop_pending=True;self._refresh_summary()
    def confirm_diameter(self,diameter_mm):
        self.confirmed_diameter=diameter_mm;self._internal_update=True
        self.diameter_input.setValue(diameter_mm);self._internal_update=False
        self.diameter_status.setText(f'✓ Verified: {diameter_mm:.2f} mm');self.diameter_status.setObjectName('successLabel')
        self.setProperty('diameterVerified',True);self.settings_applied=False;self.applied_snapshot=None
        self.step_banner.setText('2  Delivery settings');self.step_banner.setObjectName('diameterReadyBanner')
        self._repolish_status_widgets();self._refresh_enabled_state()
    def invalidate_diameter(self,message):
        self.confirmed_diameter=None;self.settings_applied=False;self.applied_snapshot=None
        self.active_checkbox.setChecked(False)
        self.diameter_status.setText(message);self.diameter_status.setObjectName('warningLabel')
        self.setProperty('diameterVerified',False);self.step_banner.setText('1  Verify syringe diameter')
        self.step_banner.setObjectName('diameterRequiredBanner');self._repolish_status_widgets();self._refresh_enabled_state()
    def _repolish_status_widgets(self):
        for widget in (self,self.status_label,self.diameter_status,self.step_banner,self.ready_label):
            widget.style().unpolish(widget);widget.style().polish(widget)
    def _update_prime_rate_preview(self):
        if self.confirmed_diameter is None:
            self.prime_rate_preview.setText('Calculated Prime rate: verify syringe diameter first');return
        from ne501.controller import prime_rate_ml_hr
        rate=prime_rate_ml_hr(self.confirmed_diameter,str(self.prime_speed_combo.currentData()))
        self.prime_rate_preview.setText(f'Calculated Prime rate: {rate:.4g} mL/hr  ({rate*1000/60:.4g} µL/min)')
    def mark_settings_dirty(self,*_):
        if self._internal_update:return
        if self.settings_applied:self.last_response_label.setText('Last response: Settings changed — apply again')
        self.settings_applied=False;self._refresh_enabled_state()
    def mark_settings_applied(self):
        self.settings_applied=True;self.applied_snapshot=self.current_settings();self._refresh_enabled_state()
    def set_program_confirmation(self,confirmation):
        value=getattr(confirmation,'steady_rate_value',None);unit=getattr(confirmation,'steady_rate_unit',None)
        if value is not None and unit:self.readback_label.setText(f'Read-back: {value:g} {RATE_LABELS.get(unit,unit)}')
    def update_from_status(self,status):
        from ne501.protocol import STATUS_LABELS
        if status in STATUS_LABELS:
            self.last_status=status;self.last_checked=datetime.now().strftime('%H:%M:%S');self.checked_at=time.monotonic()
            self.running=status in {'I','W','X'}
            if status=='S':self.stop_pending=False
        else:self.last_status=None
        self.setProperty('running',self.running);self._refresh_enabled_state()
    def set_last_response(self,text):
        self.last_response_source=str(text);self.last_response_label.setText('Last response: '+str(text))
    def readiness(self):
        if not self.online:return 'No response'
        if self.busy:return 'Sending command…'
        if self.confirmed_diameter is None:return 'Verify diameter first'
        if self.running:return 'Reported: '+self._motion()
        if not self.settings_applied:return 'Apply settings first'
        return 'Ready'
    def _motion(self):
        from ne501.protocol import STATUS_LABELS
        return STATUS_LABELS.get(self.last_status,'Unknown')
    def _refresh_summary(self):
        settings=self.applied_snapshot if self.running and self.applied_snapshot is not None else self.current_settings()
        direction='Infuse' if settings.direction=='INF' else 'Withdraw'
        prefix='Applied' if self.settings_applied or self.running and self.applied_snapshot is not None else 'Draft'
        self.target_label.setText(f'{prefix}: {direction} · {settings.rate:g} {RATE_LABELS[settings.rate_unit]}')
        self.mode_label.setText('Until stopped' if settings.continuous else f'Target: {settings.volume:g} {dict((c,l) for l,c in VOLUME_UNITS)[settings.volume_unit]}')
        self.ready_label.setText(self.readiness())
        self.ready_label.setObjectName('successLabel' if self.readiness()=='Ready' else 'secondaryLabel' if self.running else 'warningLabel')
        self.motion_label.setText('Stop pending — awaiting response' if self.stop_pending else self.readiness() if not self.running and self.readiness()!='Ready' else 'Reported: '+self._motion())
        if self.last_checked is None:self.last_check_label.setText('No confirmed status yet')
        else:self.last_check_label.setText(('Status needs refresh | ' if time.monotonic()-self.checked_at>5 else 'Last checked: ')+self.last_checked)
        self.summary_label.setText(f'Summary: {direction} · {self.rate_input.value():g} {RATE_LABELS[str(self.rate_unit_combo.currentData())]} · '+('Continuous' if self.continuous_checkbox.isChecked() else f'Target: {self.volume_input.value():g} {self.volume_unit_combo.currentText()}'))
    def refresh_age(self):self._refresh_summary()
    def _refresh_enabled_state(self):
        can_set=self.online and not self.running and not self.busy
        ready=self.online and self.confirmed_diameter is not None
        configure=ready and not self.running and not self.busy
        self.diameter_input.setEnabled(can_set);self.set_diameter_button.setEnabled(can_set)
        for widget in (self.rate_input,self.rate_unit_combo,self.direction_combo,self.mode_combo,self.continuous_checkbox,self.prime_enabled_checkbox):widget.setEnabled(configure)
        self.volume_input.setEnabled(configure and not self.continuous_checkbox.isChecked())
        self.volume_unit_combo.setEnabled(configure and not self.continuous_checkbox.isChecked())
        self.target_widget.setVisible(not self.continuous_checkbox.isChecked())
        prime_on=self.prime_enabled_checkbox.isChecked();self.prime_details.setVisible(prime_on)
        for widget in (self.prime_speed_combo,self.prime_volume_input,self.prime_volume_unit_combo):widget.setEnabled(configure and prime_on)
        self.active_checkbox.setEnabled(ready and not self.busy)
        self.apply_button.setEnabled(configure)
        self.run_button.setEnabled(ready and self.settings_applied and not self.running and not self.busy)
        self.stop_button.setEnabled(self.connection_available or self.online)
        self.set_diameter_button.setStyleSheet('border: 2px solid #ffd166;' if can_set and not ready else '')
        self.apply_button.setStyleSheet('border: 2px solid #ffd166;' if configure and not self.settings_applied else '')
        self._update_prime_rate_preview();self._refresh_summary();self.state_changed.emit()
