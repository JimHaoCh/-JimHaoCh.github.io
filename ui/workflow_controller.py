"""UI coordination for shared preparation; all motor commands stay explicit."""
from dataclasses import replace
import math

from ne501.preparation import PumpPlan, write_verified_program
from ne501.controller import ProgramSettings
from ne501.syringe import format_diameter
from ne501.mock_controller import MockNE501Controller
from .i18n import tr
from .i18n_widgets import MessageBox


class WorkflowController:
    def manual_mode(self):
        return self.mode_tabs.currentIndex() == 0

    def workflow_addresses(self):
        if self.manual_mode() and self.workflow.step == 4:
            return self.review_addresses()
        return self.preparation.used_addresses()

    def can_use_timeline(self):
        return bool(not self.pending_tasks and self.task_gate.ordinary_ticket() is not None
                    and not any(p.running or p.stop_pending for p in self.panels.values()))

    def invalidate_program_confirmation(self, address):
        # Rewriting DIA can change volume units even when its value is unchanged.
        # Invalidate before dispatch, including writes that fail or are cancelled.
        self._prep_verified.pop(address, None)
        self.panels[address].mark_settings_dirty()

    def show_nonmodal_warning(self, title, text):
        from .i18n_widgets import NonModalNotice
        notice = NonModalNotice(self, title, text)
        self._notice_windows.add(notice)
        notice.finished.connect(lambda *_: self._notice_windows.discard(notice))
        notice.show()

    def show_workflow_step(self, step):
        if not hasattr(self, 'workflow'):
            return
        timeline = self.timeline_editor
        if not self.manual_mode() and step == 2:
            step = 3
        if not self.manual_mode() and timeline and step != 3 and timeline.pending():
            self.workflow.next_hint.setText('Finish or cancel the current edit before changing preparation.')
            return
        if timeline and step != 3 and timeline.running:
            timeline.pause_preview()
        self.workflow.show_step(step)
        self.refresh_group_controls()

    def workflow_hint(self):
        used = self.workflow_addresses()
        if not self.preparation.used_addresses():
            return 'Next: choose the pumps used in this experiment.', 0
        if not used:
            return 'Select at least one active pump.', 3
        if self.pending_tasks:
            return 'Commands in progress · wait for the device response.', self.workflow.step
        manual = self.manual_mode()
        if manual:
            if not self.controller or not self.controller.is_connected:
                return 'Next: connect real pumps or choose Demo mode.', 0
            for address in used:
                panel = self.panels[address]
                index = self.addresses.index(address) + 1
                if not panel.online:
                    return f'P{index}: no response; check the connection and rescan.', 0
                if panel.last_status is None:
                    return f'P{index}: refresh status before continuing.', 0
                if panel.last_status == 'A':
                    return f'P{index}: alarm reported; inspect and stop the pump.', 0
                if panel.running or panel.stop_pending:
                    return f'P{index}: running or awaiting STOP; use the stop controls.', 4
            if not self.preparation.mapping_confirmed:
                return 'Next: confirm the pump-to-inlet mapping.', 0
        for address in used:
            if self.preparation.plans[address].diameter is None or address in self._diameter_pending:
                return f'P{self.addresses.index(address) + 1}: enter the syringe inside diameter.', 1
        if manual:
            for address in used:
                if self.preparation.tubing[address] not in ('done', 'skipped'):
                    return f'P{self.addresses.index(address) + 1}: confirm tubing preparation.', 2
        timeline = self.timeline_editor
        if not manual and timeline:
            if timeline.pending():
                return 'Finish or cancel the current edit before changing preparation.', 3
            if not timeline.model.included_clips():
                return 'Next: add a block to the timeline.', 3
            if not self.can_use_timeline():
                return 'Stop the pumps and wait for pending commands before using the timeline.', self.workflow.step
            if timeline.running:
                return 'Preview is playing; pause or stop playback.', 3
        if self.workflow.step < 3:
            return ('Next: enter the manual delivery settings.' if manual else 'Next: edit the timeline; include any initial priming as blocks.'), 3
        if self.workflow.step == 3:
            return 'Next: review targets, units and delivery amounts.', 4
        if not manual:
            return ('Review the timeline totals, then start the preview.' if timeline and timeline.checked
                    else 'Next: check the timeline before preview.'), 4
        return 'Review the listed targets before writing settings or starting.', 4

    def follow_workflow_hint(self):
        _, step = self.workflow_hint()
        used = self.workflow_addresses()
        self.show_workflow_step(step)
        target = None
        if step == 0:
            connected = self.controller is not None and self.controller.is_connected
            if not used:
                target = self.workflow.mapping_inputs[self.addresses[0]][0]
            elif not connected:
                target = self.connect_button
            elif any(not self.panels[a].online for a in used):
                target = self.scan_button
            elif any(self.panels[a].last_status is None for a in used):
                target = self.refresh_status_button
            elif any(self.panels[a].last_status == 'A' for a in used):
                target = self.emergency_button
            else:
                target = self.workflow.mapping_check
        elif step == 1:
            address = next((a for a in used if self.preparation.plans[a].diameter is None or a in self._diameter_pending), None)
            if address is not None:
                target = self.workflow.diameter_inputs[address]
        elif step == 2:
            address = next((a for a in used if self.preparation.tubing[a] not in ('done', 'skipped')), None)
            if address is not None:
                target = self.workflow.tubing_choices[address][1]
        elif step == 3 and self.mode_tabs.currentIndex() == 1 and self.timeline_editor:
            timeline = self.timeline_editor
            target = timeline.apply_button if timeline.dirty else timeline.duration_apply if timeline.duration_dirty else timeline.add_button
        if target is not None:
            target.setFocus()
            scroll = self.workflow.stack.currentWidget()
            if hasattr(scroll, 'ensureWidgetVisible'):
                scroll.ensureWidgetVisible(target)

    def update_preparation(self, address, **changes):
        if self._syncing_preparation:
            return False
        panel = self.panels[address]
        if panel.running or panel.busy:
            self.workflow.next_hint.setText('Stop this pump before changing preparation.')
            self.workflow.refresh()
            return False
        timeline = self.timeline_editor
        try:
            old = self.preparation.plans[address]
            new = replace(old, **changes)
            new.validate()
        except ValueError as exc:
            self.workflow.diameter_status[address].setText(str(exc))
            return False
        if old == new:
            self.refresh_group_controls()
            return True
        if timeline and (timeline.busy() or timeline.pending()) and not self.manual_mode():
            self.workflow.next_hint.setText('Finish or cancel the current edit before changing preparation.')
            return False
        if timeline and timeline.busy():
            timeline.stop_preview()
        self.preparation.update(address, **changes)
        self._prep_verified.pop(address, None)
        self._syncing_preparation = True
        try:
            if timeline:
                plans = [self.preparation.plans[a] for a in self.addresses]
                timeline.set_preparation([p.diameter for p in plans], [p.used for p in plans],
                                         [p.fluid for p in plans], [p.inlet for p in plans], preserve_draft=True)
        finally:
            self._syncing_preparation = False
        self.refresh_group_controls()
        return True

    def sync_preparation_from_timeline(self):
        if self._syncing_preparation or not self.timeline_editor:
            return
        self._syncing_preparation = True
        try:
            model = self.timeline_editor.model
            for i, address in enumerate(self.addresses):
                old = self.preparation.plans[address]
                self.preparation.update(address, used=model.used[i], diameter=model.diameters[i],
                                        fluid=model.names[i], inlet=model.inlets[i])
                if self.preparation.plans[address] != old:
                    self._diameter_pending.discard(address)
                    self._prep_verified.pop(address, None)
        finally:
            self._syncing_preparation = False
        self.refresh_group_controls()

    def diameter_text_pending(self, address):
        self._diameter_pending.add(address)
        self.panels[address].mark_settings_dirty()
        self.refresh_group_controls()

    def commit_diameter(self, address, spin):
        try:
            if not spin.hasAcceptableInput():
                raise ValueError('Finish entering a valid inside diameter.')
            spin.interpretText()
            value = spin.value() or None
            if value is not None:
                format_diameter(value)
            if self.update_preparation(address, diameter=value):
                self._diameter_pending.discard(address)
        except ValueError as exc:
            self._diameter_pending.add(address)
            self.workflow.diameter_status[address].setText(str(exc))
            return
        self.refresh_group_controls()

    def write_plan_diameter(self, address):
        if not self.manual_mode():
            return
        spin = self.workflow.diameter_inputs[address]
        self.commit_diameter(address, spin)
        plan = self.preparation.plans[address]
        if address not in self._diameter_pending and plan.used and plan.diameter is not None:
            self.set_diameter(address, plan.diameter)

    def adopt_diameter_readbacks(self):
        for address in self.preparation.used_addresses():
            value = self.panels[address].confirmed_diameter
            if value is not None:
                self.update_preparation(address, diameter=value)

    def diameter_matches_plan(self, address):
        plan = self.preparation.plans[address]
        panel = self.panels[address]
        return bool(panel.online and plan.diameter is not None and panel.confirmed_diameter is not None
                    and address not in self._diameter_pending
                    and math.isclose(plan.diameter, panel.confirmed_diameter, rel_tol=0, abs_tol=1e-9))

    def can_write_panel(self, panel):
        return bool(self.manual_mode() and self.controller and self.controller.is_connected and panel.online and not panel.busy
                    and not panel.running and not panel.stop_pending and panel.last_status not in (None, 'A')
                    and self.task_gate.ordinary_ticket() is not None)

    def manual_start_blocker(self, address):
        if not self.manual_mode():
            return 'Switch to Manual mode to operate pumps.'
        if address in self._diameter_pending:
            return 'Finish entering a valid inside diameter.'
        blocker = self.preparation.physical_blocker(address)
        if blocker:
            return blocker
        if not self.diameter_matches_plan(address):
            return 'Device diameter confirmation pending.'
        return self.panels[address].configuration_blocker() or ('' if self.panels[address].settings_applied else 'Apply settings first')

    def confirm_mapping(self, checked):
        if not self.workflow.updating:
            self.preparation.mapping_confirmed = checked
            self.refresh_group_controls()

    def change_tubing(self, address, choice):
        if self.workflow.updating or not self.manual_mode():
            return
        panel = self.panels[address]
        if panel.running or panel.busy:
            return
        self.preparation.confirm_tubing(address, choice)
        if choice == 'needed':
            self.workflow.prep_toggle.setChecked(True)
            self.workflow.prep_pump.setCurrentIndex(self.workflow.prep_pump.findData(address))
        self.refresh_group_controls()

    def load_example_workflow(self):
        if self.pending_tasks or any(p.running for p in self.panels.values()):
            self.workflow.next_hint.setText('Stop this pump before changing preparation.')
            return
        if self.timeline_editor:
            self.timeline_editor.load_demo()
            self.mode_tabs.setCurrentIndex(1)
            self.show_workflow_step(3)

    def reset_experiment_confirmation(self):
        self.preparation.reset_session()
        self._diameter_pending.clear()
        self._prep_verified.clear()
        for panel in self.panels.values():
            panel.invalidate_diameter('New experiment · device confirmation required.')
        self.refresh_group_controls()

    def review_addresses(self):
        scope = self.workflow.review_scope.currentData()
        if scope == 'single':
            return [self.selected_address] if self.preparation.plans[self.selected_address].used else []
        if scope == 'group':
            return [p.address for p in self.active_panels() if self.preparation.plans[p.address].used]
        return self.preparation.used_addresses()

    def write_review(self):
        if not self.manual_mode():
            return
        self.write_panel_programs([self.panels[a] for a in self.review_addresses()])

    def review_single(self, address):
        self.select_pump(address)
        self.mode_tabs.setCurrentIndex(0)
        self.workflow.review_scope.setCurrentIndex(self.workflow.review_scope.findData('single'))
        self.show_workflow_step(4)

    def review_group(self):
        self.mode_tabs.setCurrentIndex(0)
        self.workflow.review_scope.setCurrentIndex(self.workflow.review_scope.findData('group'))
        self.show_workflow_step(4)

    def start_review(self):
        if not self.manual_mode():
            return
        addresses = self.review_addresses()
        if not addresses or any(self.manual_start_blocker(a) for a in addresses):
            self.refresh_group_controls()
            return
        self.group_command([self.panels[a] for a in addresses], 'RUN 1')

    def check_review_flow(self):
        if not self.manual_mode() and self.can_use_timeline() and self.timeline_editor:
            self.timeline_editor.check_flow()

    def play_review_flow(self):
        if self.manual_mode() or not self.timeline_editor or not self.timeline_editor.can_start_preview():
            return
        self.show_workflow_step(3)
        if self.timeline_editor:
            self.timeline_editor.start_preview()

    def write_panel_programs(self, panels, overrides=None):
        if not self.manual_mode() or not panels:
            return
        plan = []
        for panel in panels:
            p = self.preparation.plans[panel.address]
            if not p.used or p.diameter is None or panel.address in self._diameter_pending or not self.can_write_panel(panel):
                self.refresh_group_controls()
                return
            settings = (overrides or {}).get(panel.address) or panel.validated_settings()
            if settings is None:
                return
            plan.append((panel.address, self.build_program_settings(panel, settings), settings, p))
        for address, *_ in plan:
            self.invalidate_program_confirmation(address)
        controller = self.controller
        ticket = self.task_gate.ordinary_ticket()
        generations = {p.address: self._pump_generation.get(p.address, 0) for p in panels}
        def current(address):
            return ticket is not None and self.task_gate.is_current(ticket) and self._pump_generation.get(address, 0) == generations[address]
        def action():
            results = []
            for address, program, settings, p in plan:
                try:
                    result = write_verified_program(controller, address, program, lambda a=address: current(a))
                    results.append((address, result, None))
                except Exception as exc:
                    results.append((address, None, str(exc)))
            return results
        def success(results):
            snapshots = {a: (settings, p) for a, _, settings, p in plan}
            failed = []
            for address, result, error in results:
                panel = self.panels[address]
                settings, p = snapshots[address]
                if error:
                    panel.set_online(False)
                    panel.set_last_response(error)
                    failed.append(address)
                    continue
                if result.diameter:
                    self.log_response(address, 'DIA ' + format_diameter(p.diameter), result.diameter.set_response)
                    self.log_response(address, 'DIA', result.diameter.query_response)
                    panel.update_from_status(result.diameter.query_response.status)
                if result.program:
                    self.process_results(result.program.commands)
                unchanged = p == self.preparation.plans[address] and settings == panel.current_settings() and address not in self._diameter_pending
                if result.verified and unchanged:
                    panel.confirm_diameter(p.diameter)
                    panel.mark_settings_applied()
                    panel.set_program_confirmation(result.program)
                    panel.set_last_response('Device settings verified')
                    self._prep_verified.pop(address, None)
                else:
                    panel.invalidate_diameter('Device settings changed or verification failed.')
                    panel.set_last_response(result.message)
                    failed.append(address)
            if failed:
                MessageBox.warning(self, 'Write result', tr('Device verification failed for addresses: ') + ', '.join(f'{a:02d}' for a in failed))
            self.refresh_group_controls()
        self.run_task(action, success, panels=panels)

    def preparation_inputs_changed(self, *_):
        if hasattr(self, 'workflow') and not self.workflow.updating:
            if _ and isinstance(_[0], str):
                self._prep_input_pending = True
            self.refresh_preparation_controls()

    def finish_preparation_input(self):
        self._prep_input_pending = not all(w.hasAcceptableInput() for w in (self.workflow.prep_rate, self.workflow.prep_volume))
        self.refresh_preparation_controls()

    def preparation_target_changed(self, *_):
        if hasattr(self, 'workflow'):
            self.refresh_preparation_controls()

    def preparation_snapshot(self):
        view = self.workflow
        if self._prep_input_pending:
            return None
        address = view.prep_pump.currentData()
        if address is None:
            return None
        plan = self.preparation.plans[address]
        if plan.diameter is None or not all(w.hasAcceptableInput() for w in (view.prep_rate, view.prep_volume)):
            return None
        if view.prep_rate.value() <= 0 or view.prep_volume.value() <= 0:
            return None
        settings = ProgramSettings(view.prep_rate.value(), view.prep_rate_unit.currentData(),
                                   view.prep_direction.currentData(), False,
                                   view.prep_volume.value(), view.prep_volume_unit.currentData(),
                                   False, 1, 'UL', 'LOW', plan.diameter)
        return address, settings

    def refresh_preparation_controls(self):
        if not hasattr(self, 'workflow'):
            return
        view = self.workflow
        snapshot = self.preparation_snapshot()
        address = view.prep_pump.currentData()
        panel = self.panels.get(address)
        writable = self.can_write_preparation(snapshot)
        ready = self.can_start_preparation(snapshot)
        view.prep_write.setEnabled(writable)
        view.prep_start.setEnabled(ready)
        view.prep_stop.setEnabled(bool(panel and self.controller and self.controller.is_connected))
        for widget in (view.prep_pump, view.prep_rate, view.prep_rate_unit, view.prep_volume, view.prep_volume_unit, view.prep_direction):
            widget.setEnabled(self.manual_mode() and (not panel or not panel.running and not panel.busy))
        if snapshot:
            _, s = snapshot
            from .pump_panel import RATE_LABELS
            direction = tr('Infuse' if s.direction == 'INF' else 'Withdraw')
            volume_unit = 'µL' if s.volume_unit == 'UL' else 'mL'
            view.prep_summary.setText(self.workflow.identity(address) + f' | {direction} | {s.rate:g} {RATE_LABELS[s.rate_unit]} | {s.volume:g} {volume_unit}')
        else:
            view.prep_summary.setText('Choose a pump and enter a positive priming rate and target volume.')

    def can_write_preparation(self, snapshot=None):
        snapshot = snapshot if snapshot is not None else self.preparation_snapshot()
        if not self.manual_mode() or not snapshot:
            return False
        address, _ = snapshot
        return bool(self.preparation.plans[address].used and self.can_write_panel(self.panels[address])
                    and address not in self._diameter_pending and self.preparation.mapping_confirmed)

    def can_start_preparation(self, snapshot=None):
        snapshot = snapshot if snapshot is not None else self.preparation_snapshot()
        return bool(snapshot and self.can_write_preparation(snapshot)
                    and self._prep_verified.get(snapshot[0]) == snapshot
                    and self.diameter_matches_plan(snapshot[0]))

    def write_preparation(self):
        snapshot = self.preparation_snapshot()
        if not self.can_write_preparation(snapshot):
            return
        address, settings = snapshot
        panel = self.panels[address]
        self.invalidate_program_confirmation(address)
        controller = self.controller
        ticket = self.task_gate.ordinary_ticket()
        generation = self._pump_generation.get(address, 0)
        def current():
            return ticket is not None and self.task_gate.is_current(ticket) and self._pump_generation.get(address, 0) == generation
        def success(result):
            if result.diameter:
                self.log_response(address, 'DIA ' + format_diameter(settings.diameter_mm), result.diameter.set_response)
                self.log_response(address, 'DIA', result.diameter.query_response)
            if result.program:
                self.process_results(result.program.commands)
            if result.verified and self.preparation_snapshot() == snapshot:
                panel.confirm_diameter(settings.diameter_mm)
                self._prep_verified[address] = snapshot
                self.preparation.confirm_tubing(address, 'needed')
                self.preparation.preparation_amounts[address] = (settings.volume, settings.volume_unit)
            else:
                self._prep_verified.pop(address, None)
                panel.invalidate_diameter('Device settings changed or verification failed.')
                MessageBox.warning(self, 'Write result', result.message)
            self.refresh_group_controls()
        self.run_task(lambda: write_verified_program(controller, address, settings, current), success, panels=[panel])

    def start_preparation(self):
        snapshot = self.preparation_snapshot()
        if self.can_start_preparation(snapshot):
            address, _ = snapshot
            self.preparation.confirm_tubing(address, 'needed')
            self.run_single_command(address, 'RUN 1', self.panels[address])

    def stop_preparation(self):
        address = self.workflow.prep_pump.currentData()
        if address is not None:
            self.stop_single(address)
