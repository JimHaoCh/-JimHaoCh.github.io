from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import QSettings, QThreadPool, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ne501.controller import NE501Controller, ProgramSettings
from ne501.logging_utils import CsvCommandLogger
from ne501.mock_controller import MockNE501Controller
from ne501.protocol import PumpResponse
from ne501.stop_report import StopAllReport, stop_all_independently
from ne501.task_gate import TaskGate
from .pump_panel import PumpPanel, PumpSettings
from .style import build_stylesheet
from .workers import FunctionWorker, WorkerCallbacks


_CANCELLED = object()


class MainWindow(QMainWindow):
    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config
        self.addresses = [int(value) for value in config.get("addresses", [0, 1, 2, 3])]
        self.controller = None
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(1)
        self.csv_logger = CsvCommandLogger()
        self.settings = QSettings("NE501Controller", "NE501 Multi Pump Controller")
        self.pending_tasks = 0
        self.task_gate = TaskGate()
        self._panel_pending: dict[int, int] = {}
        # Keep QRunnable objects alive until their finished signal is handled.
        # Without this reference, slower real-serial operations can finish after
        # the Python worker wrapper has been garbage-collected, so the UI never
        # receives the success/error signal.
        self._active_workers: set[FunctionWorker] = set()
        self._active_callbacks: set[WorkerCallbacks] = set()

        self.setWindowTitle(str(config.get("window_title", "NE-501 Multi Pump Controller")))
        self.resize(1280, 850)

        self.port_combo = QComboBox()
        self.refresh_button = QPushButton("Refresh COM")
        self.refresh_button.setObjectName("secondaryButton")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("connectButton")
        self.scan_button = QPushButton("Scan Pumps " + ", ".join(f"{address:02d}" for address in self.addresses))
        self.scan_button.setObjectName("secondaryButton")
        self.connection_label = QLabel("● Disconnected")
        self.connection_label.setObjectName("offlineStatus")

        self.ui_scale_combo = QComboBox()
        for label, value in [("85%", 0.85), ("100%", 1.0), ("115%", 1.15), ("130%", 1.30)]:
            self.ui_scale_combo.addItem(label, value)
        try:
            saved_scale = float(self.settings.value("ui_scale", 1.0))
        except (TypeError, ValueError):
            saved_scale = 1.0
        scale_index = min(
            range(self.ui_scale_combo.count()),
            key=lambda i: abs(float(self.ui_scale_combo.itemData(i)) - saved_scale),
        )
        self.ui_scale_combo.setCurrentIndex(scale_index)
        self.ui_scale_combo.setToolTip("Adjust application text and control size")

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Port"))
        top_bar.addWidget(self.port_combo, 1)
        top_bar.addWidget(QLabel("19200 baud / 8N1"))
        top_bar.addWidget(self.refresh_button)
        top_bar.addWidget(self.connect_button)
        top_bar.addWidget(self.scan_button)
        top_bar.addWidget(QLabel("UI size"))
        top_bar.addWidget(self.ui_scale_combo)
        top_bar.addWidget(self.connection_label)

        self.workflow_banner = QLabel(
            "WORKFLOW  •  1) SET & VERIFY DIAMETER  →  2) Configure Prime / Steady Flow  →  "
            "3) APPLY & VERIFY  →  4) Select Active Pumps / RUN"
        )
        self.workflow_banner.setWordWrap(True)
        self.workflow_banner.setObjectName("workflowBanner")

        self.panels: dict[int, PumpPanel] = {}
        panel_grid = QGridLayout()
        for index, address in enumerate(self.addresses):
            panel = PumpPanel(address)
            self.panels[address] = panel
            panel_grid.addWidget(panel, index // 2, index % 2)
            panel.set_diameter_requested.connect(self.set_diameter)
            panel.apply_requested.connect(self.apply_single)
            panel.run_requested.connect(self.run_single)
            panel.stop_requested.connect(self.stop_single)

        panel_container = QWidget()
        panel_container.setLayout(panel_grid)
        # Keep each panel readable. When the window or Windows display scale
        # leaves less vertical/horizontal space, scroll instead of crushing
        # spin boxes, combo boxes and labels into a few pixels.
        panel_container.setMinimumWidth(1080)

        self.panel_scroll = QScrollArea()
        self.panel_scroll.setWidgetResizable(True)
        self.panel_scroll.setWidget(panel_container)
        self.panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.select_all_button = QPushButton("Select All Available")
        self.clear_active_button = QPushButton("Clear Active")
        self.clear_active_button.setObjectName("secondaryButton")
        self.apply_active_button = QPushButton("Apply Active")
        self.apply_active_button.setObjectName("applyButton")
        self.run_active_button = QPushButton("RUN Active")
        self.run_active_button.setObjectName("runButton")
        self.stop_active_button = QPushButton("STOP Active")
        self.stop_active_button.setObjectName("stopButton")
        self.emergency_button = QPushButton("EMERGENCY STOP ALL")
        self.emergency_button.setObjectName("emergencyButton")

        group_bar = QHBoxLayout()
        group_bar.addWidget(self.select_all_button)
        group_bar.addWidget(self.clear_active_button)
        group_bar.addStretch()
        group_bar.addWidget(self.apply_active_button)
        group_bar.addWidget(self.run_active_button)
        group_bar.addWidget(self.stop_active_button)
        group_bar.addWidget(self.emergency_button)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setPlaceholderText("Command / response log")

        lower_widget = QWidget()
        lower_layout = QVBoxLayout(lower_widget)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.addLayout(group_bar)
        lower_layout.addWidget(self.log_view)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.panel_scroll)
        splitter.addWidget(lower_widget)
        splitter.setSizes([600, 240])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top_bar)
        layout.addWidget(self.workflow_banner)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.scan_button.clicked.connect(self.scan_pumps)
        self.select_all_button.clicked.connect(self.select_all_available)
        self.clear_active_button.clicked.connect(self.clear_active)
        self.apply_active_button.clicked.connect(self.apply_active)
        self.run_active_button.clicked.connect(self.run_active)
        self.stop_active_button.clicked.connect(self.stop_active)
        self.emergency_button.clicked.connect(self.emergency_stop)
        self.ui_scale_combo.currentIndexChanged.connect(self.apply_ui_scale)

        self.scan_button.setEnabled(False)
        self._set_group_buttons_enabled(False)
        self.refresh_ports()
        self.append_log(f"Log file: {self.csv_logger.path}")
        self.append_log("Close WinPumpTerm before connecting to the COM port.")

    def apply_ui_scale(self) -> None:
        scale = float(self.ui_scale_combo.currentData() or 1.0)
        self.settings.setValue("ui_scale", scale)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(scale))
        # Force geometry recalculation after stylesheet metrics change.
        for panel in self.panels.values():
            panel.updateGeometry()
        self.panel_scroll.widget().adjustSize()
        self.updateGeometry()

    def refresh_ports(self) -> None:
        selected = self.port_combo.currentData() or self.settings.value(
            "last_port", self.config.get("port", "COM4")
        )
        self.port_combo.clear()
        try:
            ports = NE501Controller.available_ports()
        except Exception as exc:
            ports = []
            self.append_log(f"Unable to list COM ports: {exc}")

        for device, description in ports:
            self.port_combo.addItem(f"{device} — {description}", device)
        self.port_combo.addItem("Simulation mode (no hardware)", "MOCK")

        index = self.port_combo.findData(selected)
        if index < 0:
            index = self.port_combo.findData(str(self.config.get("port", "COM4")))
        if index < 0 and self.port_combo.count() > 0:
            index = 0
        self.port_combo.setCurrentIndex(index)

    def toggle_connection(self) -> None:
        if self.controller is not None and self.controller.is_connected:
            self.disconnect_controller()
        else:
            self.connect_controller()

    def connect_controller(self) -> None:
        port = str(self.port_combo.currentData() or "")
        if not port:
            QMessageBox.warning(self, "No Port Selected", "Select a COM port.")
            return

        def action():
            controller = MockNE501Controller(self.addresses) if port == "MOCK" else NE501Controller()
            controller.connect(port, int(self.config.get("baudrate", 19200)))
            return controller

        def success(controller) -> None:
            self.controller = controller
            self.settings.setValue("last_port", port)
            self.connection_label.setText(f"● Connected {port}")
            self.connection_label.setObjectName("onlineStatus")
            self.connection_label.style().unpolish(self.connection_label)
            self.connection_label.style().polish(self.connection_label)
            self.connect_button.setText("Disconnect")
            self.port_combo.setEnabled(False)
            self.refresh_button.setEnabled(False)
            self.scan_button.setEnabled(True)
            self._set_group_buttons_enabled(True)
            self.append_log(f"Connected: {port}")
            self.scan_pumps()

        self.run_task(action, success)

    def disconnect_controller(self) -> None:
        if self.pending_tasks:
            QMessageBox.warning(self, "Operations in progress", "Wait for queued operations to finish before disconnecting.")
            return
        choice = QMessageBox.question(
            self,
            "Disconnect",
            "Send STOP to all four pumps before disconnecting?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return
        try:
            if choice == QMessageBox.StandardButton.Yes and self.controller is not None:
                report = stop_all_independently(self.controller, self.addresses)
                self.present_stop_report(report)
            if self.controller is not None:
                self.controller.disconnect()
        except Exception as exc:
            QMessageBox.warning(self, "Disconnect Warning", str(exc))
        finally:
            self.controller = None
            self.connection_label.setText("● Disconnected")
            self.connection_label.setObjectName("offlineStatus")
            self.connection_label.style().unpolish(self.connection_label)
            self.connection_label.style().polish(self.connection_label)
            self.connect_button.setText("Connect")
            self.port_combo.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.scan_button.setEnabled(False)
            self._set_group_buttons_enabled(False)
            for panel in self.panels.values():
                panel.set_online(False)
            self.append_log("Disconnected")

    def scan_pumps(self) -> None:
        if not self.require_connection():
            return

        def action():
            return self.controller.scan(self.addresses)

        def success(responses: dict[int, PumpResponse]) -> None:
            for address in self.addresses:
                response = responses.get(address)
                panel = self.panels[address]
                if response is None:
                    panel.set_online(False)
                    self.csv_logger.write(address, "VER", error="No response")
                    self.append_log(f"Pump {address:02d}：No response")
                    continue
                panel.set_online(True, response.data or "Online")
                panel.update_from_status(response.status)
                panel.set_last_response(self.describe_response(response))
                self.log_response(address, "VER", response)
            online_count = sum(1 for panel in self.panels.values() if panel.online)
            self.append_log(f"Scan completed: {online_count}/{len(self.panels)}  online")

        self.run_task(action, success, panels=list(self.panels.values()))

    def set_diameter(self, address: int, diameter_mm: float) -> None:
        if not self.require_connection():
            return
        panel = self.panels[address]

        def action():
            return self.controller.set_diameter(address, diameter_mm)

        def success(confirmation) -> None:
            self.log_response(address, f"DIA {diameter_mm:.2f}", confirmation.set_response)
            self.log_response(address, "DIA", confirmation.query_response)
            panel.update_from_status(confirmation.query_response.status)
            if confirmation.confirmed:
                panel.confirm_diameter(float(confirmation.confirmed_mm))
                panel.set_last_response(f"Diameter verified:  {confirmation.confirmed_mm:.2f} mm")
            else:
                panel.invalidate_diameter("Verification failed; check the pump response")
                panel.set_last_response(self.describe_response(confirmation.query_response))
                QMessageBox.warning(
                    self,
                    f"Pump {address:02d}",
                    "The diameter read back from the pump does not match the entered value.",
                )

        self.run_task(action, success, panels=[panel])

    def build_program_settings(self, panel: PumpPanel, settings: PumpSettings) -> ProgramSettings:
        if panel.confirmed_diameter is None:
            raise ValueError("Syringe diameter has not been verified")
        return ProgramSettings(
            rate=settings.rate,
            rate_unit=settings.rate_unit,
            direction=settings.direction,
            continuous=settings.continuous,
            volume=settings.volume,
            volume_unit=settings.volume_unit,
            prime_enabled=settings.prime_enabled,
            prime_volume=settings.prime_volume,
            prime_volume_unit=settings.prime_volume_unit,
            prime_speed_level=settings.prime_speed_level,
            diameter_mm=panel.confirmed_diameter,
        )

    def apply_single(self, address: int, settings: PumpSettings) -> None:
        panel = self.panels[address]
        if not self.require_panel_ready(panel, require_applied=False):
            return
        try:
            program_settings = self.build_program_settings(panel, settings)
        except ValueError as exc:
            QMessageBox.warning(self, f"Pump {address:02d}", str(exc))
            return

        def action():
            return self.controller.configure_program(address, program_settings)

        def success(confirmation) -> None:
            self.process_results(confirmation.commands)
            if confirmation.verified:
                panel.mark_settings_applied()
                programmed_rate = (
                    f"{confirmation.steady_rate_value:g} {confirmation.steady_rate_unit}"
                    if confirmation.steady_rate_value is not None and confirmation.steady_rate_unit
                    else "steady flow"
                )
                if confirmation.prime_rate_ml_hr is not None:
                    panel.set_last_response(
                        f"Program verified; Prime {settings.prime_speed_level.title()} ≈ "
                        f"{confirmation.prime_rate_ml_hr:.4g} mL/hr, then {programmed_rate}; "
                        f"VOL unit {confirmation.program_volume_unit}"
                    )
                else:
                    panel.set_last_response(
                        f"Program verified; {programmed_rate}; VOL unit {confirmation.program_volume_unit}"
                    )
            else:
                panel.mark_settings_dirty()
                panel.set_last_response(confirmation.message)
                QMessageBox.warning(self, f"Pump {address:02d}", confirmation.message)

        self.run_task(action, success, panels=[panel])

    def run_single(self, address: int) -> None:
        panel = self.panels[address]
        if not self.require_panel_ready(panel, require_applied=True):
            return
        self.run_single_command(address, "RUN 1", panel)

    def stop_single(self, address: int) -> None:
        if not self.require_connection():
            return
        panel = self.panels[address]

        def action():
            return self.controller.stop_pump(address)

        def success(results) -> None:
            self.process_results(results)

        self.run_task(action, success, panels=[panel], priority=50)

    def run_single_command(self, address: int, command: str, panel: PumpPanel) -> None:
        def action():
            return self.controller.send_command(address, command)

        def success(response: PumpResponse) -> None:
            self.log_response(address, command, response)
            panel.update_from_status(response.status)
            panel.set_last_response(self.describe_response(response))

        self.run_task(action, success, panels=[panel])

    def active_panels(self) -> list[PumpPanel]:
        return [panel for panel in self.panels.values() if panel.is_active()]

    def select_all_available(self) -> None:
        for panel in self.panels.values():
            panel.set_active(panel.online and panel.confirmed_diameter is not None)

    def clear_active(self) -> None:
        for panel in self.panels.values():
            panel.set_active(False)

    def apply_active(self) -> None:
        panels = self.active_panels()
        if not panels:
            QMessageBox.information(self, "No Active Pump", "Select at least one active pump.")
            return
        for panel in panels:
            if not self.require_panel_ready(panel, require_applied=False):
                return
        try:
            plan = [(panel, self.build_program_settings(panel, panel.current_settings())) for panel in panels]
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            return

        def action():
            return [(panel.address, self.controller.configure_program(panel.address, settings)) for panel, settings in plan]

        def success(confirmations) -> None:
            for address, confirmation in confirmations:
                self.process_results(confirmation.commands)
                panel = self.panels[address]
                if confirmation.verified:
                    panel.mark_settings_applied()
                    programmed_rate = (
                        f"{confirmation.steady_rate_value:g} {confirmation.steady_rate_unit}"
                        if confirmation.steady_rate_value is not None and confirmation.steady_rate_unit
                        else "steady flow"
                    )
                    if confirmation.prime_rate_ml_hr is not None:
                        panel.set_last_response(
                            f"Program verified; prime ≈ {confirmation.prime_rate_ml_hr:.4g} mL/hr, "
                            f"then {programmed_rate}"
                        )
                    else:
                        panel.set_last_response(f"Program verified; {programmed_rate}")
                else:
                    panel.mark_settings_dirty()
                    panel.set_last_response(confirmation.message)

        self.run_task(action, success, panels=panels)

    def run_active(self) -> None:
        panels = self.active_panels()
        if not panels:
            QMessageBox.information(self, "No Active Pump", "Select at least one active pump.")
            return
        for panel in panels:
            if not self.require_panel_ready(panel, require_applied=True):
                return
        self.group_command(panels, "RUN 1")

    def stop_active(self) -> None:
        panels = self.active_panels()
        if not panels:
            QMessageBox.information(self, "No Active Pump", "Select at least one active pump.")
            return
        self.group_command(panels, "STP")

    def emergency_stop(self) -> None:
        if not self.require_connection():
            return
        stop_ticket = self.task_gate.begin_stop()
        if stop_ticket is None:
            return
        self.append_log("EMERGENCY STOP ALL")
        self.append_log("Queued commands cancelled; an operation already in progress must finish first.")
        panels = list(self.panels.values())
        controller = self.controller

        def action():
            return stop_all_independently(controller, self.addresses)

        def success(report: StopAllReport) -> None:
            self.present_stop_report(report)

        self.run_task(action, success, panels=panels, priority=100, stop_ticket=stop_ticket)

    def present_stop_report(self, report: StopAllReport) -> None:
        self.process_results(report.results)
        for address in report.confirmed:
            panel = self.panels.get(address)
            if panel is not None:
                panel.set_last_response("STOP confirmed by pump response")
        if report.unconfirmed:
            details = []
            for address, reason in report.unconfirmed.items():
                details.append(f"{address:02d}: {reason}")
                panel = self.panels.get(address)
                if panel is not None:
                    panel.set_online(False)
                    panel.status_label.setText("● STOP NOT CONFIRMED")
                    panel.version_label.setText("Check pump")
                    panel.set_last_response(f"STOP not confirmed: {reason}")
            text = "\n".join(details)
            self.append_log(f"STOP NOT CONFIRMED: {text}")
            QMessageBox.warning(
                self, "STOP not confirmed",
                "Check these pumps directly; they may still be running:\n" + text,
            )

    def group_command(self, panels: list[PumpPanel], command: str) -> None:
        if not self.require_connection():
            return

        def action():
            if command == "STP":
                results = []
                for panel in panels:
                    results.extend(self.controller.stop_pump(panel.address))
                return results
            return self.controller.send_many((panel.address, command) for panel in panels)

        def success(results) -> None:
            self.process_results(results)

        priority = 50 if command == "STP" else 0
        self.run_task(action, success, panels=panels, priority=priority)

    def process_results(self, results) -> None:
        for address, command, response in results:
            self.log_response(address, command, response)
            panel = self.panels.get(address)
            if panel is not None:
                panel.update_from_status(response.status)
                panel.set_last_response(self.describe_response(response))

    def log_response(self, address: int, command: str, response: PumpResponse) -> None:
        self.csv_logger.write(address, command, response=response)
        message = f"TX {address:02d} {command} | RX {self.describe_response(response)}"
        self.append_log(message)

    def describe_response(self, response: PumpResponse) -> str:
        parts = [response.status_label]
        if response.data:
            parts.append(response.data)
        if response.error_code:
            parts.append(f"Error: {response.error_label}")
        if response.alarm_code:
            parts.append(f"Alarm: {response.alarm_label}")
        return " | ".join(parts)

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_view.appendPlainText(f"[{timestamp}] {message}")

    def run_task(
        self,
        action: Callable,
        on_success: Optional[Callable] = None,
        panels: Optional[list[PumpPanel]] = None,
        priority: int = 0,
        stop_ticket: Optional[int] = None,
    ) -> None:
        ticket = stop_ticket if stop_ticket is not None else self.task_gate.ordinary_ticket()
        if ticket is None:
            self.append_log("Operation skipped while STOP ALL is in progress")
            return

        def guarded_action():
            if not self.task_gate.is_current(ticket):
                return _CANCELLED
            return action()

        worker = FunctionWorker(guarded_action)
        target_panels = panels or []
        for panel in target_panels:
            self._panel_pending[panel.address] = self._panel_pending.get(panel.address, 0) + 1
            panel.set_busy(True)
        self.pending_tasks += 1
        self._active_workers.add(worker)

        def handle_result(result) -> None:
            if result is _CANCELLED or not self.task_gate.is_current(ticket):
                self.append_log("Queued operation cancelled after STOP ALL request")
            elif on_success is not None:
                on_success(result)

        def handle_error(message: str) -> None:
            if self.task_gate.is_current(ticket):
                self.on_task_error(target_panels, message)
            else:
                self.append_log(f"Earlier operation failed after STOP ALL request: {message}")

        def handle_finished() -> None:
            try:
                self.on_task_finished(worker, target_panels, stop_ticket)
            finally:
                self._active_callbacks.discard(callbacks)

        callbacks = WorkerCallbacks(self, handle_result, handle_error, handle_finished)
        self._active_callbacks.add(callbacks)
        worker.signals.result.connect(callbacks.receive_result, Qt.ConnectionType.QueuedConnection)
        worker.signals.error.connect(callbacks.receive_error, Qt.ConnectionType.QueuedConnection)
        worker.signals.finished.connect(callbacks.receive_finished, Qt.ConnectionType.QueuedConnection)
        self.thread_pool.start(worker, priority)

    def on_task_error(self, panels: list[PumpPanel], message: str) -> None:
        self.append_log(f"ERROR: {message}")
        for panel in panels:
            # A failed command does not establish the pump's physical state.
            # Require a new scan and diameter verification before another RUN.
            panel.set_online(False)
            panel.status_label.setText("● STATUS UNCONFIRMED")
            panel.version_label.setText("Check pump and rescan")
            panel.set_last_response(f"Error：{message}")
        QMessageBox.warning(self, "Operation Failed", message)

    def on_task_finished(
        self, worker: FunctionWorker, panels: list[PumpPanel], stop_ticket: Optional[int]
    ) -> None:
        self.pending_tasks = max(0, self.pending_tasks - 1)
        for panel in panels:
            count = max(0, self._panel_pending.get(panel.address, 0) - 1)
            self._panel_pending[panel.address] = count
            panel.set_busy(count > 0)
        if stop_ticket is not None:
            self.task_gate.end_stop(stop_ticket)
        self._active_workers.discard(worker)

    def require_connection(self) -> bool:
        if self.controller is None or not self.controller.is_connected:
            QMessageBox.warning(self, "Not Connected", "Connect to the COM port first.")
            return False
        return True

    def require_panel_ready(self, panel: PumpPanel, require_applied: bool) -> bool:
        if not self.require_connection():
            return False
        if not panel.online:
            QMessageBox.warning(self, panel.title(), "Pump is offline.")
            return False
        if panel.confirmed_diameter is None:
            QMessageBox.warning(self, panel.title(), "Set and verify the syringe inside diameter first.")
            return False
        if panel.running and not require_applied:
            QMessageBox.warning(self, panel.title(), "The pump is running. Press STOP before changing settings.")
            return False
        if require_applied and not panel.settings_applied:
            QMessageBox.warning(self, panel.title(), "Settings are not applied. Click APPLY & VERIFY first.")
            return False
        return True

    def _set_group_buttons_enabled(self, enabled: bool) -> None:
        for button in (
            self.select_all_button,
            self.clear_active_button,
            self.apply_active_button,
            self.run_active_button,
            self.stop_active_button,
            self.emergency_button,
        ):
            button.setEnabled(enabled)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.pending_tasks:
            QMessageBox.warning(self, "Operations in progress", "Wait for queued operations to finish before closing.")
            event.ignore()
            return
        if self.controller is None or not self.controller.is_connected:
            event.accept()
            return

        choice = QMessageBox.question(
            self,
            "Close Application",
            "Send STOP to all four pumps before closing?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return
        try:
            if choice == QMessageBox.StandardButton.Yes:
                report = stop_all_independently(self.controller, self.addresses)
                self.present_stop_report(report)
            self.controller.disconnect()
        except Exception as exc:
            QMessageBox.warning(self, "Close Warning", str(exc))
        event.accept()
