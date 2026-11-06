from __future__ import annotations
from datetime import datetime
from typing import Callable, Optional
from PySide6.QtCore import QSettings, QThreadPool, Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QMainWindow, QScrollArea, QSplitter, QVBoxLayout, QWidget, QStackedWidget, QTabWidget
from ne501.controller import NE501Controller, ProgramSettings
from ne501.logging_utils import CsvCommandLogger
from ne501.mock_controller import MockNE501Controller
from ne501.protocol import PumpResponse
from ne501.stop_report import StopAllReport, stop_all_independently
from ne501.task_gate import TaskGate
from .pump_panel import PumpPanel, PumpSettings
from .style import build_stylesheet
from .workers import FunctionWorker, WorkerCallbacks
from .i18n import manager, tr
from .i18n_widgets import Label as QLabel, Button as QPushButton, ComboBox as QComboBox, CheckBox as QCheckBox, MessageBox as QMessageBox, LogView as QPlainTextEdit

_CANCELLED=object()

class MainWindow(QMainWindow):
    def __init__(self,config:dict,settings:QSettings|None=None):
        super().__init__()
        self.config=config
        self.addresses=[int(v) for v in config.get('addresses',[0,1,2,3])]
        self.controller=None
        self.thread_pool=QThreadPool.globalInstance();self.thread_pool.setMaxThreadCount(1)
        self.csv_logger=CsvCommandLogger()
        self.settings=settings if settings is not None else QSettings('NE501Controller','NE501 Timeline UI Preview')
        manager.set_language(str(self.settings.value('language','zh_TW')))
        self.pending_tasks=0;self.task_gate=TaskGate();self._panel_pending={}
        self._active_workers=set();self._active_callbacks=set();self._pump_generation={}
        self.resize(1280,850)
        self.language_combo=QComboBox();self.language_combo.addItem('繁體中文','zh_TW');self.language_combo.addItem('English','en')
        self.language_combo.setCurrentIndex(self.language_combo.findData(manager.language))
        self.ui_scale_combo=QComboBox()
        for label,value in [('85%',.85),('100%',1.),('115%',1.15),('130%',1.3)]:self.ui_scale_combo.addItem(label,value)
        try:scale=float(self.settings.value('ui_scale',1.))
        except (TypeError,ValueError):scale=1.
        self.ui_scale_combo.setCurrentIndex(min(range(self.ui_scale_combo.count()),key=lambda i:abs(self.ui_scale_combo.itemData(i)-scale)))
        self.ui_scale_combo.setToolTip('Adjust application text and control size')
        self.connection_label=QLabel('● Disconnected');self.connection_label.setObjectName('offlineStatus')
        self.emergency_button=QPushButton('EMERGENCY STOP ALL');self.emergency_button.setObjectName('emergencyButton')
        self.emergency_button.setToolTip('連線後停止所有實際幫浦；時間軌模擬請使用頁面內的停止。')
        common=QHBoxLayout();common.addWidget(QLabel('Language'));common.addWidget(self.language_combo)
        common.addWidget(QLabel('UI size'));common.addWidget(self.ui_scale_combo);common.addWidget(self.connection_label);common.addStretch();common.addWidget(self.emergency_button)

        self.port_combo=QComboBox();self.port_combo.setToolTip('Serial connection: 19200 baud / 8N1')
        self.refresh_button=QPushButton('Refresh COM');self.connect_button=QPushButton('Connect');self.connect_button.setObjectName('connectButton')
        self.scan_button=QPushButton('Scan Pumps');self.refresh_status_button=QPushButton('Refresh status')
        self.auto_refresh_checkbox=QCheckBox('Auto refresh (2 s)')
        top=QHBoxLayout();top.setContentsMargins(0,0,0,0);top.addWidget(QLabel('Port'));top.addWidget(self.port_combo,1)
        for button in (self.refresh_button,self.connect_button,self.scan_button,self.refresh_status_button):top.addWidget(button)
        self.connection_controls=QWidget();self.connection_controls.setLayout(top)
        self.workflow_banner=QLabel('Manual control: commands operate connected pumps.');self.workflow_banner.setObjectName('workflowBanner');self.workflow_banner.setWordWrap(True)

        self.panels={};panel_grid=QGridLayout();panel_grid.setContentsMargins(0,0,0,0);panel_grid.setSpacing(7)
        self.editor_stack=QStackedWidget()
        for index,address in enumerate(self.addresses):
            panel=PumpPanel(address,index=index+1)
            self.panels[address]=panel;panel_grid.addWidget(panel,index//2,index%2);self.editor_stack.addWidget(panel.editor)
            panel.set_diameter_requested.connect(self.set_diameter);panel.apply_requested.connect(self.apply_single)
            panel.run_requested.connect(self.run_single);panel.stop_requested.connect(self.stop_single)
            panel.edit_requested.connect(self.select_pump);panel.state_changed.connect(self.refresh_group_controls)
        dashboard=QWidget();dashboard.setLayout(panel_grid);dashboard.setMinimumWidth(500)
        self.panel_scroll=QScrollArea();self.panel_scroll.setWidgetResizable(True);self.panel_scroll.setWidget(dashboard)
        self.editor_scroll=QScrollArea();self.editor_scroll.setWidgetResizable(True);self.editor_scroll.setWidget(self.editor_stack)
        self.editor_scroll.setMinimumWidth(290);self.editor_scroll.setMaximumWidth(390)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.manual_splitter=QSplitter(Qt.Orientation.Horizontal);self.manual_splitter.addWidget(self.panel_scroll);self.manual_splitter.addWidget(self.editor_scroll)
        self.manual_splitter.setStretchFactor(0,1);self.manual_splitter.setStretchFactor(1,0);self.manual_splitter.setSizes([870,330])
        self.select_all_button=QPushButton('Select available');self.select_all_button.setToolTip('Only online pumps with a verified diameter are included.');self.clear_active_button=QPushButton('Clear selection')
        self.apply_active_button=QPushButton('Apply selected');self.apply_active_button.setObjectName('applyButton')
        self.run_active_button=QPushButton('Start selected');self.run_active_button.setObjectName('runButton')
        self.stop_active_button=QPushButton('Stop selected');self.stop_active_button.setObjectName('stopButton')
        self.group_label=QLabel();self.group_label.setWordWrap(True)
        self.group_guide=QLabel();self.group_guide.setWordWrap(True);self.group_guide.setObjectName('secondaryLabel')
        selection=QHBoxLayout();selection.addWidget(self.select_all_button);selection.addWidget(self.clear_active_button);selection.addWidget(self.group_label,1);selection.addWidget(self.auto_refresh_checkbox)
        actions=QHBoxLayout();actions.addWidget(self.group_guide,1)
        for button in (self.apply_active_button,self.run_active_button,self.stop_active_button):actions.addWidget(button)
        self.log_view=QPlainTextEdit();self.log_view.setReadOnly(True);self.log_view.setMaximumBlockCount(3000)
        self.log_view.setPlaceholderText('Command / response log');self.log_view.setMaximumHeight(140);self.log_view.hide()
        self.diagnostics_checkbox=QCheckBox('Show diagnostics');self.diagnostics_checkbox.toggled.connect(self.log_view.setVisible)
        manual_page=QWidget();manual=QVBoxLayout(manual_page);manual.setContentsMargins(0,0,0,0);manual.setSpacing(5)
        manual.addWidget(self.workflow_banner);manual.addWidget(self.manual_splitter,1);manual.addLayout(selection);manual.addLayout(actions)
        manual.addWidget(self.diagnostics_checkbox);manual.addWidget(self.log_view)
        self.mode_tabs=QTabWidget();self.mode_tabs.addTab(manual_page,'')
        self.timeline_editor=None
        from .timeline_editor import TimelineEditor
        if len(self.addresses)==4:
            self.timeline_editor=TimelineEditor(self.addresses)
            self.timeline_page=QScrollArea();self.timeline_page.setWidgetResizable(True);self.timeline_page.setWidget(self.timeline_editor)
            self.mode_tabs.addTab(self.timeline_page,'')
        else:self.mode_tabs.addTab(QLabel('A timeline requires four pump addresses.'),'')
        self.mode_tabs.currentChanged.connect(self._mode_changed)
        self.mode_tabs.setCurrentIndex(1)
        central=QWidget();root=QVBoxLayout(central);root.setSpacing(5)
        root.addLayout(common);root.addWidget(self.connection_controls);root.addWidget(self.mode_tabs,1);self.setCentralWidget(central)
        self.refresh_button.clicked.connect(self.refresh_ports);self.connect_button.clicked.connect(self.toggle_connection)
        self.scan_button.clicked.connect(self.scan_pumps);self.refresh_status_button.clicked.connect(self.refresh_status)
        self.select_all_button.clicked.connect(self.select_all_available);self.clear_active_button.clicked.connect(self.clear_active)
        self.apply_active_button.clicked.connect(self.apply_active);self.run_active_button.clicked.connect(self.run_active)
        self.stop_active_button.clicked.connect(self.stop_active);self.emergency_button.clicked.connect(self.emergency_stop)
        self.language_combo.currentIndexChanged.connect(self.change_language);self.ui_scale_combo.currentIndexChanged.connect(self.apply_ui_scale)
        manager.changed.connect(self.retranslate)
        self.poll_timer=QTimer(self);self.poll_timer.setInterval(2000);self.poll_timer.timeout.connect(self.maybe_refresh_status);self.poll_timer.start()
        self.age_timer=QTimer(self);self.age_timer.setInterval(1000)
        self.age_timer.timeout.connect(lambda:[panel.refresh_age() for panel in self.panels.values()]);self.age_timer.start()
        self.select_pump(self.addresses[0]);self.refresh_ports();self.refresh_group_controls();self.retranslate()
        self.append_log(f'Log file: {self.csv_logger.path}')
        self.append_log('Close WinPumpTerm before connecting to the COM port.')

    def change_language(self,*_):
        language=str(self.language_combo.currentData());self.settings.setValue('language',language);manager.set_language(language)
    def retranslate(self):
        self.setWindowTitle(tr('NE-501 Pump Controller • UI Preview')+' v1.2.0')
        self.mode_tabs.setTabText(0,tr('Manual Control'));self.mode_tabs.setTabText(1,tr('Timeline Editor'))
        blocker=QSignalBlocker(self.language_combo);self.language_combo.setCurrentIndex(self.language_combo.findData(manager.language));del blocker
        if self.timeline_editor is not None:self.timeline_editor.canvas.update()
        self.refresh_group_controls()
    def _mode_changed(self,index):
        self.connection_controls.setVisible(index==0)
        if self.timeline_editor is not None and index!=1 and self.timeline_editor.running:self.timeline_editor.pause_preview()
    def select_pump(self,address):
        self.selected_address=address;self.editor_stack.setCurrentWidget(self.panels[address].editor)
        self.editor_scroll.verticalScrollBar().setValue(0)
        for key,panel in self.panels.items():panel.set_selected(key==address)
    def apply_ui_scale(self,*_):
        scale=float(self.ui_scale_combo.currentData() or 1.)
        self.settings.setValue('ui_scale',scale);QApplication.instance().setStyleSheet(build_stylesheet(scale));self.updateGeometry()
    def refresh_group_controls(self,*_):
        if not hasattr(self,'group_label'):return
        connected=self.controller is not None and self.controller.is_connected
        panels=self.active_panels()
        can_apply=connected and bool(panels) and all(p.online and p.confirmed_diameter is not None and not p.busy and not p.running for p in panels)
        can_run=can_apply and all(p.settings_applied for p in panels)
        self.apply_active_button.setEnabled(can_apply);self.run_active_button.setEnabled(can_run)
        self.stop_active_button.setEnabled(connected and bool(panels))
        self.clear_active_button.setEnabled(bool(panels))
        self.select_all_button.setEnabled(connected and any(p.online and p.confirmed_diameter is not None and not p.busy for p in self.panels.values()))
        self.emergency_button.setEnabled(connected and self.task_gate.ordinary_ticket() is not None)
        self.connect_button.setEnabled(not self.pending_tasks)
        self.port_combo.setEnabled(not connected and not self.pending_tasks)
        self.refresh_button.setEnabled(not connected and not self.pending_tasks)
        self.scan_button.setEnabled(connected and not self.pending_tasks)
        self.refresh_status_button.setEnabled(connected and not self.pending_tasks)
        self.auto_refresh_checkbox.setEnabled(connected)
        addresses=', '.join(f'{p.address:02d}' for p in panels) or '—'
        self.group_label.setText(f'{len(panels)} selected | Addresses: {addresses}')
        bad=[f'{p.address:02d}' for p in panels if not (p.online and p.confirmed_diameter is not None and not p.busy and not p.running and p.settings_applied)]
        self.group_guide.setText('Select pumps for group actions.' if not panels else f'Needs attention: {", ".join(bad)}' if bad else 'Ready for group actions.')
    def _set_group_buttons_enabled(self,enabled):
        for panel in self.panels.values():panel.set_connection_available(enabled)
        self.refresh_group_controls()
    def maybe_refresh_status(self):
        if self.auto_refresh_checkbox.isChecked() and self.mode_tabs.currentIndex()==0 and self.controller is not None and self.controller.is_connected and not self.pending_tasks:self.refresh_status()
    def refresh_status(self):
        if not self.require_connection() or self.pending_tasks:return
        def action():
            outcomes=[]
            for address in self.addresses:
                try:outcomes.append((address,self.controller.send_command(address,''),None))
                except Exception as exc:outcomes.append((address,None,str(exc)))
            return outcomes
        def success(outcomes):
            for address,response,error in outcomes:
                panel=self.panels[address]
                if error:
                    panel.set_online(False);panel.set_last_response(error);self.append_log(f'ERROR: {error}')
                else:
                    panel.set_online(True);self.process_results([(address,'STATUS',response)])
        self.run_task(action,success,panels=list(self.panels.values()),priority=-10)

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
        if self.pending_tasks: return
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
                panel.set_program_confirmation(confirmation)
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

    def stop_single(self,address:int):
        if not self.require_connection():return
        panel=self.panels[address]
        self._pump_generation[address]=self._pump_generation.get(address,0)+1
        panel.set_stop_pending()
        self.run_task(lambda:stop_all_independently(self.controller,[address]),self.present_stop_report,panels=[panel],priority=50)

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

    def apply_active(self):
        panels=self.active_panels()
        if not panels:return
        for panel in panels:
            if not self.require_panel_ready(panel,False):return
        try:plan=[(p,self.build_program_settings(p,p.current_settings())) for p in panels]
        except ValueError as exc:QMessageBox.warning(self,'Invalid Settings',str(exc));return
        def action():
            outcomes=[]
            for panel,settings in plan:
                try:outcomes.append((panel.address,self.controller.configure_program(panel.address,settings),None))
                except Exception as exc:outcomes.append((panel.address,None,str(exc)))
            return outcomes
        def success(outcomes):
            good=[];bad=[]
            for address,confirmation,error in outcomes:
                panel=self.panels[address]
                if error:
                    bad.append(address);panel.set_online(False);panel.set_last_response(error);continue
                self.process_results(confirmation.commands)
                if confirmation.verified:
                    good.append(address);panel.mark_settings_applied();panel.set_program_confirmation(confirmation)
                    panel.set_last_response(confirmation.message)
                else:
                    bad.append(address);panel.mark_settings_dirty();panel.set_last_response(confirmation.message)
            summary=f'Succeeded: {len(good)} | Failed: {len(bad)} | Not sent: 0'
            self.append_log(summary)
            if bad:QMessageBox.warning(self,'Group result',summary)
        self.run_task(action,success,panels=panels)

    def run_active(self) -> None:
        panels = self.active_panels()
        if not panels:
            QMessageBox.information(self, "No Active Pump", "Select at least one active pump.")
            return
        for panel in panels:
            if not self.require_panel_ready(panel, require_applied=True):
                return
        self.group_command(panels, "RUN 1")

    def stop_active(self):
        panels=self.active_panels()
        if not panels:return
        for panel in panels:
            self._pump_generation[panel.address]=self._pump_generation.get(panel.address,0)+1
            panel.set_stop_pending()
        self.run_task(lambda:stop_all_independently(self.controller,[p.address for p in panels]),self.present_stop_report,panels=panels,priority=50)

    def emergency_stop(self) -> None:
        if not self.require_connection():
            return
        stop_ticket = self.task_gate.begin_stop()
        if stop_ticket is None:
            return
        self.append_log("EMERGENCY STOP ALL")
        self.append_log("Queued commands cancelled; an operation already in progress must finish first.")
        panels = list(self.panels.values())
        for panel in panels: panel.set_stop_pending()
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
                panel.set_online(True)
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

    def group_command(self,panels,command):
        if not self.require_connection():return
        if command=='STP':
            for panel in panels:
                self._pump_generation[panel.address]=self._pump_generation.get(panel.address,0)+1
                panel.set_stop_pending()
            self.run_task(lambda:stop_all_independently(self.controller,[p.address for p in panels]),self.present_stop_report,panels=panels,priority=50)
            return
        def action():
            outcomes=[];failed=False
            for panel in panels:
                if failed:outcomes.append((panel.address,None,'Not sent after an earlier group error'));continue
                try:
                    response=self.controller.send_command(panel.address,command)
                    outcomes.append((panel.address,response,None))
                    failed=not response.ok
                except Exception as exc:outcomes.append((panel.address,None,str(exc)));failed=True
            return outcomes
        def success(outcomes):
            good=bad=not_sent=0
            for address,response,error in outcomes:
                panel=self.panels[address]
                if error=='Not sent after an earlier group error':
                    not_sent+=1;panel.set_last_response(error)
                elif error:
                    bad+=1;panel.set_online(False);panel.set_last_response(error)
                else:
                    self.process_results([(address,command,response)])
                    if response.ok:good+=1
                    else:bad+=1;panel.mark_settings_dirty()
            summary=f'Succeeded: {good} | Failed: {bad} | Not sent: {not_sent}'
            self.append_log(summary)
            if bad:QMessageBox.warning(self,'Group result',summary)
        self.run_task(action,success,panels=panels)

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

    def run_task(self,action:Callable,on_success:Optional[Callable]=None,panels=None,priority=0,stop_ticket=None):
        ticket=stop_ticket if stop_ticket is not None else self.task_gate.ordinary_ticket()
        if ticket is None:
            self.append_log('Operation skipped while STOP ALL is in progress');return
        target_panels=panels or []
        generations={p.address:self._pump_generation.get(p.address,0) for p in target_panels}
        def current():
            return self.task_gate.is_current(ticket) and (stop_ticket is not None or all(self._pump_generation.get(a,0)==g for a,g in generations.items()))
        def guarded_action():
            return action() if current() else _CANCELLED
        worker=FunctionWorker(guarded_action)
        for panel in target_panels:
            self._panel_pending[panel.address]=self._panel_pending.get(panel.address,0)+1;panel.set_busy(True)
        self.pending_tasks+=1;self._active_workers.add(worker)
        def handle_result(result):
            if result is _CANCELLED or not current():self.append_log('Queued operation cancelled after STOP request')
            elif on_success is not None:on_success(result)
        def handle_error(message):
            if current():self.on_task_error(target_panels,message)
            else:self.append_log(f'Earlier operation failed after STOP ALL request: {message}')
        def handle_finished():
            try:self.on_task_finished(worker,target_panels,stop_ticket)
            finally:self._active_callbacks.discard(callbacks)
        callbacks=WorkerCallbacks(self,handle_result,handle_error,handle_finished)
        self._active_callbacks.add(callbacks)
        worker.signals.result.connect(callbacks.receive_result,Qt.ConnectionType.QueuedConnection)
        worker.signals.error.connect(callbacks.receive_error,Qt.ConnectionType.QueuedConnection)
        worker.signals.finished.connect(callbacks.receive_finished,Qt.ConnectionType.QueuedConnection)
        self.thread_pool.start(worker,priority)
        self.refresh_group_controls()

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
        self.refresh_group_controls()

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
        if panel.busy:
            QMessageBox.warning(self, panel.title(), "Wait for the current operation to finish.")
            return False
        if panel.running:
            QMessageBox.warning(self, panel.title(), "The pump is running. Press STOP before changing settings or starting again.")
            return False
        if require_applied and not panel.settings_applied:
            QMessageBox.warning(self, panel.title(), "Settings are not applied. Click APPLY & VERIFY first.")
            return False
        return True


    def closeEvent(self, event: QCloseEvent) -> None:
        if self.pending_tasks:
            QMessageBox.warning(self, "Operations in progress", "Wait for queued operations to finish before closing.")
            event.ignore()
            return
        if self.timeline_editor is not None and not self.timeline_editor.prepare_to_leave():
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
