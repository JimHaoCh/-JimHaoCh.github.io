from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

RATE_UNITS = [("µL/min", "UM"), ("mL/min", "MM"), ("µL/hr", "UH"), ("mL/hr", "MH")]
VOLUME_UNITS = [("µL", "UL"), ("mL", "ML")]


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


class PumpPanel(QGroupBox):
    set_diameter_requested = Signal(int, float)
    apply_requested = Signal(int, object)
    run_requested = Signal(int)
    stop_requested = Signal(int)
    active_changed = Signal(int, bool)

    def __init__(self, address: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.address = address
        self.confirmed_diameter: Optional[float] = None
        self.settings_applied = False
        self.online = False
        self.running = False
        self.busy = False
        self._internal_update = False

        self.setTitle(f"Pump {address:02d}")
        self.setObjectName("pumpPanel")
        self.setMinimumWidth(500)
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setProperty("active", False)
        self.setProperty("running", False)
        self.setProperty("online", False)
        self.setProperty("diameterVerified", False)

        self.status_label = QLabel("● Offline")
        self.status_label.setObjectName("offlineStatus")
        self.version_label = QLabel("Not scanned")
        self.version_label.setWordWrap(True)
        title_row = QHBoxLayout()
        title_row.addWidget(self.status_label)
        title_row.addStretch()
        title_row.addWidget(self.version_label)

        # Prominent mandatory-step banner. All flow controls stay locked until
        # the diameter has been written to and read back from the pump.
        self.step_banner = QLabel(
            "STEP 1 REQUIRED  •  Set and verify the syringe inside diameter before configuring Prime or Flow."
        )
        self.step_banner.setWordWrap(True)
        self.step_banner.setObjectName("diameterRequiredBanner")

        self.diameter_input = QDoubleSpinBox()
        self.diameter_input.setRange(0.10, 50.00)
        self.diameter_input.setDecimals(2)
        self.diameter_input.setSingleStep(0.01)
        self.diameter_input.setValue(10.00)
        self.diameter_input.setSuffix(" mm")
        self.set_diameter_button = QPushButton("SET & VERIFY DIAMETER")
        self.set_diameter_button.setObjectName("diameterButton")
        self.set_diameter_button.setEnabled(False)
        self.diameter_status = QLabel("Diameter not verified")
        self.diameter_status.setObjectName("warningLabel")
        diameter_row = QHBoxLayout()
        diameter_row.addWidget(self.diameter_input, 1)
        diameter_row.addWidget(self.set_diameter_button)

        self.prime_enabled_checkbox = QCheckBox("Prime before steady flow")
        self.prime_enabled_checkbox.setChecked(False)
        self.prime_speed_combo = QComboBox()
        for label, code in [
            ("Max (100%)", "MAX"),
            ("High (50%)", "HIGH"),
            ("Medium (25%)", "MEDIUM"),
            ("Low (10%)", "LOW"),
            ("Min (5%)", "MIN"),
        ]:
            self.prime_speed_combo.addItem(label, code)
        # A gentler microfluidic default than the previous full-speed Prime.
        self.prime_speed_combo.setCurrentIndex(3)  # Low (10%)
        self.prime_rate_preview = QLabel("Calculated Prime rate: —")
        self.prime_rate_preview.setObjectName("secondaryLabel")
        self.prime_volume_input = QDoubleSpinBox()
        self.prime_volume_input.setRange(0.001, 9999.0)
        self.prime_volume_input.setDecimals(3)
        self.prime_volume_input.setValue(100.0)
        self.prime_volume_unit_combo = QComboBox()
        for label, code in VOLUME_UNITS:
            self.prime_volume_unit_combo.addItem(label, code)
        self.prime_volume_unit_combo.setCurrentIndex(0)
        prime_widget = QWidget()
        prime_layout = QHBoxLayout(prime_widget)
        prime_layout.setContentsMargins(0, 0, 0, 0)
        prime_layout.addWidget(self.prime_volume_input, 1)
        prime_layout.addWidget(self.prime_volume_unit_combo)
        self.prime_note = QLabel(
            "Prime speed is automatically converted from the verified syringe diameter. "
            "The five levels are software presets relative to the pump maximum, then the program "
            "switches to steady flow after the requested Prime volume."
        )
        self.prime_note.setWordWrap(True)
        self.prime_note.setObjectName("secondaryLabel")

        self.active_checkbox = QCheckBox("Active (include in group actions)")
        self.active_checkbox.setEnabled(False)
        active_font = QFont(self.active_checkbox.font())
        active_font.setBold(True)
        self.active_checkbox.setFont(active_font)

        self.rate_input = QDoubleSpinBox()
        self.rate_input.setRange(0.0001, 9999.0)
        self.rate_input.setDecimals(4)
        self.rate_input.setValue(1.0)
        self.rate_unit_combo = QComboBox()
        for label, code in RATE_UNITS:
            self.rate_unit_combo.addItem(label, code)
        self.rate_unit_combo.setCurrentIndex(3)
        rate_widget = QWidget()
        rate_layout = QHBoxLayout(rate_widget)
        rate_layout.setContentsMargins(0, 0, 0, 0)
        rate_layout.addWidget(self.rate_input, 1)
        rate_layout.addWidget(self.rate_unit_combo)

        self.direction_combo = QComboBox()
        self.direction_combo.addItem("Infuse", "INF")
        self.direction_combo.addItem("Withdraw", "WDR")
        self.continuous_checkbox = QCheckBox("Continuous steady flow")
        self.continuous_checkbox.setChecked(True)
        self.volume_input = QDoubleSpinBox()
        self.volume_input.setRange(0.001, 9999.0)
        self.volume_input.setDecimals(3)
        self.volume_input.setValue(1.0)
        self.volume_unit_combo = QComboBox()
        for label, code in VOLUME_UNITS:
            self.volume_unit_combo.addItem(label, code)
        self.volume_unit_combo.setCurrentIndex(1)
        volume_widget = QWidget()
        volume_layout = QHBoxLayout(volume_widget)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.addWidget(self.volume_input, 1)
        volume_layout.addWidget(self.volume_unit_combo)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow("Syringe inside diameter", diameter_row)
        form.addRow("", self.diameter_status)
        form.addRow("", self.prime_enabled_checkbox)
        form.addRow("Prime speed", self.prime_speed_combo)
        form.addRow("", self.prime_rate_preview)
        form.addRow("Prime volume", prime_widget)
        form.addRow("", self.prime_note)
        form.addRow("Steady rate", rate_widget)
        form.addRow("Direction", self.direction_combo)
        form.addRow("Mode", self.continuous_checkbox)
        form.addRow("Steady target volume", volume_widget)

        self.apply_button = QPushButton("APPLY & VERIFY")
        self.apply_button.setObjectName("applyButton")
        self.run_button = QPushButton("RUN")
        self.run_button.setObjectName("runButton")
        self.stop_button = QPushButton("STOP")
        self.stop_button.setObjectName("stopButton")
        self.apply_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        buttons = QGridLayout()
        buttons.addWidget(self.apply_button, 0, 0)
        buttons.addWidget(self.run_button, 0, 1)
        buttons.addWidget(self.stop_button, 0, 2)

        self.last_response_label = QLabel("Last response: —")
        self.last_response_label.setWordWrap(True)
        self.last_response_label.setObjectName("secondaryLabel")

        layout = QVBoxLayout(self)
        layout.addLayout(title_row)
        layout.addWidget(self.step_banner)
        layout.addLayout(form)
        layout.addWidget(self.active_checkbox)
        layout.addLayout(buttons)
        layout.addWidget(self.last_response_label)

        self.set_diameter_button.clicked.connect(self._request_set_diameter)
        self.apply_button.clicked.connect(self._request_apply)
        self.run_button.clicked.connect(lambda: self.run_requested.emit(self.address))
        self.stop_button.clicked.connect(lambda: self.stop_requested.emit(self.address))
        self.active_checkbox.toggled.connect(self._on_active_toggled)
        self.diameter_input.valueChanged.connect(self._on_diameter_edited)
        self.prime_enabled_checkbox.toggled.connect(self._on_prime_toggled)
        for widget_signal in [
            self.prime_speed_combo.currentIndexChanged,
            self.prime_volume_input.valueChanged, self.prime_volume_unit_combo.currentIndexChanged,
            self.rate_input.valueChanged, self.rate_unit_combo.currentIndexChanged,
            self.direction_combo.currentIndexChanged, self.volume_input.valueChanged,
            self.volume_unit_combo.currentIndexChanged,
        ]:
            widget_signal.connect(self.mark_settings_dirty)
        self.continuous_checkbox.toggled.connect(self._on_continuous_changed)
        self._refresh_enabled_state()

    def _request_set_diameter(self) -> None:
        self.set_diameter_requested.emit(self.address, self.diameter_input.value())

    def _request_apply(self) -> None:
        self.apply_requested.emit(self.address, self.current_settings())

    def _on_active_toggled(self, checked: bool) -> None:
        self.setProperty("active", checked)
        self.style().unpolish(self)
        self.style().polish(self)
        self.active_changed.emit(self.address, checked)

    def _on_diameter_edited(self, value: float) -> None:
        if self._internal_update:
            return
        if self.confirmed_diameter is not None and abs(value - self.confirmed_diameter) > 0.005:
            self.invalidate_diameter("Diameter changed — SET & VERIFY again")

    def _on_prime_toggled(self, checked: bool) -> None:
        self.mark_settings_dirty()
        self._refresh_enabled_state()

    def _on_continuous_changed(self, checked: bool) -> None:
        self.mark_settings_dirty()
        self._refresh_enabled_state()

    def current_settings(self) -> PumpSettings:
        return PumpSettings(
            rate=self.rate_input.value(), rate_unit=str(self.rate_unit_combo.currentData()),
            direction=str(self.direction_combo.currentData()),
            continuous=self.continuous_checkbox.isChecked(), volume=self.volume_input.value(),
            volume_unit=str(self.volume_unit_combo.currentData()),
            prime_enabled=self.prime_enabled_checkbox.isChecked(),
            prime_volume=self.prime_volume_input.value(),
            prime_volume_unit=str(self.prime_volume_unit_combo.currentData()),
            prime_speed_level=str(self.prime_speed_combo.currentData()),
        )

    def is_active(self) -> bool:
        return self.active_checkbox.isChecked()

    def set_active(self, checked: bool) -> None:
        if checked and not self.active_checkbox.isEnabled():
            return
        self.active_checkbox.setChecked(checked)

    def set_online(self, online: bool, version: str = "") -> None:
        self.online = online
        self.setProperty("online", online)
        if online:
            self.status_label.setText("● Online")
            self.status_label.setObjectName("onlineStatus")
            if version:
                self.version_label.setText(version)
        else:
            self.status_label.setText("● Offline")
            self.status_label.setObjectName("offlineStatus")
            self.version_label.setText("No response")
            self.invalidate_diameter("Pump offline — diameter verification required")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self._refresh_enabled_state()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self._refresh_enabled_state()

    def confirm_diameter(self, diameter_mm: float) -> None:
        self.confirmed_diameter = diameter_mm
        self._internal_update = True
        self.diameter_input.setValue(diameter_mm)
        self._internal_update = False
        self.diameter_status.setText(f"✓ Verified: {diameter_mm:.2f} mm")
        self.diameter_status.setObjectName("successLabel")
        self.step_banner.setText(
            "✓ STEP 1 COMPLETE  •  Diameter verified. Configure Prime and steady-flow settings, then APPLY & VERIFY."
        )
        self.step_banner.setObjectName("diameterReadyBanner")
        self.setProperty("diameterVerified", True)
        self.settings_applied = False
        self._update_prime_rate_preview()
        self._repolish_status_widgets()
        self._refresh_enabled_state()

    def invalidate_diameter(self, message: str) -> None:
        self.confirmed_diameter = None
        self.settings_applied = False
        self.active_checkbox.setChecked(False)
        self.active_checkbox.setEnabled(False)
        self.diameter_status.setText(message)
        self.diameter_status.setObjectName("warningLabel")
        self.step_banner.setText(
            "STEP 1 REQUIRED  •  Set and verify the syringe inside diameter before configuring Prime or Flow."
        )
        self.step_banner.setObjectName("diameterRequiredBanner")
        self.setProperty("diameterVerified", False)
        self._update_prime_rate_preview()
        self._repolish_status_widgets()
        self._refresh_enabled_state()

    def _repolish_status_widgets(self) -> None:
        for widget in (self.diameter_status, self.step_banner, self):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _update_prime_rate_preview(self) -> None:
        if self.confirmed_diameter is None:
            self.prime_rate_preview.setText("Calculated Prime rate: verify syringe diameter first")
            return
        try:
            from ne501.controller import prime_rate_ml_hr
            level = str(self.prime_speed_combo.currentData())
            rate_ml_hr = prime_rate_ml_hr(self.confirmed_diameter, level)
            rate_ul_min = rate_ml_hr * 1000.0 / 60.0
            self.prime_rate_preview.setText(
                f"Calculated Prime rate: {rate_ml_hr:.4g} mL/hr  ({rate_ul_min:.4g} µL/min)"
            )
        except Exception:
            self.prime_rate_preview.setText("Calculated Prime rate: —")

    def mark_settings_dirty(self, *_args) -> None:
        self._update_prime_rate_preview()
        if self.settings_applied:
            self.settings_applied = False
            self.last_response_label.setText("Last response: settings changed — APPLY & VERIFY again")
        self._refresh_enabled_state()

    def mark_settings_applied(self) -> None:
        self.settings_applied = True
        self._refresh_enabled_state()

    def update_from_status(self, status: Optional[str]) -> None:
        self.running = status in {"I", "W", "X"} if status is not None else self.running
        if status in {"S", "P", "T", "U", "A"}:
            self.running = False
        self.setProperty("running", self.running)
        self.style().unpolish(self)
        self.style().polish(self)
        self._refresh_enabled_state()

    def set_last_response(self, text: str) -> None:
        self.last_response_label.setText(f"Last response: {text}")

    def _refresh_enabled_state(self) -> None:
        can_set_diameter = self.online and not self.running and not self.busy
        diameter_ready = self.online and self.confirmed_diameter is not None
        can_configure_flow = diameter_ready and not self.running and not self.busy

        # Step 1 controls.
        self.diameter_input.setEnabled(can_set_diameter)
        self.set_diameter_button.setEnabled(can_set_diameter)

        # Everything below Step 1 remains locked until a verified DIA read-back.
        self.prime_enabled_checkbox.setEnabled(can_configure_flow)
        self.prime_speed_combo.setEnabled(
            can_configure_flow and self.prime_enabled_checkbox.isChecked()
        )
        self.prime_volume_input.setEnabled(
            can_configure_flow and self.prime_enabled_checkbox.isChecked()
        )
        self.prime_volume_unit_combo.setEnabled(
            can_configure_flow and self.prime_enabled_checkbox.isChecked()
        )
        self.rate_input.setEnabled(can_configure_flow)
        self.rate_unit_combo.setEnabled(can_configure_flow)
        self.direction_combo.setEnabled(can_configure_flow)
        self.continuous_checkbox.setEnabled(can_configure_flow)
        self.volume_input.setEnabled(
            can_configure_flow and not self.continuous_checkbox.isChecked()
        )
        self.volume_unit_combo.setEnabled(
            can_configure_flow and not self.continuous_checkbox.isChecked()
        )

        self.active_checkbox.setEnabled(diameter_ready and not self.busy)
        self.apply_button.setEnabled(can_configure_flow)
        self.run_button.setEnabled(
            diameter_ready and self.settings_applied and not self.busy
        )
        # STOP stays available whenever the pump is online.
        self.stop_button.setEnabled(self.online)
