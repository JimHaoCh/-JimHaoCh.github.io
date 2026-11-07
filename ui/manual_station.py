"""Per-pump priming, inline setup and same-page manual operation."""
from dataclasses import replace

from PySide6.QtCore import QSignalBlocker, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout
from .i18n_widgets import Label, Button, ComboBox, CheckBox, SpinBox, MessageBox
from .i18n import tr
from .unit_fields import preserve_quantity
from ne501.syringe import FLOW_UL_MIN, format_diameter
from ne501.controller import CommandCancelled, prime_rate_ml_hr, choose_program_volume_unit
from ne501.pump_numbers import normalize_rate
from ne501.manual_program import PrimingSettings, ManualProof, write_manual_program, hold_motor


class PrimingControl(QWidget):
    def __init__(self, owner, panel):
        super().__init__()
        self.owner, self.panel = owner, panel
        self.pending = False
        self.validation_error = ''
        box = QVBoxLayout(self); box.setContentsMargins(0, 4, 0, 4)
        self.toggle = CheckBox('Priming / purge')
        box.addWidget(self.toggle)
        self.body = QWidget(); grid = QGridLayout(self.body); grid.setContentsMargins(4, 4, 4, 4)
        self.mode = ComboBox()
        self.mode.addItem('Five speed presets', 'PRESET'); self.mode.addItem('Custom rate', 'CUSTOM')
        self.custom_rate = SpinBox(); self.custom_rate.setDecimals(4); self.custom_rate.setRange(0,9999)
        self.custom_rate.setSpecialValueText(tr('Enter rate'))
        self.rate_unit = ComboBox()
        for label, code in (('µL/min','UM'),('mL/min','MM'),('µL/hr','UH'),('mL/hr','MH')):
            self.rate_unit.addItem(label,code)
        self.direction = ComboBox(); self.direction.addItem('Infuse','INF'); self.direction.addItem('Withdraw','WDR')
        self.volume = panel.prime_volume_input; self.volume.setMinimum(0); self.volume.setValue(0)
        self.volume.setSpecialValueText(tr('Enter volume'))
        self.volume_unit = panel.prime_volume_unit_combo
        self.follow = CheckBox('Then start formal delivery')
        self.rate_info = Label(); self.rate_info.setWordWrap(True)
        self.start = Button('Start priming only'); self.start.setObjectName('runButton')
        self.notice = Label(); self.notice.setWordWrap(True); self.notice.setObjectName('secondaryLabel')
        grid.addWidget(self.mode,0,0,1,2)
        grid.addWidget(panel.prime_speed_combo,1,0,1,2)
        grid.addWidget(self.custom_rate,2,0); grid.addWidget(self.rate_unit,2,1)
        grid.addWidget(Label('Direction'),3,0); grid.addWidget(self.direction,3,1)
        grid.addWidget(Label('Priming target volume'),4,0,1,2)
        grid.addWidget(self.volume,5,0); grid.addWidget(self.volume_unit,5,1)
        grid.addWidget(self.rate_info,6,0,1,2); grid.addWidget(self.follow,7,0,1,2)
        grid.addWidget(self.start,8,0,1,2); grid.addWidget(self.notice,9,0,1,2)
        box.addWidget(self.body); self.body.hide()
        self.toggle.toggled.connect(self.body.setVisible)
        self.toggle.toggled.connect(lambda checked:QTimer.singleShot(0,lambda:owner.editor_scroll.ensureWidgetVisible(self.mode,12,12)) if checked else None)
        self.start.clicked.connect(lambda: owner.start_station_priming(panel.address))
        preserve_quantity(self.custom_rate,self.rate_unit,FLOW_UL_MIN,lambda text: self.notice.setText(text))
        for widget in (self.mode,self.rate_unit,self.direction,self.volume_unit,panel.prime_speed_combo):
            widget.currentIndexChanged.connect(owner.refresh_group_controls)
        for widget in (self.custom_rate,self.volume):
            widget.valueChanged.connect(owner.refresh_group_controls)
            widget.lineEdit().textEdited.connect(self.text_pending)
            widget.editingFinished.connect(self.finish_input)
        self.custom_rate.valueChanged.connect(lambda *_: self.mode.setCurrentIndex(1))
        self.follow.toggled.connect(owner.refresh_group_controls)

    def text_pending(self,*_):
        self.pending = True; self.owner.refresh_group_controls()

    def finish_input(self):
        self.pending = not self.volume.hasAcceptableInput() or self.mode.currentData()=='CUSTOM' and not self.custom_rate.hasAcceptableInput()
        self.owner.refresh_group_controls()

    def commit_input(self):
        fields = [self.volume] + ([self.custom_rate] if self.mode.currentData()=='CUSTOM' else [])
        if all(field.hasAcceptableInput() for field in fields):
            for field in fields:field.interpretText()
            self.pending = False
        self.validation_error = ''
        try:self.snapshot()
        except ValueError as exc:self.validation_error = str(exc)

    def snapshot(self):
        diameter = self.owner.preparation.plans[self.panel.address].diameter
        if self.pending or diameter is None or not self.volume.hasAcceptableInput() or self.volume.value()<=0:
            return None
        preset = self.panel.prime_speed_combo.currentData() if self.mode.currentData()=='PRESET' else None
        if not preset and (not self.custom_rate.hasAcceptableInput() or self.custom_rate.value()<=0):
            return None
        settings = PrimingSettings(prime_rate_ml_hr(diameter,preset) if preset else self.custom_rate.value(),
                                  'MH' if preset else self.rate_unit.currentData(),self.volume.value(),
                                  self.volume_unit.currentData(),self.direction.currentData(),self.follow.isChecked(),preset)
        settings.validate()
        return settings

    def refresh(self):
        p = self.panel
        editable = self.owner.manual_mode() and not p.running and not p.busy and not p.stop_pending
        preset = self.mode.currentData()=='PRESET'
        self.panel.prime_speed_combo.setVisible(preset)
        self.custom_rate.setVisible(not preset); self.rate_unit.setVisible(not preset)
        for widget in (self.mode,self.panel.prime_speed_combo,self.custom_rate,self.rate_unit,
                       self.volume,self.volume_unit,self.direction,self.follow):
            widget.setEnabled(editable)
        self.validation_error = ''
        try:settings = self.snapshot()
        except ValueError as exc:
            settings = None;self.validation_error = str(exc)
        if settings:
            from .pump_panel import RATE_LABELS
            self.rate_info.setText(f'Priming: {settings.rate:.5g} {RATE_LABELS[settings.rate_unit]} · {settings.volume:g} {"µL" if settings.volume_unit=="UL" else "mL"}')
        else:
            self.rate_info.setText('Enter a priming rate and finite target volume when needed.')
        blocker = self.owner.station_priming_blocker(p.address)
        self.start.setEnabled(not blocker)
        paused=p.last_status=='P' and p.station_phase==3 and p.station_context in ('priming','priming_chain')
        self.start.setText('Resume priming' if paused else 'Prime then deliver' if self.follow.isChecked() else 'Start priming only')
        self.notice.setText(blocker or 'Priming is explicit. Formal start and resume never repeat priming.')


class SetupSummary(QWidget):
    """Read-only hardware summary; all syringe inputs live in step 2."""
    def __init__(self, owner, panel):
        super().__init__(); self.owner, self.panel = owner, panel
        box = QVBoxLayout(self); box.setContentsMargins(0, 0, 0, 4)
        box.addWidget(panel.diameter_status)
        panel.change_diameter_button.setText('Edit syringe & tubing in step 2')
        box.addWidget(panel.change_diameter_button)
        self.tubing_status = Label(); self.tubing_status.setWordWrap(True)
        box.addWidget(self.tubing_status)
        self.confirm_ready = Button('Priming checked · tubing ready')
        self.confirm_ready.clicked.connect(lambda: owner.change_tubing(panel.address, 'done'))
        box.addWidget(self.confirm_ready)

    def refresh(self):
        p, owner = self.panel, self.owner
        choice = owner.preparation.tubing[p.address]
        text = {'pending':'Choose preparation status', 'needed':'Connected · needs priming',
                'done':'Tubing checked · ready', 'skipped':'Skip priming · user confirmed'}[choice]
        self.tubing_status.setText(text)
        finished = p.station_context in ('priming', 'priming_chain') and p.last_status in ('P', 'S')
        self.confirm_ready.setVisible(choice == 'needed' and finished)
        self.confirm_ready.setEnabled(owner.manual_mode() and not p.busy and not p.stop_pending)


class ManualStationController:
    def attach_manual_station(self):
        self.station_proofs={}
        self.station_ready=False
        for panel in self.panels.values():
            panel.station_managed=True
            panel.station_context=None
            panel.station_phase=None
            panel.station_priming_settings=None
            panel.setup_summary=SetupSummary(self,panel)
            panel.diameter_input.setReadOnly(True)
            panel.priming_control=PrimingControl(self,panel)
            panel.editor.layout().insertWidget(3,panel.setup_summary)
            panel.editor.layout().insertWidget(6,panel.priming_control)
            panel.new_dose_requested.connect(lambda a:self.start_station(a,fresh=True))
            panel.shared_setup_requested.disconnect()
            panel.shared_setup_requested.connect(lambda p=panel:self.open_station_setup(p.address))
            panel.run_button.show()
        self.station_ready=True

    def open_station_setup(self,address):
        self.select_pump(address)
        self.show_workflow_step(1)
        spin = self.workflow.diameter_inputs[address]
        spin.setFocus()
        self.workflow.stack.widget(1).ensureWidgetVisible(spin)

    def station_prime_snapshot(self,address):
        try:return self.panels[address].priming_control.snapshot()
        except ValueError as exc:
            self.panels[address].priming_control.validation_error=str(exc)
            return None

    def station_priming_blocker(self,address):
        if not self.manual_mode():return 'Switch to Manual mode to operate pumps.'
        panel=self.panels[address];plan=self.preparation.plans[address]
        if not plan.used:return 'Select this pump for this experiment.'
        if not self.can_write_panel(panel):return panel.configuration_blocker() or 'Wait for the device response.'
        if not self.preparation.mapping_confirmed:return 'Confirm the pump-to-inlet mapping.'
        if self.preparation.tubing[address]=='pending':return 'Confirm syringe clamping, tubing and the outlet before priming.'
        snapshot=self.station_prime_snapshot(address)
        if snapshot is None:return panel.priming_control.validation_error or 'Enter a priming rate and finite target volume when needed.'
        proof=self.station_proofs.get(address)
        if not self.diameter_matches_plan(address) or not proof or proof.priming!=snapshot:
            return 'Write and read back the priming settings first.'
        if snapshot.follow_delivery:
            return self.manual_start_blocker(address)
        return ''

    def refresh_station(self):
        if not getattr(self,'station_ready',False):return
        for address,panel in self.panels.items():
            panel.priming_control.refresh();panel.setup_summary.refresh()
            formal_ready=not self.manual_start_blocker(address)
            panel.run_button.setEnabled(formal_ready);panel.editor_run_button.setEnabled(formal_ready)
            phase=panel.station_phase
            is_formal=panel.station_context=='formal' or panel.station_context=='priming_chain' and phase==1
            paused=panel.last_status=='P' and is_formal and panel.settings_applied
            panel.run_button.setText('Resume' if paused else 'Start')
            panel.editor_run_button.setText('Resume delivery' if paused else 'Start delivery' if panel.current_settings().continuous else 'Start a new dose')
            panel.new_dose_button.setVisible(paused and not panel.current_settings().continuous)
            panel.new_dose_button.setEnabled(not self.manual_start_blocker(address))

    def write_station_programs(self,panels,overrides=None):
        if not self.manual_mode() or not panels:return
        plans=[]
        for panel in panels:
            a=panel.address;plan=self.preparation.plans[a]
            if not self.can_write_panel(panel) or not plan.used or plan.diameter is None or a in self._diameter_pending:return
            settings=(overrides or {}).get(a) or panel.validated_settings()
            if settings is None:return
            settings=replace(settings,prime_enabled=False)
            panel.priming_control.commit_input()
            prime=self.station_prime_snapshot(a)
            program=self.build_program_settings(panel,settings)
            try:
                normalize_rate(program.rate,program.rate_unit)
                if panel.priming_control.validation_error:
                    raise ValueError(panel.priming_control.validation_error)
                combined=replace(program,prime_enabled=True,prime_volume=prime.volume,prime_volume_unit=prime.volume_unit) if prime else program
                choose_program_volume_unit(combined)
            except ValueError as exc:
                self.show_nonmodal_warning('Invalid Settings',str(exc));return
            plans.append((a,settings,program,prime,plan))
        generations={p.address:self._pump_generation.get(p.address,0) for p in panels}
        for a,*_ in plans:self.invalidate_program_confirmation(a)
        controller=self.controller
        def action():
            results=[]
            for a,settings,program,prime,plan in plans:
                try:
                    diameter=controller.set_diameter(a,program.diameter_mm)
                    result=write_manual_program(controller,a,program,prime) if diameter.confirmed else None
                    results.append((a,diameter,result,None))
                except CommandCancelled:
                    results.append((a,None,None,'CANCELLED'));break
                except Exception as exc:results.append((a,None,None,str(exc)))
            return results
        def success(results):
            saved={a:(s,p,prime,plan) for a,s,p,prime,plan in plans}
            completed=set()
            for a,diameter,result,error in results:
                completed.add(a)
                if self._pump_generation.get(a,0)!=generations[a]:continue
                panel=self.panels[a];settings,program,prime,plan=saved[a]
                if error=='CANCELLED':
                    panel.set_last_response('Write interrupted by STOP; write and verify again.')
                    self.append_log(f'Pump {panel.index}: Write interrupted by STOP; write and verify again.')
                    continue
                if diameter:
                    self.log_response(a,'DIA '+format_diameter(program.diameter_mm),diameter.set_response)
                    self.log_response(a,'DIA',diameter.query_response)
                if result:self.process_results(result.commands)
                unchanged=plan==self.preparation.plans[a] and settings==panel.current_settings() and prime==self.station_prime_snapshot(a) and a not in self._diameter_pending
                if diameter and diameter.confirmed and result and result.verified and unchanged:
                    panel.confirm_diameter(program.diameter_mm)
                    panel.mark_settings_applied();panel.set_program_confirmation(result)
                    self.station_proofs[a]=ManualProof(settings,prime,program)
                    panel.station_priming_settings=prime
                    if prime:
                        self._prep_verified[a]=(a,prime)
                        self.preparation.preparation_amounts[a]=(prime.volume,prime.volume_unit)
                    panel.set_last_response('Device settings verified')
                else:
                    panel.invalidate_diameter('Device settings changed or verification failed.')
                    if error:panel.set_online(False)
                    self.show_nonmodal_warning('Write result',error or (result.message if result else 'Device verification failed.'))
            if any(item[3]=='CANCELLED' for item in results):
                for a in saved:
                    if a not in completed and self._pump_generation.get(a,0)==generations[a]:
                        self.panels[a].set_last_response('Not sent after STOP request')
            self.refresh_group_controls()
        self.run_task(action,success,panels=panels,allow_partial=True)

    def start_station(self,address,fresh=False,priming=False):
        self.start_station_group([self.panels[address]],fresh=fresh,priming=priming)

    def start_station_priming(self,address):
        self.start_station(address,priming=True)

    def start_station_group(self,panels,*,fresh=False,priming=False):
        if not self.manual_mode() or not panels:return
        for p in panels:
            blocker=self.station_priming_blocker(p.address) if priming else self.manual_start_blocker(p.address)
            if blocker:self.refresh_group_controls();return
        controller=self.controller;generations={p.address:self._pump_generation.get(p.address,0) for p in panels}
        expected_phase=3 if priming else 1
        contexts=('priming','priming_chain') if priming else ('formal','priming_chain')
        resume_intent={p.address:not fresh and p.last_status=='P' and p.station_phase==expected_phase and p.station_context in contexts for p in panels}
        def action():
            outcomes=[]
            for p in panels:
                a=p.address
                try:
                    status=controller.send_command(a,'')
                    results=[(a,'STATUS',status)]
                    if not status.ok or status.status not in ('P','S'):
                        outcomes.append((a,results,None,'Confirm the pump is stopped before starting.'));break
                    phase=None
                    if status.status=='P':
                        response=controller.send_command(a,'PHN');results.append((a,'PHN',response))
                        if not response.ok or not response.data.strip().isdigit():
                            outcomes.append((a,results,None,'Cannot confirm the paused phase.'));break
                        phase=int(response.data)
                    resume=resume_intent[a]
                    if resume and (status.status!='P' or phase!=expected_phase):
                        outcomes.append((a,results,None,'Paused progress changed; review the device state before continuing.'));break
                    command='RUN' if resume else 'RUN 3' if priming else 'RUN 1'
                    if status.status=='P' and not resume:
                        response=controller.send_command(a,'STP');results.append((a,'STP',response))
                        if not response.ok or response.status!='S':
                            outcomes.append((a,results,None,'Cannot confirm program reset.'));break
                    response=controller.send_command(a,command);results.append((a,command,response))
                    proof=self.station_proofs.get(a)
                    kind=('priming_chain' if proof and proof.priming and proof.priming.follow_delivery else 'priming') if priming else 'formal'
                    outcomes.append((a,results,kind,None if response.ok else 'Pump rejected the start command.'))
                    if not response.ok:break
                except CommandCancelled:break
                except Exception as exc:outcomes.append((a,[],None,str(exc)));break
            return outcomes
        def success(outcomes):
            completed=set()
            for a,results,kind,error in outcomes:
                if self._pump_generation.get(a,0)!=generations[a]:continue
                completed.add(a)
                panel=self.panels[a]
                if kind:
                    panel.station_context=kind;panel.station_phase=3 if priming else 1
                    proof=self.station_proofs.get(a)
                    panel.station_priming_settings=proof.priming if proof else None
                    if kind=='priming':self.preparation.confirm_tubing(a,'needed')
                self.process_results(results)
                if error:
                    if not results:panel.set_online(False)
                    self.show_nonmodal_warning('Operation Failed',error)
            if any(item[3] for item in outcomes):
                for panel in panels:
                    if panel.address not in completed and self._pump_generation.get(panel.address,0)==generations[panel.address]:
                        panel.set_last_response('Not sent after an earlier group error')
            self.refresh_group_controls()
        self.run_task(action,success,panels=panels,allow_partial=True)

    def hold_station(self,addresses):
        if not self.controller or not self.controller.is_connected or not addresses:return
        self._packet_epoch+=1
        panels=[self.panels[a] for a in addresses]
        reset_addresses={p.address for p in panels if p.stop_requires_reset}
        for p in panels:
            self._pump_generation[p.address]=self._pump_generation.get(p.address,0)+1
            p.set_stop_pending()
        controller=self.controller
        def action():
            outcomes=[]
            for a in addresses:
                try:
                    results,status=hold_motor(controller,a,reset=a in reset_addresses);outcomes.append([a,results,status,None])
                except CommandCancelled:break
                except Exception as exc:outcomes.append([a,[],None,str(exc)])
            # Query progress only after every requested motor has been stopped.
            for item in outcomes:
                a,results,status,error=item
                if status and status.status=='P':
                    try:
                        response=controller.send_command(a,'PHN');results.append((a,'PHN',response))
                    except CommandCancelled:break
                    except Exception:pass
            return outcomes
        def success(outcomes):
            for a,results,status,error in outcomes:
                panel=self.panels[a];self.process_results(results)
                if status:
                    for _,command,response in results:
                        if command=='PHN' and response.ok and response.data.strip().isdigit():panel.station_phase=int(response.data)
                    panel.set_last_response('Motor stopped · progress retained' if status.status=='P' else 'STOP confirmed by pump response')
                else:
                    panel.set_online(False);panel.set_stop_pending()
                    panel.set_last_response(error or 'STOP not confirmed')
                    self.show_nonmodal_warning('STOP not confirmed',error or f'Check pump {panel.index}.')
            self.refresh_group_controls()
        self.run_task(action,success,panels=panels,priority=50,stop_operation=True)
