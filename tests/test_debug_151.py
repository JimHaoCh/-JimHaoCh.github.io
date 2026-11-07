"""Regression cases from the v1.5.0 keyboard and fault-path audit.

Keyboard paths use Qt events; device and filesystem faults are injected.
No tests open a physical serial port.
"""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ne501.controller import NE501Controller, PumpTimeoutError, CommandCancelled
from ne501.mock_controller import MockNE501Controller
from ne501.protocol import parse_response
from ne501.stop_report import StopAllReport, stop_all_independently
from ui.i18n import manager
from ui.i18n_widgets import SpinBox, MessageBox
import test_workflow_141 as helpers
from test_manual_station_150 import Clock
from test_gui_dispatch_logic import FakeWorker, FakeCallbacks, FakePool


class StopTimeoutTests(unittest.TestCase):
    def test_status_timeout_still_sends_stop_reset_and_continues_other_addresses(self):
        class Probe(NE501Controller):
            def __init__(self):super().__init__();self.sent=[];self.stops=0
            def send_command(self,a,c):
                self.sent.append((a,c))
                if a==0 and not c:raise PumpTimeoutError('Injected status timeout')
                if a==0 and c=='STP':
                    self.stops+=1;status='P' if self.stops==1 else 'S'
                else:status='S'
                return parse_response(f'\x02{a:02d}{status}\x03'.encode(),a)
        controller=Probe();report=stop_all_independently(controller,[0,1])
        self.assertEqual(controller.sent,[(0,''),(0,'STP'),(0,'STP'),(1,'')])
        self.assertEqual(report.confirmed,[0,1]);self.assertFalse(report.unconfirmed)

    def test_stop_timeout_never_becomes_confirmed_and_remaining_pumps_are_attempted(self):
        class Probe(NE501Controller):
            def __init__(self):super().__init__();self.sent=[]
            def send_command(self,a,c):
                self.sent.append((a,c))
                if a==0:raise PumpTimeoutError('Injected timeout')
                return parse_response(f'\x02{a:02d}S\x03'.encode(),a)
        controller=Probe();report=stop_all_independently(controller,[0,1])
        self.assertIn((0,'STP'),controller.sent)
        self.assertIn(0,report.unconfirmed);self.assertEqual(report.confirmed,[1])

    def test_cancelled_query_does_not_bypass_command_cancellation(self):
        controller=MockNE501Controller([0],latency=0);controller.connect()
        with controller.cancellable(lambda:False):
            with self.assertRaises(CommandCancelled):controller.stop_pump(0)


class Debug151Tests(unittest.TestCase):
    setUpClass=classmethod(helpers.ModeWorkflowTests.setUpClass.__func__)
    setUp=helpers.ModeWorkflowTests.setUp
    tearDown=helpers.ModeWorkflowTests.tearDown
    idle=helpers.ModeWorkflowTests.idle
    ready=helpers.ModeWorkflowTests.ready

    def write(self,*addresses):
        self.win.write_station_programs([self.win.panels[a] for a in addresses]);self.idle()
        for a in addresses:self.assertTrue(self.win.panels[a].settings_applied)

    def enter(self,spin,text):
        spin.setFocus();spin.selectAll();self.app.processEvents()
        QTest.keyClicks(spin,text);self.app.processEvents()

    def prime(self):
        control=self.win.panels[0].priming_control
        control.mode.setCurrentIndex(1);control.custom_rate.setValue(10)
        control.volume.setValue(5);control.toggle.setChecked(True)
        return control

    def test_typed_diameter_survives_each_keystroke_and_commits_on_enter(self):
        self.ready();w=self.win;w.show_workflow_step(1);s=w.workflow.diameter_inputs[0]
        s.setFocus();s.selectAll()
        typed=''
        for c in '4.699':
            QTest.keyClicks(s,c);typed+=c;self.app.processEvents()
            self.assertEqual(s.text(),typed)
        QTest.keyClick(s,Qt.Key.Key_Return);self.app.processEvents()
        self.assertEqual(w.preparation.plans[0].diameter,4.699)

    def test_blank_diameter_accepts_paste_and_mouse_write_without_extra_commit(self):
        self.ready();w=self.win;w.update_preparation(0,diameter=None);w.show_workflow_step(1)
        s=w.workflow.diameter_inputs[0];s.setFocus();s.selectAll()
        QApplication.clipboard().setText('14.43')
        QTest.keyClick(s,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier);self.app.processEvents()
        self.assertEqual(s.text(),'14.43');self.assertTrue(w.workflow.diameter_buttons[0].isEnabled())
        QTest.mouseClick(w.workflow.diameter_buttons[0],Qt.MouseButton.LeftButton);self.idle()
        self.assertEqual(w.preparation.plans[0].diameter,14.43)
        self.assertEqual(w.panels[0].confirmed_diameter,14.43)

    def test_diameter_tab_commits_and_invalid_precision_stays_pending(self):
        self.ready();w=self.win;w.show_workflow_step(1);s=w.workflow.diameter_inputs[0]
        self.enter(s,'14.43');QTest.keyClick(s,Qt.Key.Key_Tab);self.app.processEvents()
        self.assertEqual(w.preparation.plans[0].diameter,14.43)
        self.enter(s,'14.431');QTest.keyClick(s,Qt.Key.Key_Return);self.app.processEvents()
        self.assertIn(0,w._diameter_pending)
        self.assertFalse(w.workflow.diameter_buttons[0].isEnabled())
        self.assertFalse(w.panels[0].run_button.isEnabled())
        self.assertTrue(w.panels[0].stop_button.isEnabled())

    def test_empty_diameter_draft_survives_refresh_and_blocks_old_start(self):
        self.ready();self.write(0);w=self.win;w.show_workflow_step(1)
        s=w.workflow.diameter_inputs[0];s.setFocus();s.selectAll();QTest.keyClick(s,Qt.Key.Key_Backspace)
        w.refresh_group_controls();self.app.processEvents()
        self.assertEqual(s.lineEdit().text(),'')
        self.assertIn(0,w._diameter_pending);self.assertFalse(w.panels[0].run_button.isEnabled())

    def test_cursor_selection_and_draft_survive_poll_language_and_scale_changes(self):
        self.ready();w=self.win;w.show_workflow_step(1);s=w.workflow.diameter_inputs[0]
        self.enter(s,'14.43');s.lineEdit().setSelection(1,2)
        before=(s.text(),s.lineEdit().cursorPosition(),s.lineEdit().selectionStart(),s.lineEdit().selectedText())
        w.refresh_status();self.idle();manager.set_language('en');manager.set_language('zh_TW')
        w.ui_scale_combo.setCurrentIndex(w.ui_scale_combo.findData(1.3));self.app.processEvents()
        after=(s.text(),s.lineEdit().cursorPosition(),s.lineEdit().selectionStart(),s.lineEdit().selectedText())
        self.assertEqual(after,before)

    def test_flow_mode_uses_the_same_working_keyboard_input(self):
        self.ready();w=self.win;w.mode_tabs.setCurrentIndex(1);w.show_workflow_step(1)
        s=w.workflow.diameter_inputs[0];self.enter(s,'4.699');QTest.keyClick(s,Qt.Key.Key_Return);self.app.processEvents()
        self.assertEqual(w.timeline_editor.model.diameters[0],4.699)
        self.assertEqual(w.preparation.plans[0].diameter,4.699)

    def test_console_has_readonly_diameter_and_its_edit_entry_focuses_step2(self):
        self.ready();w=self.win;w.show_workflow_step(3);p=w.panels[0]
        self.assertFalse(hasattr(p,'inline_setup'))
        self.assertFalse(any(s.isVisible() and s.objectName()=='syringeValue' for s in p.editor.findChildren(SpinBox)))
        self.assertTrue(p.diameter_input.isReadOnly())
        p.change_diameter_button.click();self.app.processEvents()
        self.assertEqual(w.workflow.step,1);self.assertTrue(w.workflow.diameter_inputs[0].hasFocus())

    def test_missing_diameter_group_resolver_opens_step2(self):
        self.ready();w=self.win;p=w.panels[0];p.set_active(True)
        w.diameter_text_pending(0);w.show_workflow_step(3)
        w.resolve_group_blocker();self.assertEqual(w.workflow.step,1)
        self.assertTrue(w.workflow.diameter_inputs[0].hasFocus())

    def test_priming_rate_and_volume_accept_keyboard_then_mouse_write(self):
        self.ready();w=self.win;w.show_workflow_step(3);p=w.panels[0];c=p.priming_control
        c.toggle.setChecked(True);c.mode.setCurrentIndex(1);self.app.processEvents()
        w.editor_scroll.ensureWidgetVisible(c.custom_rate);self.enter(c.custom_rate,'12.3')
        self.assertEqual(c.custom_rate.text(),'12.3')
        w.editor_scroll.ensureWidgetVisible(c.volume);self.enter(c.volume,'5')
        self.assertEqual(c.volume.text(),'5')
        QTest.mouseClick(p.apply_button,Qt.MouseButton.LeftButton);self.idle()
        self.assertTrue(c.start.isEnabled())
        state=w.controller.pumps[0]
        self.assertEqual(state.phases[3].rate,12.3);self.assertEqual(state.phases[3].volume,5)

    def test_unrepresentable_priming_rate_is_an_inline_error_and_never_written(self):
        self.ready();w=self.win;self.write(0);c=self.prime()
        c.rate_unit.setCurrentIndex(c.rate_unit.findData('UH'))
        with patch.object(sys,'excepthook') as unhandled:
            c.custom_rate.setValue(.0001);c.refresh();w.refresh_group_controls()
        unhandled.assert_not_called()
        self.assertIn('cannot be represented',c.validation_error)
        self.assertFalse(c.start.isEnabled());self.assertTrue(w.panels[0].run_button.isEnabled())
        with patch.object(w.controller,'send_command',wraps=w.controller.send_command) as sent:
            w.apply_single(0,w.panels[0].current_settings());self.idle()
        sent.assert_not_called();self.assertTrue(w.panels[0].stop_button.isEnabled())

    def test_priming_stage_label_survives_age_update_and_full_panel_refresh(self):
        self.ready();w=self.win;w.controller.clock=Clock();self.prime();self.write(0)
        w.start_station_priming(0);self.idle();p=w.panels[0]
        before=(p.target_label.source_text,p.mode_label.source_text)
        p.refresh_age();p.set_compact(True);p._refresh_enabled_state()
        self.assertEqual((p.target_label.source_text,p.mode_label.source_text),before)
        self.assertIn('Priming:',before[0]);self.assertEqual(w.controller.pumps[0].current_phase,3)

    def test_paused_label_survives_age_refresh_and_language_changes(self):
        self.ready();w=self.win;self.write(0);w.run_single(0);self.idle();w.stop_single(0);self.idle()
        p=w.panels[0];p.refresh_age();manager.set_language('en');manager.set_language('zh_TW')
        self.assertEqual(p.status_label.source_text,'● Stopped · progress retained')
        self.assertEqual(p.editor_run_button.source_text,'Resume delivery')

    def test_post_priming_tubing_confirmation_is_available_without_a_second_diameter_input(self):
        self.ready();w=self.win;w.show_workflow_step(3);w.controller.clock=Clock();self.prime()
        w.change_tubing(0,'needed');self.write(0);w.start_station_priming(0);self.idle();w.stop_single(0);self.idle()
        p=w.panels[0];self.assertTrue(p.setup_summary.confirm_ready.isVisible())
        p.setup_summary.confirm_ready.click();self.assertEqual(w.preparation.tubing[0],'done')
        self.assertEqual(w.workflow.step,3);self.assertFalse(hasattr(p,'inline_setup'))

    def test_running_p1_does_not_make_missing_p2_diameter_bounce_between_steps(self):
        self.ready((0,1));w=self.win;self.write(0);w.run_single(0);self.idle()
        w.update_preparation(1,diameter=None);w.select_pump(1);w.show_workflow_step(1)
        for _ in range(3):
            self.assertEqual(w.workflow_hint()[1],1);w.follow_workflow_hint()
            self.assertEqual(w.workflow.step,1)
        self.assertTrue(w.panels[0].running)

    def test_stop_unconfirmed_survives_repeated_timeouts_and_rescan(self):
        self.ready();w=self.win;w.present_stop_report(StopAllReport(unconfirmed={0:'Injected STOP failure'}))
        original=w.controller.send_command
        def send(a,c):
            if a==0:raise PumpTimeoutError('Still no response')
            return original(a,c)
        with patch.object(w.controller,'send_command',side_effect=send):
            for _ in range(2):w.refresh_status();self.idle()
        with patch.object(w.controller,'scan',return_value={}):w.scan_pumps();self.idle()
        self.assertTrue(w.panels[0].stop_pending);self.assertFalse(w.can_use_timeline())
        self.assertIn('Stop unconfirmed: P1',w.execution_label.source_text)

    def test_unconfirmed_stop_survives_disconnect_without_a_stop_confirmation(self):
        self.ready();w=self.win;w.present_stop_report(StopAllReport(unconfirmed={0:'Injected STOP failure'}))
        with patch('ui.main_window.QMessageBox.question',return_value=MessageBox.StandardButton.No):w.disconnect_controller()
        self.assertTrue(w.panels[0].stop_pending)
        self.assertIn('Stop unconfirmed: P1',w.execution_label.source_text)

    def test_reset_stop_requires_s_while_single_hold_accepts_p(self):
        self.ready();p=self.win.panels[0]
        p.set_stop_pending(reset=True);p.update_from_status('P');self.assertTrue(p.stop_pending)
        p.set_online(False);self.assertTrue(p.stop_pending)
        p.update_from_status('S');self.assertFalse(p.stop_pending)
        p.set_stop_pending();p.update_from_status('P');self.assertFalse(p.stop_pending)

    def test_retrying_single_stop_finishes_a_previously_unconfirmed_reset(self):
        self.ready();w=self.win;self.write(0);w.run_single(0);self.idle()
        w.panels[0].set_stop_pending(reset=True);w.stop_single(0);self.idle()
        self.assertEqual(w.controller.pumps[0].status,'S');self.assertFalse(w.panels[0].stop_pending)

    def test_log_write_failure_cannot_hide_global_stop_results(self):
        self.ready();w=self.win;self.write(0);w.run_single(0);self.idle()
        with patch.object(w.csv_logger,'write',side_effect=OSError('Injected disk error')):
            w.emergency_stop();self.idle()
        self.assertTrue(all(p.last_status=='S' and not p.stop_pending for p in w.panels.values()))
        self.assertEqual(len(w._notice_windows),1)
        self.assertTrue(all(p.last_response_source=='STOP confirmed by pump response' for p in w.panels.values()))

    def test_log_write_failure_cannot_hide_single_stop_results(self):
        self.ready();w=self.win;self.write(0);w.run_single(0);self.idle()
        with patch.object(w.csv_logger,'write',side_effect=OSError('Injected disk error')):
            w.stop_single(0);self.idle()
        self.assertEqual(w.panels[0].last_status,'P');self.assertFalse(w.panels[0].stop_pending)

    def test_group_stop_keeps_another_pumps_completed_write_confirmation(self):
        self.ready((0,1));w=self.win;w.panels[0].rate_input.setValue(2)
        original=w.controller.send_command;interrupted=False
        def send(a,c):
            nonlocal interrupted
            response=original(a,c)
            if a==1 and c.startswith('DIA ') and not interrupted:
                interrupted=True;w.stop_single(1)
            return response
        with patch.object(w.controller,'send_command',side_effect=send),patch('ui.main_window.FunctionWorker',FakeWorker),patch('ui.main_window.WorkerCallbacks',FakeCallbacks):
            w.thread_pool=FakePool();w.write_station_programs([w.panels[0],w.panels[1]])
            while w.thread_pool.queue:w.thread_pool.run_next()
        self.assertEqual(w.controller.pumps[0].phases[1].rate,2)
        self.assertTrue(w.panels[0].settings_applied);self.assertIn(0,w.station_proofs)
        self.assertFalse(w.panels[1].settings_applied);self.assertEqual(w.panels[1].last_status,'S')


if __name__=='__main__':unittest.main()
