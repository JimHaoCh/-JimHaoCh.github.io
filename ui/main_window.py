from __future__ import annotations
from datetime import datetime
from contextlib import nullcontext
from typing import Callable, Optional
from PySide6.QtCore import QEvent, QSettings, QThreadPool, Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QMainWindow, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget, QStackedWidget, QTabWidget
from ne501.controller import NE501Controller, ProgramSettings, CommandCancelled
from ne501 import __version__
from ne501.syringe import format_diameter
from ne501.preparation import PreparationState
from .workflow_controller import WorkflowController
from .workflow import Workflow
from .manual_station import ManualStationController
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

class MainWindow(ManualStationController, WorkflowController, QMainWindow):
    def __init__(self,config:dict,settings:QSettings|None=None):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.config=config
        self.addresses=[int(v) for v in config.get('addresses',[0,1,2,3])]
        self.controller=None
        self.preparation = PreparationState(self.addresses)
        self._diameter_pending = set()
        self._prep_input_pending = False
        self._notice_windows = set()
        self._alarm_notices = set()
        self._prep_verified = {}
        self._syncing_preparation = False
        self._refreshing_workflow = False
        self._timeline_allowed = None
        self._timeline_plan_ready = None
        self.thread_pool=QThreadPool.globalInstance();self.thread_pool.setMaxThreadCount(1)
        self.csv_logger=CsvCommandLogger()
        self.settings=settings if settings is not None else QSettings('NE501Controller','NE501 Timeline UI Preview')
        manager.set_language(str(self.settings.value('language','zh_TW')))
        self.pending_tasks=0;self.task_gate=TaskGate();self._panel_pending={}
        self._active_workers=set();self._active_callbacks=set();self._pump_generation={};self._packet_epoch=0
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
        self.emergency_button=QPushButton('Stop all pumps');self.emergency_button.setObjectName('emergencyButton')
        self.emergency_button.setToolTip('Stop preview playback and send STOP to every configured pump; wait for individual confirmations.')
        common=QHBoxLayout();common.addWidget(QLabel('Language'));common.addWidget(self.language_combo)
        common.addWidget(QLabel('UI size'));common.addWidget(self.ui_scale_combo);common.addWidget(self.connection_label);common.addStretch();common.addWidget(self.emergency_button)

        self.port_combo=QComboBox();self.port_combo.setToolTip('Serial connection: 19200 baud / 8N1')
        self.refresh_button=QPushButton('Refresh COM');self.connect_button=QPushButton('Connect and detect');self.connect_button.setObjectName('connectButton')
        self.connect_button.setToolTip('Connect to the selected port and automatically detect configured pumps.')
        self.scan_button=QPushButton('Rescan pumps');self.refresh_status_button=QPushButton('Refresh status')
        self.auto_refresh_checkbox=QCheckBox('Auto refresh (2 s)')
        top=QHBoxLayout();top.setContentsMargins(0,0,0,0);top.addWidget(QLabel('Port'));top.addWidget(self.port_combo,1)
        for button in (self.refresh_button,self.connect_button,self.scan_button,self.refresh_status_button):top.addWidget(button)
        self.connection_controls=QWidget();self.connection_controls.setLayout(top)
        self.workflow_banner=QLabel('Manual control: commands operate connected pumps.');self.workflow_banner.setObjectName('workflowBanner');self.workflow_banner.setWordWrap(True)

        self.panels={};panel_grid=QGridLayout();panel_grid.setContentsMargins(0,0,0,0);panel_grid.setSpacing(7)
        self.editor_stack=QStackedWidget();self.action_stack=QStackedWidget()
        for index,address in enumerate(self.addresses):
            panel=PumpPanel(address,index=index+1)
            self.panels[address]=panel;panel_grid.addWidget(panel,index//2,index%2);self.editor_stack.addWidget(panel.editor);self.action_stack.addWidget(panel.action_bar)
            panel.set_diameter_requested.connect(self.set_diameter);panel.apply_requested.connect(self.apply_single)
            panel.run_requested.connect(self.run_single);panel.stop_requested.connect(self.stop_single)
            panel.edit_requested.connect(self.select_pump);panel.state_changed.connect(self.refresh_group_controls)
        dashboard=QWidget();dashboard_layout=QVBoxLayout(dashboard);dashboard_layout.setContentsMargins(0,0,0,0)
        self.show_unused_checkbox=QCheckBox('Show pumps outside this experiment')
        self.show_unused_checkbox.toggled.connect(self.refresh_group_controls)
        dashboard_layout.addWidget(self.show_unused_checkbox)
        dashboard_layout.addLayout(panel_grid);dashboard_layout.addStretch();dashboard.setMinimumWidth(500)
        self.panel_scroll=QScrollArea();self.panel_scroll.setWidgetResizable(True);self.panel_scroll.setWidget(dashboard)
        self.panel_scroll.viewport().installEventFilter(self)
        self.editor_scroll=QScrollArea();self.editor_scroll.setWidgetResizable(True);self.editor_scroll.setWidget(self.editor_stack)
        self.editor_scroll.setMinimumWidth(350)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor_container=QWidget();right=QVBoxLayout(self.editor_container);right.setContentsMargins(0,0,0,0);right.setSpacing(3);right.addWidget(self.editor_scroll,1);right.addWidget(self.action_stack)
        self.editor_container.setMinimumWidth(350);self.editor_container.setMaximumWidth(680)
        self.manual_splitter=QSplitter(Qt.Orientation.Horizontal);self.manual_splitter.addWidget(self.panel_scroll);self.manual_splitter.addWidget(self.editor_container)
        self.manual_splitter.setStretchFactor(0,1);self.manual_splitter.setStretchFactor(1,1);self.manual_splitter.setSizes([740,500])
        self.select_all_button=QPushButton('Select available');self.select_all_button.setToolTip('Select online pumps with entered syringe plans.');self.clear_active_button=QPushButton('Clear selection')
        self.apply_active_button=QPushButton('Apply selected');self.apply_active_button.setObjectName('applyButton')
        self.run_active_button=QPushButton('Start selected');self.run_active_button.setObjectName('runButton')
        self.stop_active_button=QPushButton('Stop selected');self.stop_active_button.setObjectName('stopButton')
        self.group_label=QLabel();self.group_label.setWordWrap(True)
        self.group_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.group_guide=QLabel();self.group_guide.setWordWrap(True);self.group_guide.setObjectName('secondaryLabel')
        self.group_guide.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.group_fix_button=QPushButton('Resolve');self.group_fix_button.setObjectName('secondaryButton')
        self.group_fix_button.clicked.connect(self.resolve_group_blocker)
        self._first_group_blocker=None
        selection=QHBoxLayout();selection.addWidget(self.select_all_button);selection.addWidget(self.clear_active_button);selection.addWidget(self.group_label,1);selection.addWidget(self.auto_refresh_checkbox)
        actions=QHBoxLayout();actions.addWidget(self.group_guide,1)
        actions.addWidget(self.group_fix_button)
        for button in (self.apply_active_button,self.run_active_button,self.stop_active_button):actions.addWidget(button)
        self.log_view=QPlainTextEdit();self.log_view.setReadOnly(True);self.log_view.setMaximumBlockCount(3000)
        self.log_view.setPlaceholderText('Command / response log');self.log_view.setMaximumHeight(140);self.log_view.hide()
        self.diagnostics_checkbox=QCheckBox('Show diagnostics');self.diagnostics_checkbox.toggled.connect(self.log_view.setVisible)
        manual_page=QWidget();manual=QVBoxLayout(manual_page);manual.setContentsMargins(0,0,0,0);manual.setSpacing(5)
        manual.addWidget(self.workflow_banner);self.workflow_banner.hide();manual.addWidget(self.manual_splitter,1);manual.addLayout(selection);manual.addLayout(actions)
        manual.addWidget(self.diagnostics_checkbox);manual.addWidget(self.log_view)
        self.mode_tabs=QTabWidget();self.mode_tabs.addTab(manual_page,'')
        self.mode_tabs.tabBar().hide()
        self.timeline_editor=None
        from .timeline_editor import TimelineEditor
        if len(self.addresses)==4:
            self.timeline_editor=TimelineEditor(self.addresses)
            self.timeline_page=QScrollArea();self.timeline_page.setWidgetResizable(True);self.timeline_page.setWidget(self.timeline_editor)
            self.mode_tabs.addTab(self.timeline_page,'')
        else:self.mode_tabs.addTab(QLabel('A timeline requires four pump addresses.'),'')
        self.mode_tabs.currentChanged.connect(self._mode_changed)
        self.mode_tabs.setCurrentIndex(0)
        central=QWidget();root=QVBoxLayout(central);root.setSpacing(5)
        self.execution_label = QLabel()
        self.execution_label.setObjectName('liveStatus')
        self.execution_label.setWordWrap(True)
        self.workflow = Workflow(self, self.connection_controls, self.mode_tabs)
        root.addLayout(common)
        root.addWidget(self.execution_label)
        root.addWidget(self.workflow, 1)
        self.setCentralWidget(central)
        for panel in self.panels.values():
            panel.workflow_managed = True
            panel.planned_diameter = None
            panel.external_start_blocker = ''
            panel.editor_title.setTextFormat(Qt.TextFormat.PlainText)
            panel.footer_target_label.setTextFormat(Qt.TextFormat.PlainText)
            panel._internal_update = True
            panel.diameter_input.setMinimum(0)
            panel.diameter_input.setSpecialValueText(tr('Enter diameter'))
            panel.diameter_input.setValue(0)
            panel._internal_update = False
            for label in panel.step_labels:
                label.hide()
            panel.shared_setup_requested.connect(lambda: self.show_workflow_step(1))
            panel.diameter_input.valueChanged.connect(lambda value, p=panel: self._legacy_diameter_edit(p, value))
        self.attach_manual_station()
        if self.timeline_editor:
            from ne501.timeline_model import Timeline
            self.timeline_editor._load_model(Timeline(addresses=self.addresses))
            self.timeline_editor.external_setup = True
            self.timeline_editor.operation_allowed = self.can_use_timeline
            self.timeline_editor.plan_ready = lambda: not any(a in self._diameter_pending for a in self.preparation.used_addresses())
            self.timeline_editor.syringe_button.hide()
            self.timeline_editor.plan_changed.connect(self.sync_preparation_from_timeline)
            self.timeline_editor.project_loaded.connect(self.reset_experiment_confirmation)
            self.timeline_editor.state_changed.connect(self.refresh_group_controls)
            self.timeline_editor.setup_requested.connect(lambda: self.show_workflow_step(1))
            self.timeline_editor.example_requested.connect(self.load_example_workflow)
            self.timeline_editor.preparation_requested.connect(self.show_timeline_preparation)
            self.timeline_editor.show_notice('New workflow: choose pumps, review the 10 mm defaults in step 2, then add blocks.')
        self.auto_refresh_checkbox.setChecked(False)
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
        if self.csv_logger.initialization_error is not None:
            self.report_log_failure(self.csv_logger.initialization_error)

    def change_language(self,*_):
        language=str(self.language_combo.currentData());self.settings.setValue('language',language);manager.set_language(language)
    def retranslate(self):
        self.setWindowTitle(tr('NE-501 Pump Controller • UI Preview')+' v'+__version__)
        self.mode_tabs.setTabText(0,tr('Manual Control'));self.mode_tabs.setTabText(1,tr('Timeline Editor'))
        blocker=QSignalBlocker(self.language_combo);self.language_combo.setCurrentIndex(self.language_combo.findData(manager.language));del blocker
        if self.timeline_editor is not None:self.timeline_editor.canvas.update()
        self.refresh_group_controls()
    def _mode_changed(self,index):
        if self.timeline_editor is not None and index!=1 and self.timeline_editor.running:self.timeline_editor.pause_preview()
        if hasattr(self, 'workflow'):
            if index==0 and self.workflow.step==4:self.workflow.show_step(3)
            if index == 1 and self.workflow.step == 2:
                self.workflow.show_step(3)
            self.refresh_group_controls()
        QTimer.singleShot(0,self.update_dashboard_density)

    def show_timeline_preparation(self, step):
        self.mode_tabs.setCurrentIndex(1)
        self.show_workflow_step(step)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'panel_scroll'):QTimer.singleShot(0,self.update_dashboard_density)

    def eventFilter(self,watched,event):
        if hasattr(self,'panel_scroll') and watched is self.panel_scroll.viewport() and event.type()==QEvent.Type.Resize:
            self.update_dashboard_density(event.size().height(),event.size().width())
        return super().eventFilter(watched,event)

    def update_dashboard_density(self,height=None,width=None):
        height=self.panel_scroll.viewport().height() if height is None else height
        width=self.panel_scroll.viewport().width() if width is None else width
        compact=height<520 or width<600
        for panel in self.panels.values():panel.set_compact(compact)
    def select_pump(self,address):
        self.selected_address=address;self.editor_stack.setCurrentWidget(self.panels[address].editor);self.action_stack.setCurrentWidget(self.panels[address].action_bar)
        self.editor_scroll.verticalScrollBar().setValue(0)
        for key,panel in self.panels.items():panel.set_selected(key==address)
        self.refresh_group_controls()
    def apply_ui_scale(self,*_):
        scale=float(self.ui_scale_combo.currentData() or 1.)
        self.settings.setValue('ui_scale',scale);QApplication.instance().setStyleSheet(build_stylesheet(scale));self.updateGeometry()
        QTimer.singleShot(0,self.update_dashboard_density)
    def _legacy_diameter_edit(self, panel, value):
        if not panel._internal_update and hasattr(self, 'workflow'):
            self.update_preparation(panel.address, diameter=value or None)

    def refresh_group_controls(self, *_):
        if self._refreshing_workflow:
            return
        self._refreshing_workflow = True
        try:
            if hasattr(self, 'workflow'):
                used = self.preparation.used_addresses()
                self.show_unused_checkbox.setVisible(len(used) < len(self.addresses))
                if used and self.selected_address not in used and not self.show_unused_checkbox.isChecked():
                    self.select_pump(used[0])
                for address, panel in self.panels.items():
                    plan = self.preparation.plans[address]
                    panel.setVisible(plan.used or self.show_unused_checkbox.isChecked() or panel.running or panel.stop_pending or panel.online and panel.last_status in (None, 'A'))
                    if not plan.used and panel.is_active():
                        panel.set_active(False)
                    panel.update_shared_plan(plan.used, plan.diameter, self.preparation.physical_blocker(address), address in self._diameter_pending)
                    identity = self.workflow.identity(address)
                    panel.editor_title.setText(identity)
                    panel.footer_target_label.setText(identity)
                    panel.setTitle(identity if len(identity) < 32 else identity[:29] + '…')
                connected = self.controller is not None and self.controller.is_connected
                kind = 'Demo mode' if connected and isinstance(self.controller, MockNE501Controller) else 'Real pump connection' if connected else 'Offline planning'
                running = ', '.join(f'P{p.index}' for p in self.panels.values() if p.running and p.last_status is not None) or '—'
                running_text = f'Demo pumps running: {running}' if connected and isinstance(self.controller, MockNE501Controller) else f'Reported running: {running}'
                self.execution_label.setText(f'{kind} | {running_text}')
                unconfirmed = ', '.join(f'P{p.index}' for p in self.panels.values() if (p.running and p.last_status is None) or p.stop_pending)
                if unconfirmed:
                    self.execution_label.setText(self.execution_label.source_text + f' | Stop unconfirmed: {unconfirmed}')
                unknown = ', '.join(f'P{p.index}' for p in self.panels.values() if p.last_status is None)
                if connected and unknown:
                    self.execution_label.setText(self.execution_label.source_text + f' | State unknown: {unknown}')
            self._refresh_group_controls_legacy()
            if hasattr(self, 'workflow'):
                timeline = self.timeline_editor
                connected = self.controller is not None and self.controller.is_connected
                self.emergency_button.setEnabled(bool(connected and self.task_gate.ordinary_ticket() is not None or timeline and timeline.busy()))
                if timeline:
                    allowed = self.can_use_timeline()
                    plan_ready = timeline.plan_ready()
                    timeline.setEnabled(allowed)
                    if allowed != self._timeline_allowed or plan_ready != self._timeline_plan_ready:
                        self._timeline_allowed = allowed
                        self._timeline_plan_ready = plan_ready
                        timeline.update_controls()
                panels = self.active_panels()
                self.apply_active_button.setEnabled(bool(panels) and all(self.can_write_panel(p) and self.preparation.plans[p.address].diameter is not None and not p.input_errors() and p.address not in self._diameter_pending for p in panels))
                self.workflow.refresh()
                self.refresh_station()
        finally:
            self._refreshing_workflow = False

    def _refresh_group_controls_legacy(self):
        if not hasattr(self,'group_label'):return
        connected=self.controller is not None and self.controller.is_connected
        selected=self.panels.get(getattr(self,'selected_address',self.addresses[0]))
        if selected is not None:
            mode='Demo mode' if connected and isinstance(self.controller,MockNE501Controller) else 'Connected pumps' if connected else 'Manual setup'
            self.workflow_banner.setText(f'{mode} | Pump {selected.index} | Address {selected.address:02d} | '+selected.next_instruction())
        panels=self.active_panels()
        can_apply=connected and bool(panels) and all(not p.configuration_blocker() for p in panels)
        start_blocker=lambda p:self.manual_start_blocker(p.address) if getattr(self,'station_ready',False) else p.start_blocker()
        can_run=connected and bool(panels) and all(not start_blocker(p) for p in panels)
        self.apply_active_button.setEnabled(can_apply);self.run_active_button.setEnabled(can_run)
        self.stop_active_button.setEnabled(connected and bool(panels))
        self.clear_active_button.setEnabled(bool(panels))
        self.select_all_button.setEnabled(connected and any(p.online and self.preparation.plans[a].used and self.preparation.plans[a].diameter is not None and not p.busy for a,p in self.panels.items()))
        self.emergency_button.setEnabled(connected and self.task_gate.ordinary_ticket() is not None)
        self.connect_button.setEnabled(not self.pending_tasks)
        self.port_combo.setEnabled(not connected and not self.pending_tasks)
        self.refresh_button.setEnabled(not connected and not self.pending_tasks)
        self.scan_button.setEnabled(connected and not self.pending_tasks)
        self.refresh_status_button.setEnabled(connected and not self.pending_tasks)
        self.auto_refresh_checkbox.setEnabled(connected)
        addresses=', '.join(f'{p.address:02d}' for p in panels) or '—'
        count=len(panels);ready_count=sum(not start_blocker(p) for p in panels)
        self.group_label.setText(f'{count} selected | Ready: {ready_count}/{count} | Addresses: {addresses}' if panels else 'Group: no pumps selected')
        blockers=[(p,start_blocker(p)) for p in panels if start_blocker(p)]
        self._first_group_blocker=blockers[0][0].address if blockers else None
        details=[f'Pump {p.index} (address {p.address:02d}): {reason}' for p,reason in blockers]
        self.group_guide.setText('Select pumps for group actions.' if not panels else details[0] if blockers else 'Ready for group actions.')
        self.group_guide.setToolTip('\n'.join(details))
        self.group_fix_button.setVisible(bool(blockers))
        self.group_fix_button.setEnabled(connected and not self.pending_tasks)
        if details:self.group_fix_button.setToolTip(details[0])
        self.apply_active_button.setText(f'Apply selected ({count})')
        self.run_active_button.setText(f'Start / resume ({count})')
        self.run_active_button.setObjectName('runButton')
        self.stop_active_button.setText(f'Stop selected ({count})')
        self.apply_active_button.setStyleSheet('border: 2px solid #ffd166;' if can_apply and not can_run else '')
        self.run_active_button.setStyleSheet('border: 2px solid #ffd166;' if can_run else '')
        if getattr(self,'timeline_editor',None) is not None:
            self.timeline_editor.set_device_diameters({address:p.confirmed_diameter if p.online else None for address,p in self.panels.items()})

    def resolve_group_blocker(self):
        address=self._first_group_blocker
        if address is None:return
        self.select_pump(address)
        panel=self.panels[address]
        if not self.preparation.plans[address].used:
            self.show_workflow_step(0)
            self.workflow.mapping_inputs[address][0].setFocus()
            return
        if self.preparation.plans[address].diameter is None or address in self._diameter_pending:
            self.open_station_setup(address)
            return
        if not panel.online:
            self.show_workflow_step(0)
            self.scan_button.setFocus()
            return
        if panel.last_status is None:
            self.refresh_status_button.setFocus()
            return
        target=panel.focus_next_step()
        if target is None:return
        if panel.editor.isAncestorOf(target):
            QTimer.singleShot(0,lambda:self.editor_scroll.ensureWidgetVisible(target,12,12))
    def _set_group_buttons_enabled(self,enabled):
        for panel in self.panels.values():panel.set_connection_available(enabled)
        self.refresh_group_controls()
    def maybe_refresh_status(self):
        if (self.auto_refresh_checkbox.isChecked() or any(p.running or p.stop_pending for p in self.panels.values())) and self.controller is not None and self.controller.is_connected and not self.pending_tasks and QApplication.activeModalWidget() is None:self.refresh_status()
    def refresh_status(self):
        if not self.require_connection() or self.pending_tasks:return
        ticket=self.task_gate.ordinary_ticket()
        def action():
            outcomes=[]
            for address in self.addresses:
                if ticket is None or not self.task_gate.is_current(ticket):break
                try:
                    response=self.controller.send_command(address,'')
                    phase=None
                    if response.ok and response.status in ('I','W','P','T','U','X') and self.panels[address].station_context:
                        phase=self.controller.send_command(address,'PHN')
                    outcomes.append((address,response,phase,None))
                except Exception as exc:outcomes.append((address,None,None,str(exc)))
            return outcomes
        def success(outcomes):
            for address,response,phase,error in outcomes:
                panel=self.panels[address]
                if error:
                    panel.set_online(False);panel.set_last_response(error);self.append_log(f'ERROR: {error}')
                else:
                    panel.set_online(True)
                    if phase and phase.ok and phase.data.strip().isdigit():panel.station_phase=int(phase.data)
                    self.process_results([(address,'STATUS',response)])
                    if phase:self.log_response(address,'PHN',phase)
        self.run_task(action,success,panels=list(self.panels.values()),priority=-10,lock_panels=False)

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
        self.port_combo.addItem("Demo mode (virtual pumps)", "MOCK")

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
            self.preparation.reset_session()
            self._prep_verified.clear()
            self.station_proofs.clear()
            self._alarm_notices.clear()
            self.settings.setValue("last_port", port)
            self.connection_label.setText('● Demo mode' if isinstance(controller, MockNE501Controller) else f"● Connected {port}")
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
                if report.unconfirmed:
                    return
            if self.controller is not None:
                self.controller.disconnect()
        except Exception as exc:
            QMessageBox.warning(self, "Disconnect Warning", str(exc))
            return
        self.controller = None
        self.preparation.reset_session()
        self._prep_verified.clear()
        self.station_proofs.clear()
        self.connection_label.setText("● Disconnected")
        self.connection_label.setObjectName("offlineStatus")
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)
        self.connect_button.setText("Connect and detect")
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
                    self.record_command(address, "VER", error="No response")
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
        if not self.manual_mode():
            return
        if not self.update_preparation(address, used=True, diameter=diameter_mm):
            return
        if not self.require_connection():
            return
        panel = self.panels[address]
        if not self.can_write_panel(panel):
            return
        self.invalidate_program_confirmation(address)

        def action():
            return self.controller.set_diameter(address, diameter_mm)

        def success(confirmation) -> None:
            self.log_response(address, f"DIA {format_diameter(diameter_mm)}", confirmation.set_response)
            self.log_response(address, "DIA", confirmation.query_response)
            panel.update_from_status(confirmation.query_response.status)
            if confirmation.confirmed:
                panel.confirm_diameter(float(confirmation.confirmed_mm))
                panel.set_last_response(f"Diameter verified:  {confirmation.confirmed_mm:.3f} mm")
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
        diameter = self.preparation.plans[panel.address].diameter
        if diameter is None:
            raise ValueError("Enter the syringe inside diameter.")
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
            diameter_mm=diameter,
        )

    def apply_single(self, address, settings):
        self.write_panel_programs([self.panels[address]], {address: settings})

    def run_single(self, address: int) -> None:
        self.start_station(address)

    def stop_single(self,address:int):
        self.hold_station([address])

    def run_single_command(self, address: int, command: str, panel: PumpPanel) -> None:
        parts=command.strip().upper().split()
        if parts and parts[0]=='RUN':
            if parts not in (['RUN'], ['RUN','1'], ['RUN','3']):return
            self.start_station(address,fresh=parts==['RUN','1'],priming=parts==['RUN','3'])
            return
        def action():
            return self.controller.send_command(address, command)

        def success(response: PumpResponse) -> None:
            self.process_results([(address, command, response)])

        self.run_task(action, success, panels=[panel])

    def active_panels(self) -> list[PumpPanel]:
        return [panel for panel in self.panels.values() if panel.is_active()]

    def select_all_available(self) -> None:
        for panel in self.panels.values():
            plan = self.preparation.plans[panel.address]
            panel.set_active(panel.online and plan.used and plan.diameter is not None and not panel.busy)

    def clear_active(self) -> None:
        for panel in self.panels.values():
            panel.set_active(False)

    def apply_active(self):
        self.write_panel_programs(self.active_panels())

    def run_active(self) -> None:
        panels = self.active_panels()
        if not panels:
            QMessageBox.information(self, "No Active Pump", "Select at least one active pump.")
            return
        self.start_station_group(panels)

    def stop_active(self):
        self.hold_station([p.address for p in self.active_panels()])

    def emergency_stop(self) -> None:
        if self.timeline_editor is not None:
            self.timeline_editor.stop_preview()
        if self.controller is None or not self.controller.is_connected:
            self.refresh_group_controls()
            return
        stop_ticket = self.task_gate.begin_stop()
        if stop_ticket is None:
            return
        self.append_log("EMERGENCY STOP ALL")
        self.append_log('Queued commands cancelled; STOP follows the current command response.')
        panels = list(self.panels.values())
        for panel in panels: panel.set_stop_pending(reset=True)
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
                panel.update_from_status('S')
                panel.set_last_response("STOP confirmed by pump response")
        if report.unconfirmed:
            details = []
            for address, reason in report.unconfirmed.items():
                details.append(f"{address:02d}: {reason}")
                panel = self.panels.get(address)
                if panel is not None:
                    panel.set_online(False)
                    panel.set_stop_pending(reset=True)
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
        parts=command.strip().upper().split()
        if parts and parts[0]=='RUN':
            if parts not in (['RUN'], ['RUN','1'], ['RUN','3']):return
            self.start_station_group(panels,fresh=parts==['RUN','1'],priming=parts==['RUN','3'])
            return
        if command=='STP':
            for panel in panels:
                self._pump_generation[panel.address]=self._pump_generation.get(panel.address,0)+1
                panel.set_stop_pending()
            self.run_task(lambda:stop_all_independently(self.controller,[p.address for p in panels]),self.present_stop_report,panels=panels,priority=50)
            return
        ticket=self.task_gate.ordinary_ticket()
        generations={p.address:self._pump_generation.get(p.address,0) for p in panels}
        def action():
            outcomes=[];failed=False
            for panel in panels:
                if ticket is None or not self.task_gate.is_current(ticket) or any(self._pump_generation.get(a,0)!=g for a,g in generations.items()):
                    outcomes.append((panel.address,None,'Not sent after STOP request'));continue
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
                if error in ('Not sent after an earlier group error','Not sent after STOP request'):
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
            panel = self.panels.get(address)
            if panel is not None:
                panel.update_from_status(response.status)
                panel.set_last_response(self.describe_response(response))
            self.log_response(address, command, response)

    def log_response(self, address: int, command: str, response: PumpResponse) -> None:
        # Scanning and standalone diameter verification also pass here. Keep
        # their alarm notices as persistent as alarms seen during polling.
        panel = self.panels.get(address)
        if panel is not None and response.status == 'A':
            panel.invalidate_diameter('Alarm — check pump, stop and refresh status')
            self.invalidate_program_confirmation(address)
            key = (address, response.alarm_code)
            if key not in self._alarm_notices:
                self._alarm_notices.add(key)
                self.show_nonmodal_warning('Pump alarm',
                    f'Pump {panel.index}: {response.alarm_label or response.data}. Check the device, stop, then write and verify again.')
        self.record_command(address, command, response=response)
        message = f"TX {address:02d} {command} | RX {self.describe_response(response)}"
        self.append_log(message)

    def record_command(self, address, command, *, response=None, error=''):
        try:
            self.csv_logger.write(address, command, response=response, error=error)
        except OSError as exc:
            self.report_log_failure(exc)
        else:
            self._log_failure_reported = False

    def report_log_failure(self, error):
        self.append_log(f'Command log unavailable: {error}')
        if not getattr(self, '_log_failure_reported', False):
            self._log_failure_reported = True
            self.show_nonmodal_warning('Command log unavailable', 'Device responses remain visible. Check the log folder and free disk space.')

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

    def run_task(self,action:Callable,on_success:Optional[Callable]=None,panels=None,priority=0,stop_ticket=None,allow_partial=False,stop_operation=False,lock_panels=True):
        ticket=stop_ticket if stop_ticket is not None else self.task_gate.ordinary_ticket()
        if ticket is None:
            self.append_log('Operation skipped while STOP ALL is in progress');return
        target_panels=panels or []
        generations={p.address:self._pump_generation.get(p.address,0) for p in target_panels}
        controller = self.controller
        def current():
            return self.task_gate.is_current(ticket) and (stop_ticket is not None or stop_operation or all(self._pump_generation.get(a,0)==g for a,g in generations.items()))
        def guarded_action():
            if not current(): return _CANCELLED
            # A stop preempts an active transaction on any pump. Unrelated
            # queued work takes the new epoch when it starts after the stop.
            epoch=self._packet_epoch
            packet_current=lambda:current() and (stop_operation or self._packet_epoch==epoch)
            guard = controller.cancellable(packet_current) if stop_ticket is None and hasattr(controller, 'cancellable') else nullcontext()
            try:
                with guard:return action()
            except CommandCancelled:return _CANCELLED
        worker=FunctionWorker(guarded_action)
        # Read-only polling keeps cancellation guards without disabling forms.
        locked_panels=target_panels if lock_panels else []
        for panel in locked_panels:
            self._panel_pending[panel.address]=self._panel_pending.get(panel.address,0)+1;panel.set_busy(True)
        self.pending_tasks+=1;self._active_workers.add(worker)
        def handle_result(result):
            if result is _CANCELLED or not current() and not (allow_partial and self.task_gate.is_current(ticket)):self.append_log('Queued operation cancelled after STOP request')
            elif on_success is not None:on_success(result)
        def handle_error(message):
            if current():self.on_task_error(target_panels,message)
            else:self.append_log(f'Earlier operation failed after STOP ALL request: {message}')
        def handle_finished():
            try:self.on_task_finished(worker,locked_panels,stop_ticket)
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
            self._prep_verified.pop(panel.address, None)
            self.station_proofs.pop(panel.address, None)
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
        if panel.last_status in (None, "A"):
            QMessageBox.warning(self, panel.title(), "Update the pump status before applying settings or starting.")
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
        if require_applied and self.manual_start_blocker(panel.address):
            QMessageBox.warning(self, panel.title(), self.manual_start_blocker(panel.address))
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
                if report.unconfirmed:
                    event.ignore()
                    return
            self.controller.disconnect()
        except Exception as exc:
            QMessageBox.warning(self, "Close Warning", str(exc))
            event.ignore()
            return
        event.accept()
