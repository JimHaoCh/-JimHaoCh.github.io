"""Shared, task-oriented preparation pages for manual and timeline operation."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QColor, QPainter, QPen, QValidator
import math
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QStackedWidget, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy, QTabBar,
)
from .i18n import manager, tr
from .i18n_widgets import Label, Button, CheckBox, ComboBox, SpinBox
from .unit_fields import preserve_quantity
from ne501.syringe import FLOW_UL_MIN


class TextInput(QLineEdit):
    def __init__(self, placeholder):
        super().__init__()
        self.placeholder = placeholder
        self.setMaxLength(64)
        manager.changed.connect(self.retranslate)
        self.retranslate()

    def retranslate(self):
        self.setPlaceholderText(tr(self.placeholder))


class DiameterInput(SpinBox):
    """Keep the empty-diameter hint outside the editable numeric text."""
    def __init__(self):
        super().__init__()
        manager.changed.connect(self._refresh_placeholder)
        self._refresh_placeholder()

    def textFromValue(self, value):
        return '' if value == 0 else super().textFromValue(value)

    def valueFromText(self, text):
        return 0.0 if not text.strip() else super().valueFromText(text)

    def validate(self, text, position):
        if not text.strip():
            return QValidator.State.Acceptable, text, position
        return super().validate(text, position)

    def stepBy(self, steps):
        # Step through representable diameters: 0.100–9.999 by 0.001,
        # then 10.00–50.00 by 0.01. Index 0 is the explicitly empty value.
        if not steps:
            return
        value = self.valueFromText(self.text())
        index = 0 if value < .1 else (value - .1) * 1000 + 1 if value < 10 else 9901 + (value - 10) * 100
        index = math.floor(index + 1e-7) + steps if steps > 0 else math.ceil(index - 1e-7) + steps
        index = max(0, min(13901, index))
        value = 0 if index == 0 else (index + 99) / 1000 if index <= 9900 else (index - 8901) / 100
        self.setValue(value)

    def _refresh_placeholder(self):
        self.lineEdit().setPlaceholderText('' if self.hasFocus() else tr('Enter diameter'))

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._refresh_placeholder()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._refresh_placeholder()


class DiameterDrawing(QWidget):
    """Exact code-drawn bore cue: d spans the inside of the syringe barrel."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(88, 64)
        manager.changed.connect(self.update)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#b8cce3'), 3))
        painter.drawEllipse(12, 6, 52, 52)
        painter.setPen(QPen(QColor('#eaf3ff'), 2))
        painter.drawEllipse(20, 14, 36, 36)
        painter.setPen(QPen(QColor('#ffd166'), 2))
        painter.drawLine(20, 32, 56, 32)
        painter.drawLine(20, 32, 26, 28)
        painter.drawLine(20, 32, 26, 36)
        painter.drawLine(56, 32, 50, 28)
        painter.drawLine(56, 32, 50, 36)
        painter.drawText(66, 37, 'd')


def page(title, note):
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(14, 10, 14, 12)
    title_label = Label(title)
    title_label.setObjectName('pageTitle')
    title_label.setWordWrap(True)
    layout.addWidget(title_label)
    subtitle = Label(note)
    subtitle.setObjectName('secondaryLabel')
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)
    scroll = QScrollArea()
    scroll.title_label = title_label
    scroll.note_label = subtitle
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)
    return scroll, layout


def card():
    widget = QWidget()
    widget.setObjectName('setupCard')
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(6)
    return widget, layout


class Workflow(QWidget):
    def __init__(self, owner, connection_controls, modes):
        super().__init__()
        self.owner = owner
        self.updating = False
        self.step = 0
        self.mapping_inputs = {}
        self.diameter_inputs = {}
        self.diameter_status = {}
        self.diameter_buttons = {}
        self.diameter_cards = {}
        self.prep_input_values = {}
        self._prep_selector = ComboBox()
        self._prep_selector.currentIndexChanged.connect(lambda *_: owner.select_pump(self._prep_selector.currentData()) if self._prep_selector.currentData() in owner.panels else None)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)
        self.mode_selector = QTabBar()
        self.mode_selector.setObjectName('modeSelector')
        self.mode_selector.setExpanding(True)
        self.mode_selector.setDrawBase(False)
        self.mode_selector.addTab('')
        self.mode_selector.addTab('')
        self.mode_selector.currentChanged.connect(modes.setCurrentIndex)
        root.addWidget(self.mode_selector)
        nav = QHBoxLayout()
        nav.setSpacing(5)
        self.steps = []
        for i, text in enumerate(('1 Connect & map', '2 Syringes', '3 Tubing', '4 Operation', '5 Review & start')):
            button = Button(text)
            button.setObjectName('stepButton')
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda checked=False, index=i: owner.show_workflow_step(index))
            nav.addWidget(button, 1)
            self.steps.append(button)
        root.addLayout(nav)
        self.progress = Label()
        self.progress.setObjectName('secondaryLabel')
        root.addWidget(self.progress)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.build_mapping(connection_controls))
        self.stack.addWidget(self.build_syringes())
        self.stack.addWidget(self.build_tubing())
        self.stack.addWidget(modes)
        self.stack.addWidget(self.build_review())
        root.addWidget(self.stack, 1)
        footer = QHBoxLayout()
        self.next_hint = Label()
        self.next_hint.setObjectName('nextStepBanner')
        self.next_hint.setWordWrap(True)
        self.next_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.next_hint, 1)
        self.next_button = Button('Next step')
        self.next_button.setObjectName('applyButton')
        self.next_button.clicked.connect(owner.follow_workflow_hint)
        footer.addWidget(self.next_button)
        root.addLayout(footer)
        manager.changed.connect(self.refresh)

    def identity(self, address):
        index = self.owner.addresses.index(address) + 1
        plan = self.owner.preparation.plans[address]
        identity = f'P{index} · {address:02d}'
        if plan.fluid:
            identity += ' · ' + plan.fluid
        if plan.inlet:
            identity += ' → ' + plan.inlet
        return identity

    def build_mapping(self, connection):
        view, layout = page('Connect pumps and match the fluid paths',
                            'Choose the pumps used in this experiment. Match each address to its physical pump and chip inlet.')
        layout.addWidget(connection)
        grid = QGridLayout()
        for i, address in enumerate(self.owner.addresses):
            widget, box = card()
            check = CheckBox(f'Use P{i + 1} · Address {address:02d}')
            box.addWidget(check)
            fluid, inlet = TextInput('Fluid name (optional)'), TextInput('Chip inlet (optional)')
            box.addWidget(fluid)
            box.addWidget(inlet)
            self.mapping_inputs[address] = (check, fluid, inlet)
            check.toggled.connect(lambda checked, a=address: self.owner.update_preparation(a, used=checked))
            fluid.editingFinished.connect(lambda a=address, w=fluid: self.owner.update_preparation(a, fluid=w.text().strip()))
            inlet.editingFinished.connect(lambda a=address, w=inlet: self.owner.update_preparation(a, inlet=w.text().strip()))
            grid.addWidget(widget, i // 2, i % 2)
        layout.addLayout(grid)
        self.mapping_note = Label('Add any initial priming as timeline blocks. Every included block contributes to the delivery totals.')
        self.mapping_note.setObjectName('secondaryLabel')
        self.mapping_note.setWordWrap(True)
        layout.addWidget(self.mapping_note)
        demo = Button('Load example workflow')
        demo.setToolTip('Load example blocks for selected pumps; retain syringe diameters and path names, then review step 2.')
        demo.clicked.connect(self.owner.load_example_workflow)
        layout.addWidget(demo)
        layout.addStretch()
        return view

    def build_syringes(self):
        view, layout = page('Syringe inside diameter d (mm)',
                            'New plans start at 10 mm. Use the actual inside diameter; capacity in mL is a separate quantity.')
        self.syringe_count = Label()
        self.syringe_count.setObjectName('nextStepBanner')
        self.syringe_count.hide()
        grid = QGridLayout()
        for i, address in enumerate(self.owner.addresses):
            widget, box = card()
            identity = Label()
            identity.setTextFormat(Qt.TextFormat.PlainText)
            identity.setObjectName('cardTitle')
            identity.setWordWrap(True)
            identity.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            box.addWidget(identity)
            title = Label('Syringe inside diameter d')
            title.setObjectName('diameterHeading')
            box.addWidget(title)
            row = QHBoxLayout()
            row.addWidget(DiameterDrawing())
            spin = DiameterInput()
            spin.setObjectName('syringeValue')
            spin.setDecimals(3)
            spin.setRange(0, 50)
            spin.setSingleStep(.001)
            spin.setAccessibleName(tr('Syringe inside diameter d (mm)'))
            spin.setKeyboardTracking(False)
            row.addWidget(spin, 1)
            unit = Label('mm')
            unit.setObjectName('diameterHeading')
            row.addWidget(unit)
            box.addLayout(row)
            status = Label()
            status.setWordWrap(True)
            box.addWidget(status)
            verify = Button('Write diameter & read back')
            verify.clicked.connect(lambda checked=False, a=address: self.owner.write_plan_diameter(a))
            box.addWidget(verify)
            spin.editingFinished.connect(lambda a=address, w=spin: self.owner.commit_diameter(a, w))
            spin.valueChanged.connect(lambda _, a=address, w=spin: self.owner.diameter_value_changed(a, w))
            spin.lineEdit().textEdited.connect(lambda text, a=address: self.owner.diameter_text_pending(a))
            self.diameter_cards[address] = (widget, identity)
            self.diameter_inputs[address] = spin
            self.diameter_status[address] = status
            self.diameter_buttons[address] = verify
            grid.addWidget(widget, i // 2, i % 2)
        layout.addLayout(grid)
        self.empty_syringes = Label('Select the pumps in step 1 to enter their syringe diameters.')
        self.empty_syringes.setWordWrap(True)
        layout.addWidget(self.empty_syringes)
        self.copy_button = Button('Use current device read-backs as plan values')
        self.copy_button.clicked.connect(self.owner.adopt_diameter_readbacks)
        layout.addWidget(self.copy_button)
        self.syringe_note = Label()
        self.syringe_note.setObjectName('secondaryLabel')
        self.syringe_note.setWordWrap(True)
        layout.addWidget(self.syringe_note)
        layout.addStretch()
        return view

    def build_tubing(self):
        # Retain the old stack index for JSON/editor navigation compatibility.
        return QWidget()

    @property
    def prep_pump(self): return self._prep_selector
    @property
    def prep_toggle(self): return self.owner.panels[self.owner.selected_address].priming_control.toggle
    @property
    def prep_rate(self): return self.owner.panels[self.owner.selected_address].priming_control.custom_rate
    @property
    def prep_rate_unit(self): return self.owner.panels[self.owner.selected_address].priming_control.rate_unit
    @property
    def prep_volume(self): return self.owner.panels[self.owner.selected_address].priming_control.volume
    @property
    def prep_volume_unit(self): return self.owner.panels[self.owner.selected_address].priming_control.volume_unit
    @property
    def prep_direction(self): return self.owner.panels[self.owner.selected_address].priming_control.direction
    @property
    def prep_write(self): return self.owner.panels[self.owner.selected_address].apply_button
    @property
    def prep_start(self): return self.owner.panels[self.owner.selected_address].priming_control.start
    @property
    def prep_stop(self): return self.owner.panels[self.owner.selected_address].stop_button

    def build_review(self):
        view, layout = page('Review targets and delivery before starting',
                            'Plan values, user confirmations and device read-backs are listed separately.')
        self.review_scope = ComboBox()
        self.review_scope.addItem('All pumps used in this experiment', 'used')
        self.review_scope.addItem('Selected manual pump', 'single')
        self.review_scope.addItem('Manual group selection', 'group')
        self.review_scope.currentIndexChanged.connect(lambda *_: self.owner.refresh_group_controls())
        layout.addWidget(self.review_scope)
        self.review_table = QTableWidget(0, 6)
        self.review_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.review_table.verticalHeader().hide()
        self.review_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.review_table.setMinimumHeight(170)
        layout.addWidget(self.review_table)
        self.review_note = Label()
        self.review_note.setWordWrap(True)
        self.review_note.setObjectName('nextStepBanner')
        layout.addWidget(self.review_note)
        self.review_write = Button('Write settings & read back')
        self.review_write.setObjectName('applyButton')
        self.review_start = Button('Start reviewed pumps')
        self.review_start.setObjectName('runButton')
        self.review_check = Button('Check timeline')
        self.review_play = Button('Preview flow')
        self.review_write.clicked.connect(self.owner.write_review)
        self.review_start.clicked.connect(self.owner.start_review)
        self.review_check.clicked.connect(self.owner.check_review_flow)
        self.review_play.clicked.connect(self.owner.play_review_flow)
        for button in (self.review_write, self.review_start, self.review_check, self.review_play):
            layout.addWidget(button)
        layout.addStretch()
        return view

    def show_step(self, step):
        if self.owner.manual_mode() and step in (2,4):step = 1 if step==2 else 3
        elif not self.owner.manual_mode() and step == 2:step=3
        self.step = step
        self.stack.setCurrentIndex(step)
        self.refresh()

    def refresh(self):
        if self.updating:
            return
        self.updating = True
        try:
            owner = self.owner
            prep = owner.preparation
            used = prep.used_addresses()
            targets = owner.workflow_addresses()
            manual = owner.manual_mode()
            timeline = owner.timeline_editor
            blocker = QSignalBlocker(self.mode_selector)
            self.mode_selector.setCurrentIndex(owner.mode_tabs.currentIndex())
            del blocker
            for i, text in enumerate(('Manual Control', 'Timeline Editor')):
                self.mode_selector.setTabText(i, tr(text))
            self.mode_selector.setAccessibleName(tr('Operation mode'))
            labels = ('1 Connect & map', '2 Syringes', '', '3 Manual console', '') if manual else ('1 Pumps & paths', '2 Syringes', '', '3 Timeline editor', '4 Check & preview')
            self.steps[2].hide()
            self.steps[4].setVisible(not manual)
            owner.connection_controls.setVisible(manual)
            self.mapping_note.setVisible(not manual)
            mapping = self.stack.widget(0)
            mapping.title_label.setText('Connect pumps and match the fluid paths' if manual else 'Choose pumps and name their fluid paths')
            mapping.note_label.setText('Choose the pumps used in this experiment. Match each address to its physical pump and chip inlet.' if manual else 'Choose the pumps, fluids and inlets for the timeline. Offline editing is available.')
            self.syringe_note.setText('Entered = plan value. Read back = confirmed in this connection. Writing settings keeps the motor stopped.' if manual else 'Timeline planning uses the entered diameters. Device writes and priming are available in Manual mode.')
            self.stack.widget(1).title_label.setText('Syringe inside diameter d (mm)')
            self.stack.widget(4).title_label.setText('Review targets and delivery before starting' if manual else 'Review the timeline before preview')
            self.stack.widget(4).note_label.setText('Plan values, user confirmations and device read-backs are listed separately.' if manual else 'Check pump paths, syringe diameters and the total delivery from all included blocks.')
            complete = [
                bool(targets) and (not manual or bool(owner.controller and owner.controller.is_connected)
                and all(owner.panels[a].online and owner.panels[a].last_status not in (None, 'A') for a in targets)),
                bool(targets) and all(prep.plans[a].diameter is not None and a not in owner._diameter_pending for a in targets),
                False,  # The legacy tubing-page index remains hidden.
                bool(timeline and timeline.model.included_clips() and not timeline.pending()) if not manual else bool(targets) and all(not owner.panels[a].input_errors() for a in targets),
                bool(timeline and timeline.checked and timeline.plan_ready() and not timeline.pending()) if not manual else bool(targets) and all(not owner.manual_start_blocker(a) for a in targets),
            ]
            for i, button in enumerate(self.steps):
                button.setText(labels[i])
                button.setProperty('current', i == self.step)
                button.setProperty('complete', complete[i])
                button.setToolTip('Step completed' if complete[i] else 'Step pending')
                button.style().unpolish(button)
                button.style().polish(button)
            entered = sum(prep.plans[a].diameter is not None and a not in owner._diameter_pending for a in used)
            verified = sum(owner.diameter_matches_plan(a) for a in used)
            count = (f'Plan entered: {entered}/{len(used)} | Device read-back: {verified}/{len(used)}' if manual else f'Timeline diameters entered: {entered}/{len(used)}') if used else 'No pumps selected for this experiment.'
            self.progress.setText(f'Editing P{owner.panels[owner.selected_address].index} · Start and stop each pump on its card.' if manual and self.step == 3 else count)
            self.syringe_count.setText(count)
            for address in owner.addresses:
                plan = prep.plans[address]
                panel = owner.panels[address]
                check, fluid, inlet = self.mapping_inputs[address]
                check.blockSignals(True)
                check.setChecked(plan.used)
                check.blockSignals(False)
                for line, text in ((fluid, plan.fluid), (inlet, plan.inlet)):
                    if not line.hasFocus():
                        line.setText(text)
                    line.setEnabled(not panel.running and not panel.busy and not panel.stop_pending)
                check.setEnabled(not panel.running and not panel.busy and not panel.stop_pending)
                widget, identity = self.diameter_cards[address]
                widget.setVisible(plan.used)
                identity.setText(self.identity(address))
                spin = self.diameter_inputs[address]
                spin.setAccessibleName(tr('Syringe inside diameter d (mm)'))
                if not spin.hasFocus() and address not in owner._diameter_pending:
                    blocker = QSignalBlocker(spin)
                    spin.setValue(plan.diameter or 0)
                    del blocker
                spin.setEnabled(not panel.running and not panel.busy and not panel.stop_pending)
                status = self.diameter_status[address]
                if address in owner._diameter_pending:
                    status.setText('Finish entering a valid inside diameter.')
                elif plan.diameter is None:
                    status.setText('Required · enter the actual inside diameter.')
                elif owner.diameter_matches_plan(address):
                    status.setText(f'Device read-back: {plan.diameter:g} mm')
                else:
                    status.setText(f'Plan entered: {plan.diameter:g} mm · device confirmation pending' if manual else f'Timeline diameter: {plan.diameter:g} mm')
                self.diameter_buttons[address].setVisible(manual)
                self.diameter_buttons[address].setEnabled(plan.used and owner.diameter_input_valid(address) and owner.can_write_panel(panel))
            self.empty_syringes.setVisible(not used)
            self.copy_button.setEnabled(any(owner.panels[a].confirmed_diameter is not None for a in used))
            target = getattr(owner,'selected_address',None)
            if [self.prep_pump.itemData(i) for i in range(self.prep_pump.count())] != used:
                blocker = QSignalBlocker(self.prep_pump)
                self.prep_pump.clear()
                for address in used:
                    self.prep_pump.addItem(self.identity(address), address)
                if target in used:
                    self.prep_pump.setCurrentIndex(self.prep_pump.findData(target))
                del blocker
            if target in used:
                blocker=QSignalBlocker(self.prep_pump)
                self.prep_pump.setCurrentIndex(self.prep_pump.findData(target))
                del blocker
            if getattr(owner,'station_ready',False):owner.refresh_preparation_controls()
            self.refresh_review()
            hint, target_step = owner.workflow_hint()
            self.next_hint.setText(hint)
            self.next_button.setText('Go to required step' if target_step != self.step else 'Locate required field')
            self.next_button.setVisible((self.step != 4 or target_step != 4) and not (manual and self.step==3 and target_step==3))
            self.next_button.setEnabled(not owner.pending_tasks)
        finally:
            self.updating = False

    def refresh_review(self):
        owner = self.owner
        timeline = owner.timeline_editor
        simulation = owner.mode_tabs.currentIndex() == 1
        self.review_scope.setVisible(not simulation)
        addresses = owner.review_addresses() if not simulation else owner.preparation.used_addresses()
        headers = ('Pump / path', 'Inside diameter', 'Timeline delivery (all blocks)', 'Confirmation') if simulation else ('Pump / path', 'Inside diameter', 'Delivery', 'Startup Prime', 'Manual priming plan', 'Confirmation')
        self.review_table.setColumnCount(len(headers))
        self.review_table.setHorizontalHeaderLabels([tr(t) for t in headers])
        self.review_table.setRowCount(len(addresses))
        for row, address in enumerate(addresses):
            plan = owner.preparation.plans[address]
            panel = owner.panels[address]
            settings = panel.current_settings()
            if simulation and timeline is not None:
                index = owner.addresses.index(address)
                clips = [c for c in timeline.model.included_clips() if c.pump == index]
                infused = sum(c.volume_ul for c in clips if c.direction == 'INF')
                withdrawn = sum(c.volume_ul for c in clips if c.direction == 'WDR')
                delivery = tr('Infuse') + f': {infused:.5g} µL\n' + tr('Withdraw') + f': {withdrawn:.5g} µL'
                extra = '—'
                confirmation = tr('Flow checked' if timeline.checked and timeline.plan_ready() and not timeline.pending() else 'Flow check pending')
            else:
                direction = tr('Infuse' if settings.direction == 'INF' else 'Withdraw')
                from .pump_panel import RATE_LABELS
                mode = tr('Continuous') if settings.continuous else f'{settings.volume:g} {"µL" if settings.volume_unit == "UL" else "mL"}'
                delivery = f'{direction}\n{settings.rate:g} {RATE_LABELS[settings.rate_unit]}\n{mode}'
                extra = f'{settings.prime_volume:g} {"µL" if settings.prime_volume_unit == "UL" else "mL"}' if settings.prime_enabled else tr('Off')
                confirmation = tr(owner.manual_start_blocker(address) or 'Device settings verified')
            amount = owner.preparation.preparation_amounts.get(address)
            tubing_amount = f'{amount[0]:g} {"µL" if amount[1] == "UL" else "mL"}' if amount else tr('Not recorded')
            diameter = f'{plan.diameter:g} mm' if plan.diameter is not None else tr('Not entered')
            values = (self.identity(address), diameter, delivery, confirmation) if simulation else (self.identity(address), diameter, delivery, extra, tubing_amount, confirmation)
            for col, text in enumerate(values):
                self.review_table.setItem(row, col, QTableWidgetItem(text))
        self.review_table.resizeRowsToContents()
        for button in (self.review_write, self.review_start):
            button.setVisible(not simulation)
        for button in (self.review_check, self.review_play):
            button.setVisible(simulation)
        ready = bool(addresses) and all(not owner.manual_start_blocker(a) for a in addresses)
        self.review_write.setEnabled(bool(addresses) and all(owner.can_write_panel(owner.panels[a]) for a in addresses)
                                     and all(owner.preparation.plans[a].diameter is not None and a not in owner._diameter_pending and not owner.panels[a].input_errors() for a in addresses))
        self.review_start.setEnabled(ready)
        self.review_start.setText(f'Start reviewed pumps ({len(addresses)})')
        self.review_check.setEnabled(bool(simulation and owner.can_use_timeline() and timeline and timeline.plan_ready() and not timeline.busy() and not timeline.pending()))
        self.review_play.setEnabled(bool(simulation and timeline and timeline.can_start_preview()))
        self.review_play.setText('Resume preview' if timeline and timeline.paused else 'Preview flow')
        if simulation:
            self.review_note.setText('All included blocks count toward the totals. Preview playback sends no pump start commands.')
        else:
            self.review_note.setText('Use the pump cards to start, resume or stop. Write changed settings before starting.')
