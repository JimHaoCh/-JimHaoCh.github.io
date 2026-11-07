"""Same-page controls, native progress, explicit priming and packet cancellation.

All device tests use simulated I/O. Fake clocks avoid timing-dependent dosing.
"""
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint
from ne501.controller import NE501Controller, ProgramSettings, CommandCancelled
from ne501.manual_program import PrimingSettings, write_manual_program, hold_motor
from ne501.mock_controller import MockNE501Controller
from ui.i18n import manager
from ui.style import build_stylesheet
import test_workflow_141 as helpers
from test_controller_features import FakeSerial
from test_gui_dispatch_logic import FakeWorker, FakeCallbacks, FakePool


class Clock:
    now=0.
    def __call__(self):return self.now
    def advance(self,seconds):self.now+=seconds


def formal(continuous=False,volume=10,unit='UL'):
    return ProgramSettings(60,'UM','INF',continuous,volume,unit,False,1,'UL','LOW',10)


class ManualProgramTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.controller=MockNE501Controller([0,1],latency=0,clock=self.clock)
        self.controller.connect()

    def test_formal_entry_never_replays_priming_and_chain_is_explicit(self):
        prime=PrimingSettings(120,'UM',2,'UL','WDR',True)
        result=write_manual_program(self.controller,0,formal(),prime)
        self.assertTrue(result.verified,result.message)
        self.assertFalse(any(c.startswith('RUN') for _,c,_ in result.commands))
        self.controller.send_command(0,'RUN 1')
        self.clock.advance(10)
        self.assertEqual(self.controller.send_command(0,'').status,'S')
        state=self.controller.pumps[0]
        self.assertAlmostEqual(state.infused_ml,.01)
        self.assertEqual(state.withdrawn_ml,0)
        self.controller.send_command(0,'RUN 3')
        self.clock.advance(2)
        self.assertEqual(self.controller.send_command(0,'').status,'I')
        self.assertEqual(state.current_phase,1)
        self.assertAlmostEqual(state.withdrawn_ml,.002)
        self.assertAlmostEqual(state.phase_ml,.001)

    def test_finite_pause_retains_quantity_and_resume_delivers_only_remainder(self):
        self.assertTrue(write_manual_program(self.controller,0,formal()).verified)
        self.controller.send_command(0,'RUN 1')
        self.clock.advance(4)
        results,status=hold_motor(self.controller,0)
        self.assertEqual(status.status,'P')
        self.assertEqual([c for _,c,_ in results],['STATUS','STP'])
        self.assertAlmostEqual(self.controller.pumps[0].phase_ml,.004)
        self.clock.advance(100)
        # Repeated STOP must preserve the paused progress.
        self.assertEqual([c for _,c,_ in hold_motor(self.controller,0)[0]],['STATUS'])
        self.controller.send_command(0,'RUN')
        self.clock.advance(6)
        self.assertEqual(self.controller.send_command(0,'').status,'S')
        self.assertAlmostEqual(self.controller.pumps[0].infused_ml,.01)

    def test_new_dose_and_global_style_reset_start_from_zero(self):
        write_manual_program(self.controller,0,formal())
        self.controller.send_command(0,'RUN 1');self.clock.advance(4)
        hold_motor(self.controller,0)
        self.controller.send_command(0,'STP')
        self.controller.send_command(0,'RUN 1');self.clock.advance(10)
        self.assertEqual(self.controller.send_command(0,'').status,'S')
        self.assertAlmostEqual(self.controller.pumps[0].infused_ml,.014)

    def test_prime_only_auto_stops_without_starting_formal(self):
        prime=PrimingSettings(120,'UM',2,'UL','WDR')
        self.assertTrue(write_manual_program(self.controller,0,formal(),prime).verified)
        self.controller.send_command(0,'RUN 3');self.clock.advance(2)
        self.assertEqual(self.controller.send_command(0,'').status,'S')
        self.assertEqual(self.controller.pumps[0].infused_ml,0)
        self.assertAlmostEqual(self.controller.pumps[0].withdrawn_ml,.002)

    def test_shared_native_volume_unit_and_five_presets_are_verified(self):
        for level in ('MIN','LOW','MEDIUM','HIGH','MAX'):
            with self.subTest(level=level):
                prime=PrimingSettings(1,'MH',.0005,'UL','INF',preset=level)
                result=write_manual_program(self.controller,0,formal(volume=.05,unit='ML'),prime)
                self.assertTrue(result.verified,result.message)
                self.assertEqual(result.program_volume_unit,'UL')
                self.assertEqual(self.controller.pumps[0].phases[1].volume,50)
                self.assertGreater(result.prime_rate_ml_hr,0)

    def test_continuous_formal_and_ml_priming_set_one_global_ml_unit(self):
        result=write_manual_program(self.controller,0,formal(continuous=True),PrimingSettings(10,'UM',10,'ML','INF'))
        self.assertTrue(result.verified,result.message)
        self.assertEqual(self.controller.pumps[0].volume_unit,'ML')
        self.assertEqual(self.controller.pumps[0].phases[1].volume,0)
        self.assertEqual(self.controller.pumps[0].phases[3].volume,10)

    def test_small_diameter_preset_equivalent_unit_is_verified(self):
        self.controller.set_diameter(0,.1)
        result=write_manual_program(self.controller,0,replace(formal(),diameter_mm=.1,rate=.01,rate_unit='UH'),PrimingSettings(.001,'MH',1,'UL','INF',preset='MIN'))
        self.assertTrue(result.verified,result.message)

    def test_priming_rate_or_jump_readback_mismatch_blocks_verification(self):
        original=self.controller.send_command
        for mismatch in ('RAT','FUN'):
            with self.subTest(mismatch=mismatch):
                def send(a,c):
                    response=original(a,c)
                    phase=self.controller.pumps[a].current_phase
                    if (c=='RAT' and phase==3 and mismatch=='RAT') or (c=='FUN' and phase==4 and mismatch=='FUN'):
                        return replace(response,data='999UM' if mismatch=='RAT' else 'JMP02')
                    return response
                with patch.object(self.controller,'send_command',side_effect=send):
                    result=write_manual_program(self.controller,0,formal(),PrimingSettings(10,'UM',5,'UL','INF',True))
                self.assertFalse(result.verified)

    def test_serial_write_checks_cancellation_between_packets(self):
        controller=NE501Controller(inter_command_delay=0)
        controller._serial=FakeSerial(b'\x0200S\x03')
        live=True
        with controller.cancellable(lambda:live):
            controller.send_command(0,'')
            live=False
            with self.assertRaises(CommandCancelled):controller.send_command(0,'RUN 1')
        self.assertNotIn(b'RUN',controller._serial.written)

    def test_nested_cancellation_guard_restores_outer_scope(self):
        with self.controller.cancellable(lambda:True):
            with self.controller.cancellable(lambda:False):
                with self.assertRaises(CommandCancelled):self.controller.send_command(0,'RUN 1')
            self.assertTrue(self.controller.send_command(0,'').ok)

    def test_status_timeout_still_attempts_stop_and_confirms_the_response(self):
        self.controller.send_command(0,'RUN 1');original=self.controller.send_command
        sent=[]
        def send(a,c):
            sent.append(c)
            if not c:raise TimeoutError('Injected status timeout')
            return original(a,c)
        with patch.object(self.controller,'send_command',side_effect=send):results,status=hold_motor(self.controller,0)
        self.assertEqual(sent,['','STP']);self.assertEqual(status.status,'P')

    def test_failed_stop_never_produces_a_confirmed_stopped_state(self):
        self.controller.send_command(0,'RUN 1');original=self.controller.send_command
        def send(a,c):
            if c=='STP':return replace(original(a,''),data='?NA',error_code='NA')
            return original(a,c)
        with patch.object(self.controller,'send_command',side_effect=send):results,status=hold_motor(self.controller,0)
        self.assertIsNone(status)
        self.assertEqual(self.controller.pumps[0].status,'I')


class ManualStationTests(unittest.TestCase):
    setUpClass=classmethod(helpers.ModeWorkflowTests.setUpClass.__func__)
    setUp=helpers.ModeWorkflowTests.setUp
    tearDown=helpers.ModeWorkflowTests.tearDown
    idle=helpers.ModeWorkflowTests.idle
    ready=helpers.ModeWorkflowTests.ready

    def write(self,*addresses):
        self.win.write_station_programs([self.win.panels[a] for a in addresses]);self.idle()
        for a in addresses:self.assertTrue(self.win.panels[a].settings_applied)

    def prime(self,address=0,follow=False):
        p=self.win.panels[address];control=p.priming_control
        control.custom_rate.setValue(120);control.volume.setValue(2)
        control.follow.setChecked(follow);control.toggle.setChecked(True)
        return control

    def test_console_is_three_stages_with_one_priming_tool(self):
        self.ready((0,1));w=self.win;w.show_workflow_step(3)
        self.assertEqual([i for i,b in enumerate(w.workflow.steps) if b.isVisible()],[0,1,3])
        p=w.panels[0]
        self.assertTrue(p.run_button.isVisible());self.assertTrue(p.stop_button.isVisible())
        self.assertTrue(p.prime_details.isHidden());self.assertTrue(p.prime_enabled_checkbox.isHidden())
        self.assertIs(w.workflow.prep_volume,p.priming_control.volume)
        w.show_workflow_step(4);self.assertEqual(w.workflow.step,3)
        w.show_workflow_step(2);self.assertEqual(w.workflow.step,1)

    def test_start_stop_resume_uses_same_page_and_never_rewrites(self):
        self.ready();w=self.win;w.show_workflow_step(3);self.prime();self.write(0)
        p=w.panels[0]
        with patch.object(w.controller,'send_command',wraps=w.controller.send_command) as sent:
            p.editor_run_button.click();self.idle()
            p.stop_button.click();self.idle()
            self.assertEqual(p.last_status,'P')
            self.assertEqual(p.editor_run_button.source_text,'Resume delivery')
            p.run_button.click();self.idle()
            commands=[c.args[1] for c in sent.call_args_list]
        self.assertEqual([c for c in commands if c.startswith('RUN')],['RUN 1','RUN'])
        self.assertFalse(any(c.startswith(('RAT ','VOL ','DIA ','PHN ')) for c in commands))
        self.assertEqual(w.workflow.step,3)

    def test_finite_resume_and_restart_full_dose_have_distinct_commands(self):
        self.ready();w=self.win;p=w.panels[0];p.mode_combo.setCurrentIndex(1)
        self.write(0);w.run_single(0);self.idle();w.stop_single(0);self.idle()
        self.assertFalse(p.new_dose_button.isHidden())
        with patch.object(w.controller,'send_command',wraps=w.controller.send_command) as sent:
            p.new_dose_button.click();self.idle()
        self.assertIn('RUN 1',[c.args[1] for c in sent.call_args_list])
        self.assertIn('STP',[c.args[1] for c in sent.call_args_list])

    def test_stale_native_resume_does_not_silently_start_a_new_dose(self):
        self.ready();w=self.win;self.write(0)
        w.run_single(0);self.idle();w.stop_single(0);self.idle()
        w.controller.send_command(0,'STP')
        with patch.object(w.controller,'send_command',wraps=w.controller.send_command) as sent:
            w.run_single(0);self.idle()
        self.assertFalse(any(c.args[1].startswith('RUN') for c in sent.call_args_list))
        self.assertEqual(w.panels[0].last_status,'S')

    def test_p1_running_does_not_block_p2_edit_write_start_or_stop(self):
        self.ready((0,1));w=self.win;self.write(0);w.run_single(0);self.idle()
        w.select_pump(1);p2=w.panels[1]
        self.assertTrue(p2.rate_input.isEnabled())
        p2.rate_input.setValue(2);self.write(1)
        with patch.object(w.controller,'send_command',wraps=w.controller.send_command) as sent:
            w.run_single(1);self.idle();w.stop_single(1);self.idle()
        self.assertTrue(w.panels[0].running)
        self.assertFalse(any(c.args[0]==0 and c.args[1]=='STP' for c in sent.call_args_list))

    def test_priming_draft_change_leaves_verified_formal_start_available(self):
        self.ready();w=self.win;p=w.panels[0];control=self.prime();self.write(0)
        control.volume.setValue(3)
        self.assertTrue(p.settings_applied);self.assertTrue(p.run_button.isEnabled())
        self.assertFalse(control.start.isEnabled())
        with patch.object(w.controller,'send_command',wraps=w.controller.send_command) as sent:
            w.start_preparation();self.idle()
        sent.assert_not_called()
        w.run_single(0);self.idle();self.assertTrue(p.running)

    def test_paused_priming_resumes_native_progress_without_repeating_full_volume(self):
        self.ready();w=self.win;clock=Clock();w.controller.clock=clock
        control=self.prime();self.write(0)
        w.start_preparation();self.idle();clock.advance(.5);w.stop_single(0);self.idle()
        self.assertEqual(control.start.source_text,'Resume priming')
        self.assertAlmostEqual(w.controller.pumps[0].phase_ml,.001)
        with patch.object(w.controller,'send_command',wraps=w.controller.send_command) as sent:
            w.start_preparation();self.idle()
        self.assertEqual([c.args[1] for c in sent.call_args_list if c.args[1].startswith('RUN')],['RUN'])
        clock.advance(.5);w.refresh_status();self.idle()
        self.assertEqual(w.panels[0].last_status,'S')
        self.assertAlmostEqual(w.controller.pumps[0].infused_ml,.002)

    def test_prime_only_keeps_tubing_confirmation_pending_and_formal_requires_user(self):
        self.ready();w=self.win;self.prime();w.change_tubing(0,'needed');self.write(0)
        self.assertTrue(w.panels[0].priming_control.start.isEnabled())
        self.assertTrue(w.manual_start_blocker(0))
        w.start_preparation();self.idle();w.stop_single(0);self.idle()
        self.assertEqual(w.preparation.tubing[0],'needed')
        w.change_tubing(0,'done');self.assertFalse(w.manual_start_blocker(0))

    def test_follow_priming_requires_ready_tubing_and_is_tracked_into_formal(self):
        self.ready();w=self.win;clock=Clock();w.controller.clock=clock
        control=self.prime(follow=True);self.write(0)
        w.change_tubing(0,'needed');self.assertFalse(control.start.isEnabled())
        w.change_tubing(0,'done');control.start.click();self.idle()
        self.assertEqual(w.panels[0].station_context,'priming_chain')
        clock.advance(2);w.refresh_status();self.idle()
        self.assertEqual(w.panels[0].station_phase,1)
        w.stop_single(0);self.idle()
        self.assertEqual(w.panels[0].editor_run_button.source_text,'Resume delivery')

    def test_stop_cancels_remainder_of_running_write_between_packets(self):
        self.ready();w=self.win;original=w.controller.send_command;commands=[];stopped=False
        def send(a,c):
            nonlocal stopped
            response=original(a,c);commands.append(c)
            if c=='PHN 1' and not stopped:
                stopped=True;w.stop_single(0)
            return response
        with patch.object(w.controller,'send_command',side_effect=send),patch('ui.main_window.FunctionWorker',FakeWorker),patch('ui.main_window.WorkerCallbacks',FakeCallbacks):
            w.thread_pool=FakePool();w.apply_single(0,w.panels[0].current_settings())
            while w.thread_pool.queue:w.thread_pool.run_next()
        boundary=commands.index('PHN 1')
        self.assertEqual(commands[boundary+1:],[''])
        self.assertFalse(w.panels[0].settings_applied)
        self.assertFalse(w.panels[0].busy)
        self.assertEqual(w.pending_tasks,0)

    def test_partial_group_start_retains_other_running_status_when_target_stopped(self):
        self.ready((0,1));w=self.win;self.write(0,1)
        original=w.controller.send_command;interrupted=False
        def send(a,c):
            nonlocal interrupted
            response=original(a,c)
            if a==0 and c=='RUN 1' and not interrupted:
                interrupted=True;w.stop_single(1)
            return response
        with patch.object(w.controller,'send_command',side_effect=send),patch('ui.main_window.FunctionWorker',FakeWorker),patch('ui.main_window.WorkerCallbacks',FakeCallbacks):
            w.thread_pool=FakePool();w.start_station_group([w.panels[0],w.panels[1]])
            while w.thread_pool.queue:w.thread_pool.run_next()
        self.assertTrue(w.panels[0].running)
        self.assertFalse(w.panels[1].running)

    def test_stop_all_interrupts_an_active_batch_before_any_more_settings_packets(self):
        self.ready((0,1));w=self.win;self.write(1);w.run_single(1);self.idle()
        original=w.controller.send_command;commands=[];interrupted=False
        def send(a,c):
            nonlocal interrupted
            response=original(a,c);commands.append((a,c))
            if a==0 and c=='PHN 1' and not interrupted:
                interrupted=True;w.emergency_stop()
            return response
        with patch.object(w.controller,'send_command',side_effect=send),patch('ui.main_window.FunctionWorker',FakeWorker),patch('ui.main_window.WorkerCallbacks',FakeCallbacks):
            w.thread_pool=FakePool();w.apply_single(0,w.panels[0].current_settings())
            while w.thread_pool.queue:w.thread_pool.run_next()
        boundary=commands.index((0,'PHN 1'))
        self.assertTrue(all(c in ('','STP') for _,c in commands[boundary+1:]))
        self.assertEqual({a for a,c in commands[boundary+1:]},set(w.addresses))
        self.assertTrue(all(p.last_status=='S' for p in w.panels.values()))
        self.assertFalse(w.panels[0].settings_applied)

    def test_overlapping_single_and_group_stops_finish_every_requested_motor(self):
        self.ready((0,1));w=self.win;self.write(0,1)
        w.start_station_group([w.panels[0],w.panels[1]]);self.idle()
        with patch('ui.main_window.FunctionWorker',FakeWorker),patch('ui.main_window.WorkerCallbacks',FakeCallbacks):
            w.thread_pool=FakePool();w.hold_station([0,1]);w.hold_station([0])
            while w.thread_pool.queue:w.thread_pool.run_next()
        self.assertEqual([w.panels[a].last_status for a in (0,1)],['P','P'])
        self.assertTrue(all(not w.panels[a].stop_pending and not w.panels[a].busy for a in (0,1)))

    def test_group_combines_native_resume_and_fresh_start_without_changing_edit_target(self):
        self.ready((0,1));w=self.win;self.write(0,1)
        w.run_single(0);self.idle();w.stop_single(0);self.idle()
        for a in (0,1):w.panels[a].set_active(True)
        w.select_pump(1)
        with patch.object(w.controller,'send_command',wraps=w.controller.send_command) as sent:
            w.run_active();self.idle()
        self.assertEqual([(c.args[0],c.args[1]) for c in sent.call_args_list if c.args[1].startswith('RUN')],[(0,'RUN'),(1,'RUN 1')])
        self.assertEqual(w.selected_address,1)
        self.assertEqual([p.address for p in w.active_panels()],[0,1])

    def test_single_stop_failure_keeps_unconfirmed_indicator_and_accessible_stop(self):
        self.ready();w=self.win;self.write(0);w.run_single(0);self.idle()
        original=w.controller.send_command
        def send(a,c):
            if c=='STP':raise TimeoutError('Injected STOP timeout')
            return original(a,c)
        with patch.object(w.controller,'send_command',side_effect=send):w.stop_single(0);self.idle()
        self.assertTrue(w.panels[0].stop_pending)
        self.assertTrue(w.panels[0].stop_button.isEnabled())
        self.assertIn('Stop unconfirmed: P1',w.execution_label.source_text)
        self.assertNotEqual(w.panels[0].last_response_source,'STOP confirmed by pump response')

    def test_invalid_input_keeps_stop_controls_enabled(self):
        self.ready();w=self.win;self.write(0);w.run_single(0);self.idle()
        p=w.panels[0];p.rate_input.lineEdit().setText('');p.rate_input.lineEdit().textEdited.emit('')
        self.assertTrue(p.stop_button.isEnabled());self.assertTrue(p.editor_stop_button.isEnabled())
        p.stop_button.click();self.idle();self.assertEqual(p.last_status,'P')

    def test_background_status_poll_preserves_other_pump_editing_and_can_queue_its_write(self):
        self.ready((0,1));w=self.win;self.write(0);w.run_single(0);self.idle()
        with patch('ui.main_window.FunctionWorker',FakeWorker),patch('ui.main_window.WorkerCallbacks',FakeCallbacks):
            w.thread_pool=FakePool();w.refresh_status()
            self.assertFalse(w.panels[1].busy);self.assertTrue(w.panels[1].rate_input.isEnabled())
            w.panels[1].rate_input.setValue(2);w.apply_single(1,w.panels[1].current_settings())
            while w.thread_pool.queue:w.thread_pool.run_next()
        self.assertTrue(w.panels[0].running);self.assertTrue(w.panels[1].settings_applied)
        self.assertEqual(w.pending_tasks,0)

    def test_single_stop_preempts_other_pump_active_configuration_between_packets(self):
        self.ready((0,1));w=self.win;self.write(0);w.run_single(0);self.idle()
        original=w.controller.send_command;commands=[];interrupted=False
        def send(a,c):
            nonlocal interrupted
            response=original(a,c);commands.append((a,c))
            if a==1 and c=='PHN 1' and not interrupted:
                interrupted=True;w.stop_single(0)
            return response
        with patch.object(w.controller,'send_command',side_effect=send),patch('ui.main_window.FunctionWorker',FakeWorker),patch('ui.main_window.WorkerCallbacks',FakeCallbacks):
            w.thread_pool=FakePool();w.apply_single(1,w.panels[1].current_settings())
            while w.thread_pool.queue:w.thread_pool.run_next()
        boundary=commands.index((1,'PHN 1'))
        self.assertTrue(all(a==0 and c in ('','STP','PHN') for a,c in commands[boundary+1:]))
        self.assertEqual(w.panels[0].last_status,'P')
        self.assertFalse(w.panels[1].settings_applied);self.assertTrue(w.panels[1].online)
        self.assertIn('Write interrupted by STOP',w.panels[1].last_response_source)

    def test_inline_syringe_drawer_stays_on_console_and_shares_model(self):
        self.ready();w=self.win;w.show_workflow_step(3);w.open_station_setup(0)
        drawer=w.panels[0].inline_setup
        self.assertTrue(drawer.toggle.isChecked());self.assertEqual(w.workflow.step,3)
        drawer.diameter.setValue(4.699);drawer.diameter.editingFinished.emit()
        self.assertEqual(w.preparation.plans[0].diameter,4.699)
        self.assertEqual(w.workflow.diameter_inputs[0].value(),4.699)
        drawer.tubing.setCurrentIndex(drawer.tubing.findData('done'))
        self.assertEqual(w.preparation.tubing[0],'done')

    def test_cancel_example_preserves_mode_page_and_draft(self):
        self.ready();w=self.win;w.show_workflow_step(3)
        before=w.timeline_editor.model.to_json()
        with patch.object(w.timeline_editor,'prepare_to_leave',return_value=False):w.load_example_workflow()
        self.assertEqual(w.mode_tabs.currentIndex(),0);self.assertEqual(w.workflow.step,3)
        self.assertEqual(w.timeline_editor.model.to_json(),before)

    def test_all_four_start_stop_controls_stay_visible_at_1024_and_130_percent(self):
        self.ready((0,1,2,3));w=self.win;w.show_workflow_step(3)
        self.write(0,1,2,3);w.run_single(0);self.idle();w.select_pump(1)
        shots=Path(__file__).resolve().parents[1]/'builds/ui-shots-source';shots.mkdir(parents=True,exist_ok=True)
        for language in ('zh_TW','en'):
            manager.set_language(language)
            for scale in (1.,1.3):
                w.ui_scale_combo.setCurrentIndex(w.ui_scale_combo.findData(scale))
                self.app.setStyleSheet(build_stylesheet(scale))
                for width in (1024,1366):
                    w.resize(width,768);self.app.processEvents();w.update_dashboard_density();self.app.processEvents()
                    viewport=w.panel_scroll.viewport()
                    for p in w.panels.values():
                        for button in (p.run_button,p.stop_button):
                            point=button.mapTo(viewport,QPoint(0,0))
                            self.assertTrue(button.isVisible())
                            self.assertTrue(viewport.rect().contains(point),(language,scale,width,point))
                            self.assertLessEqual(point.y()+button.height(),viewport.height())
                            self.assertLessEqual(point.x()+button.width(),viewport.width())
                    p=w.panels[w.selected_address]
                    for button in (p.apply_button,p.editor_run_button,p.editor_stop_button,w.run_active_button):
                        caption=button.text().replace('&','')
                        self.assertLessEqual(button.fontMetrics().horizontalAdvance(caption)+12,button.width(),(language,scale,width,caption))
                    if width==1366:w.grab().save(str(shots/f'station-{language}-{round(scale*100)}.png'))
        self.prime(1);self.write(1);w.panels[1].priming_control.toggle.setChecked(True)
        manager.set_language('zh_TW');w.ui_scale_combo.setCurrentIndex(w.ui_scale_combo.findData(1.));self.app.setStyleSheet(build_stylesheet(1.));w.resize(1366,768);self.app.processEvents()
        w.editor_scroll.ensureWidgetVisible(w.panels[1].priming_control.start,12,12);self.app.processEvents()
        w.grab().save(str(shots/'station-priming-zh_TW-100.png'))


if __name__=='__main__':unittest.main()
