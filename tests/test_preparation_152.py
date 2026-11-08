"""Mouse-first diameter entry and preparation without extra confirmations.

Device commands use the virtual controller; no physical serial port is opened.
"""
from unittest.mock import patch
import unittest

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.i18n import manager, tr
import test_workflow_141 as helpers
from test_manual_station_150 import Clock


class Preparation152Tests(unittest.TestCase):
    setUpClass = classmethod(helpers.ModeWorkflowTests.setUpClass.__func__)
    setUp = helpers.ModeWorkflowTests.setUp
    tearDown = helpers.ModeWorkflowTests.tearDown
    idle = helpers.ModeWorkflowTests.idle
    ready = helpers.ModeWorkflowTests.ready

    def select_connected(self):
        self.ready(())
        w = self.win
        w.preparation.mapping_confirmed = False
        w.show_workflow_step(0)
        check = w.workflow.mapping_inputs[0][0]
        QTest.mouseClick(check, Qt.MouseButton.LeftButton, pos=QPoint(12, check.height() // 2))
        self.assertEqual(w.preparation.used_addresses(), [0])
        self.assertEqual(w.preparation.tubing[0], 'pending')

    def blank(self):
        w = self.win
        w.show_workflow_step(1)
        w.workflow.next_button.setFocus()
        w.update_preparation(0, diameter=None)
        self.app.processEvents()
        spin = w.workflow.diameter_inputs[0]
        self.assertEqual(spin.text(), '')
        QTest.mouseClick(spin.lineEdit(), Qt.MouseButton.LeftButton,
                         pos=QPoint(12, spin.lineEdit().height() // 2))
        self.app.processEvents()
        self.assertEqual(spin.text(), '')
        self.assertEqual(spin.lineEdit().placeholderText(), '')
        return spin

    def write(self, *addresses):
        self.win.write_station_programs([self.win.panels[a] for a in addresses])
        self.idle()
        for a in addresses:
            self.assertTrue(self.win.panels[a].settings_applied)

    def priming(self, follow=False):
        w = self.win
        w.controller.clock = Clock()
        c = w.panels[0].priming_control
        c.toggle.setChecked(True)
        c.mode.setCurrentIndex(1)
        c.custom_rate.setValue(120)
        c.volume.setValue(2)
        c.follow.setChecked(follow)
        return c

    def test_manual_blank_accepts_typing_after_mouse_click_in_both_languages(self):
        self.select_connected()
        for language in ('zh_TW', 'en'):
            with self.subTest(language=language):
                manager.set_language(language)
                spin = self.blank()
                QTest.keyClicks(spin, '4.699')
                self.assertEqual(spin.text(), '4.699')
                QTest.keyClick(spin, Qt.Key.Key_Return)
                self.assertEqual(self.win.preparation.plans[0].diameter, 4.699)

    def test_offline_timeline_blank_accepts_mouse_then_typing_in_both_languages(self):
        w = self.win
        w.mode_tabs.setCurrentIndex(1)
        w.update_preparation(0, used=True)
        for language in ('zh_TW', 'en'):
            with self.subTest(language=language):
                manager.set_language(language)
                spin = self.blank()
                QTest.keyClicks(spin, '14.43')
                QTest.keyClick(spin, Qt.Key.Key_Tab)
                self.assertEqual(w.timeline_editor.model.diameters[0], 14.43)
        self.assertIsNone(w.controller)

    def test_mouse_then_paste_then_mouse_write_needs_no_select_all(self):
        self.select_connected()
        spin = self.blank()
        QApplication.clipboard().setText('4.699')
        QTest.keyClick(spin, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        QTest.mouseClick(self.win.workflow.diameter_buttons[0], Qt.MouseButton.LeftButton)
        self.idle()
        self.assertEqual(self.win.panels[0].confirmed_diameter, 4.699)

    def test_empty_hint_localizes_off_focus_and_stays_hidden_while_focused(self):
        self.select_connected()
        spin = self.blank()
        manager.set_language('en')
        self.assertEqual(spin.lineEdit().placeholderText(), '')
        self.win.workflow.next_button.setFocus()
        self.app.processEvents()
        self.assertEqual(spin.text(), '')
        self.assertEqual(spin.lineEdit().placeholderText(), tr('Enter diameter'))
        manager.set_language('zh_TW')
        self.assertEqual(spin.lineEdit().placeholderText(), tr('Enter diameter'))

    def test_mouse_started_draft_survives_poll_language_and_scale_changes(self):
        self.select_connected()
        spin = self.blank()
        QTest.keyClicks(spin, '4.6')
        self.win.refresh_status()
        self.idle()
        manager.set_language('en')
        self.win.ui_scale_combo.setCurrentIndex(self.win.ui_scale_combo.findData(1.3))
        self.app.processEvents()
        self.assertEqual(spin.text(), '4.6')
        QTest.keyClicks(spin, '99')
        QTest.keyClick(spin, Qt.Key.Key_Return)
        self.assertEqual(self.win.preparation.plans[0].diameter, 4.699)

    def test_selection_goes_to_diameter_then_console_without_confirmation_controls(self):
        self.select_connected()
        w = self.win
        self.assertFalse(hasattr(w.workflow, 'mapping_check'))
        self.assertFalse(hasattr(w.workflow, 'tubing_box'))
        self.assertEqual(w.workflow_hint()[1], 1)
        self.assertTrue(w.workflow.steps[0].property('complete'))
        QTest.mouseClick(w.workflow.next_button, Qt.MouseButton.LeftButton)
        self.assertEqual(w.workflow.step, 1)
        spin = self.blank()
        QTest.keyClicks(spin, '10')
        QTest.keyClick(spin, Qt.Key.Key_Tab)
        self.assertEqual(w.workflow_hint()[1], 3)
        QTest.mouseClick(w.workflow.next_button, Qt.MouseButton.LeftButton)
        self.assertEqual(w.workflow.step, 3)

    def test_write_then_explicit_start_stop_works_with_confirmation_flags_unset(self):
        self.select_connected()
        w = self.win
        w.update_preparation(0, diameter=10)
        w.show_workflow_step(3)
        with patch.object(w.controller, 'send_command', wraps=w.controller.send_command) as sent:
            self.write(0)
            self.assertFalse(any(c.args[1].startswith('RUN') for c in sent.call_args_list))
            self.assertFalse(w.manual_start_blocker(0))
            w.panels[0].editor_run_button.click()
            self.idle()
            self.assertTrue(w.panels[0].running)
            w.panels[0].editor_stop_button.click()
            self.idle()
        self.assertEqual(w.panels[0].last_status, 'P')
        self.assertFalse(w.preparation.mapping_confirmed)
        self.assertEqual(w.preparation.tubing[0], 'pending')

    def test_independent_priming_stops_and_formal_delivery_needs_only_start(self):
        self.select_connected()
        w = self.win
        w.update_preparation(0, diameter=10)
        w.show_workflow_step(3)
        c = self.priming()
        self.write(0)
        c.start.click()
        self.idle()
        w.stop_single(0)
        self.idle()
        self.assertFalse(w.panels[0].running)
        self.assertFalse(hasattr(w.panels[0].setup_summary, 'confirm_ready'))
        self.assertFalse(w.manual_start_blocker(0))
        with patch.object(w.controller, 'send_command', wraps=w.controller.send_command) as sent:
            w.panels[0].editor_run_button.click()
            self.idle()
        self.assertEqual([c.args[1] for c in sent.call_args_list if c.args[1].startswith('RUN')], ['RUN 1'])

    def test_optional_priming_chain_needs_no_removed_confirmation(self):
        self.select_connected()
        w = self.win
        w.update_preparation(0, diameter=10)
        c = self.priming(follow=True)
        self.write(0)
        self.assertTrue(c.start.isEnabled())
        self.assertFalse(w.panels[0].running)
        c.start.click()
        self.idle()
        self.assertEqual(w.panels[0].station_context, 'priming_chain')
        w.controller.clock.advance(1.1)
        w.refresh_status()
        self.idle()
        self.assertEqual(w.panels[0].station_phase, 1)

    def test_group_write_and_start_need_no_mapping_or_tubing_confirmation(self):
        self.ready((0, 1))
        w = self.win
        w.preparation.mapping_confirmed = False
        for a in (0, 1):
            w.preparation.confirm_tubing(a, 'pending')
            w.panels[a].set_active(True)
        w.show_workflow_step(3)
        w.apply_active_button.click()
        self.idle()
        self.assertTrue(w.run_active_button.isEnabled())
        w.run_active_button.click()
        self.idle()
        self.assertTrue(all(w.panels[a].running for a in (0, 1)))
        w.stop_active_button.click()
        self.idle()
        self.assertTrue(all(w.panels[a].last_status == 'P' for a in (0, 1)))

    def test_blank_and_invalid_diameter_still_block_write_and_start(self):
        self.select_connected()
        w = self.win
        spin = self.blank()
        self.assertFalse(w.workflow.diameter_buttons[0].isEnabled())
        QTest.keyClicks(spin, '14.431')
        QTest.keyClick(spin, Qt.Key.Key_Return)
        self.assertIn(0, w._diameter_pending)
        self.assertFalse(w.workflow.diameter_buttons[0].isEnabled())
        self.assertFalse(w.panels[0].run_button.isEnabled())
        self.assertTrue(w.panels[0].stop_button.isEnabled())

    def test_changed_diameter_still_requires_device_readback_before_start(self):
        self.select_connected()
        w = self.win
        w.update_preparation(0, diameter=10)
        self.write(0)
        spin = self.blank()
        QTest.keyClicks(spin, '4.699')
        QTest.keyClick(spin, Qt.Key.Key_Return)
        self.assertTrue(w.manual_start_blocker(0))
        self.assertFalse(w.panels[0].run_button.isEnabled())
        self.write(0)
        self.assertFalse(w.manual_start_blocker(0))
        self.assertFalse(w.panels[0].running)


if __name__ == '__main__':
    unittest.main()
