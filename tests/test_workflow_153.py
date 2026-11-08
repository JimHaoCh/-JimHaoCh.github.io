"""Shared defaults, template preparation, live diameter edits and fault recovery."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyle, QStyleOptionSpinBox

from ne501.logging_utils import CsvCommandLogger
from ne501.syringe import format_diameter
from ne501.timeline_model import Timeline, example_timeline
from ui.main_window import MainWindow
from ui.workflow import DiameterInput
import test_workflow_141 as helpers


class DiameterStepTests(unittest.TestCase):
    setUpClass = classmethod(helpers.ModeWorkflowTests.setUpClass.__func__)

    def test_all_arrow_values_are_representable_and_monotonic_in_both_directions(self):
        spin = DiameterInput(); spin.setDecimals(3); spin.setRange(0, 50)
        previous = 0
        for _ in range(13901):
            spin.stepUp(); value = spin.value()
            format_diameter(value)
            self.assertGreater(value, previous); previous = value
        self.assertEqual(spin.value(), 50)
        spin.stepUp(); self.assertEqual(spin.value(), 50)
        for _ in range(13901):
            spin.stepDown(); value = spin.value()
            if value: format_diameter(value)
            self.assertLess(value, previous); previous = value
        self.assertEqual(spin.value(), 0)
        self.assertEqual(spin.text(), '')

    def test_arrow_boundaries_and_multi_steps_use_valid_precision(self):
        spin = DiameterInput(); spin.setDecimals(3); spin.setRange(0, 50)
        for start, steps, expected in ((10, 1, 10.01), (10, -1, 9.999),
                                       (9.999, 1, 10), (14.43, -1, 14.42),
                                       (0, 1, .1), (.1, -1, 0), (10, 10, 10.1)):
            with self.subTest(start=start, steps=steps):
                spin.setValue(start); spin.stepBy(steps)
                self.assertEqual(spin.value(), expected)


class LogRecoveryTests(unittest.TestCase):
    def test_unwritable_startup_log_recovers_with_one_header_and_keeps_commands(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'LOCALAPPDATA': folder}):
            with patch.object(CsvCommandLogger, '_initialize', side_effect=PermissionError('read-only')):
                logger = CsvCommandLogger()
                self.assertIsInstance(logger.initialization_error, OSError)
            logger.write(0, 'STATUS'); logger.write(0, 'STP')
            self.assertIsNone(logger.initialization_error)
            with logger.path.open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.reader(f))
            self.assertEqual(len(rows), 3)
            self.assertEqual([r[2] for r in rows[1:]], ['STATUS', 'STP'])


class Workflow153Tests(unittest.TestCase):
    setUpClass = classmethod(helpers.ModeWorkflowTests.setUpClass.__func__)
    setUp = helpers.ModeWorkflowTests.setUp
    tearDown = helpers.ModeWorkflowTests.tearDown
    idle = helpers.ModeWorkflowTests.idle
    ready = helpers.ModeWorkflowTests.ready

    def write(self, *addresses):
        self.win.write_station_programs([self.win.panels[a] for a in addresses]); self.idle()
        for a in addresses: self.assertTrue(self.win.panels[a].settings_applied)

    def diameter(self):
        self.win.show_workflow_step(1)
        spin = self.win.workflow.diameter_inputs[0]
        spin.setFocus(); self.app.processEvents()
        return spin

    def load_example(self):
        with patch.object(self.win.timeline_editor, 'prepare_to_leave', return_value=True):
            self.win.load_example_workflow()

    def test_new_session_has_four_ten_mm_plans_without_selection_or_device_proof(self):
        w = self.win
        self.assertEqual([p.diameter for p in w.preparation.plans.values()], [10] * 4)
        self.assertEqual(w.timeline_editor.model.diameters, [10] * 4)
        self.assertFalse(w.preparation.used_addresses())
        self.assertFalse(w.timeline_editor.model.clips)
        self.assertTrue(all(p.confirmed_diameter is None for p in w.panels.values()))
        self.assertTrue(all(not p.run_button.isEnabled() for p in w.panels.values()))

    def test_default_diameter_still_routes_step_one_to_step_two_in_both_modes(self):
        self.ready(); w = self.win
        for mode in (0, 1):
            w.mode_tabs.setCurrentIndex(mode); w.show_workflow_step(0)
            self.assertEqual(w.workflow_hint()[1], 1)
            w.follow_workflow_hint(); self.assertEqual(w.workflow.step, 1)
            self.assertEqual(w.workflow.diameter_inputs[0].value(), 10)

    def test_both_example_entries_preserve_selected_pumps_diameters_and_paths(self):
        self.ready((0, 1)); w = self.win
        w.update_preparation(0, diameter=4.699, fluid='Sample', inlet='A')
        w.update_preparation(1, diameter=14.43, fluid='Buffer', inlet='B')
        for toolbar in (False, True):
            with self.subTest(toolbar=toolbar), patch.object(w.timeline_editor, 'prepare_to_leave', return_value=True):
                if toolbar:
                    w.mode_tabs.setCurrentIndex(1); w.show_workflow_step(3)
                    w.timeline_editor.demo_button.click()
                else: w.load_example_workflow()
                self.assertEqual(w.mode_tabs.currentIndex(), 1)
                self.assertEqual(w.workflow.step, 1)
                self.assertEqual(w.preparation.used_addresses(), [0, 1])
                self.assertEqual(w.timeline_editor.model.diameters, [4.699, 14.43, 10, 10])
                self.assertEqual(w.timeline_editor.model.names[:2], ['Sample', 'Buffer'])
                self.assertEqual(w.timeline_editor.model.inlets[:2], ['A', 'B'])
                self.assertEqual({c.pump for c in w.timeline_editor.model.clips}, {0, 1})

    def test_example_from_empty_selection_uses_four_default_syringes_and_step_two(self):
        self.load_example(); w = self.win
        self.assertEqual(w.preparation.used_addresses(), [0, 1, 2, 3])
        self.assertEqual(w.workflow.step, 1)
        self.assertEqual(w.timeline_editor.model.diameters, [10] * 4)
        self.assertIsNone(w.controller)

    def test_example_preserves_an_explicitly_cleared_diameter(self):
        self.ready(); w = self.win; spin = self.diameter()
        spin.selectAll(); QTest.keyClick(spin, Qt.Key.Key_Backspace)
        QTest.keyClick(spin, Qt.Key.Key_Tab)
        self.load_example()
        self.assertIsNone(w.preparation.plans[0].diameter)
        self.assertIsNone(w.timeline_editor.model.diameters[0])
        self.assertEqual(spin.text(), '')
        self.assertEqual(w.workflow.step, 1)

    def test_invalid_diameter_draft_blocks_example_without_losing_text(self):
        self.ready(); w = self.win; spin = self.diameter()
        spin.selectAll(); QTest.keyClicks(spin, '14.431')
        before = w.timeline_editor.model.to_json()
        with patch.object(w.timeline_editor, 'prepare_to_leave') as leave:
            w.load_example_workflow(); leave.assert_not_called()
        self.assertEqual(spin.text(), '14.431')
        self.assertEqual(w.timeline_editor.model.to_json(), before)
        self.assertEqual(w.workflow.step, 1)
        self.assertIn(0, w._diameter_pending)

    def test_cancelled_example_keeps_mode_page_model_and_inspector_draft(self):
        self.load_example(); w = self.win; w.show_workflow_step(3)
        w.timeline_editor.rate_spin.setValue(12)
        before = w.timeline_editor.model.to_json()
        with patch.object(w.timeline_editor, 'prepare_to_leave', return_value=False):
            w.load_example_workflow()
        self.assertEqual(w.workflow.step, 3)
        self.assertEqual(w.timeline_editor.model.to_json(), before)
        self.assertTrue(w.timeline_editor.dirty)
        self.assertEqual(w.timeline_editor.rate_spin.value(), 12)

    def test_arrow_key_updates_shared_value_and_invalidates_old_proof_immediately(self):
        self.ready(); self.write(0); w = self.win; spin = self.diameter()
        QTest.keyClick(spin, Qt.Key.Key_Up)
        self.assertEqual(spin.value(), 10.01)
        self.assertEqual(w.preparation.plans[0].diameter, 10.01)
        self.assertEqual(w.timeline_editor.model.diameters[0], 10.01)
        self.assertTrue(w.manual_start_blocker(0))
        self.assertFalse(w.panels[0].run_button.isEnabled())
        self.assertTrue(w.panels[0].stop_button.isEnabled())

    def test_mouse_arrow_commits_the_same_representable_value(self):
        self.ready(); spin = self.diameter()
        option = QStyleOptionSpinBox(); spin.initStyleOption(option)
        rect = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option,
                                          QStyle.SubControl.SC_SpinBoxUp, spin)
        QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=rect.center())
        self.assertEqual(self.win.preparation.plans[0].diameter, 10.01)

    def test_deleted_default_stays_empty_after_tab_mode_switch_and_json_roundtrip(self):
        self.ready(); w = self.win; spin = self.diameter()
        spin.selectAll(); QTest.keyClick(spin, Qt.Key.Key_Backspace); QTest.keyClick(spin, Qt.Key.Key_Tab)
        self.assertEqual(spin.text(), '')
        self.assertIsNone(w.preparation.plans[0].diameter)
        w.mode_tabs.setCurrentIndex(1); w.mode_tabs.setCurrentIndex(0)
        self.assertEqual(spin.text(), '')
        data = w.timeline_editor.model.to_json()
        self.assertIsNone(json.loads(data)['tracks'][0]['diameter_mm'])
        self.assertIsNone(Timeline.from_json(data).diameters[0])

    def test_loading_updates_a_focused_diameter_field_to_the_loaded_plan(self):
        self.ready(); w = self.win; spin = self.diameter()
        w.timeline_editor._load_model(Timeline(diameters=[4.699, 10, 10, 10], used=[True, False, False, False]))
        self.assertEqual(spin.value(), 4.699)
        self.assertEqual(w.preparation.plans[0].diameter, 4.699)

    def test_undo_redo_update_focused_shared_input_and_never_restore_device_proof(self):
        self.ready(); self.write(0); w = self.win; spin = self.diameter()
        spin.setValue(4.699)
        w.timeline_editor.undo(); self.assertEqual(spin.value(), 10)
        self.assertIsNone(w.panels[0].confirmed_diameter)
        w.timeline_editor.redo(); self.assertEqual(spin.value(), 4.699)
        self.assertTrue(w.manual_start_blocker(0))

    def test_invalid_shared_draft_blocks_save_without_overwriting_existing_file(self):
        self.ready(); w = self.win; spin = self.diameter()
        path = Path(self.folder.name) / 'keep.json'
        before = w.timeline_editor.model.to_json(); path.write_text(before)
        w.timeline_editor.current_path = path
        spin.selectAll(); QTest.keyClicks(spin, '14.431')
        self.assertFalse(w.timeline_editor.save_file())
        self.assertEqual(path.read_text(), before)
        self.assertEqual(w.workflow.step, 1)

    def test_new_project_restores_defaults_and_returns_to_pump_selection(self):
        self.load_example(); w = self.win; w.show_workflow_step(3)
        with patch.object(w.timeline_editor, 'prepare_to_leave', return_value=True):
            w.timeline_editor.new_file()
        self.assertEqual(w.workflow.step, 0)
        self.assertEqual(w.mode_tabs.currentIndex(), 1)
        self.assertEqual(w.timeline_editor.model.diameters, [10] * 4)
        self.assertFalse(w.preparation.used_addresses())
        self.assertFalse(w.timeline_editor.model.clips)

    def test_open_file_preserves_saved_diameters_including_null_and_routes_step_two(self):
        self.ready(); self.write(0); w = self.win
        model = Timeline(diameters=[4.699, None, 10, 10], used=[True, True, False, False])
        path = Path(self.folder.name) / 'saved.json'; path.write_text(model.to_json())
        with patch.object(w.timeline_editor, 'prepare_to_leave', return_value=True), patch('ui.timeline_editor.QFileDialog.getOpenFileName', return_value=(str(path), '')):
            w.timeline_editor.open_file()
        self.assertEqual(w.workflow.step, 1)
        self.assertEqual(w.timeline_editor.model.diameters, model.diameters)
        self.assertIsNone(w.preparation.plans[1].diameter)
        self.assertIsNone(w.panels[0].confirmed_diameter)

    def test_unconfirmed_stop_blocks_all_project_replacement_entries(self):
        self.ready(); w = self.win; w.show_workflow_step(0)
        w.panels[0].set_stop_pending(reset=True); w.refresh_group_controls()
        before = w.timeline_editor.model.to_json()
        with patch.object(w.timeline_editor, 'prepare_to_leave') as leave, patch('ui.timeline_editor.QFileDialog.getOpenFileName') as choose:
            w.load_example_workflow(); w.timeline_editor.load_demo()
            w.timeline_editor.new_file(); w.timeline_editor.open_file()
            leave.assert_not_called(); choose.assert_not_called()
        self.assertEqual(w.workflow.step, 0)
        self.assertEqual(w.mode_tabs.currentIndex(), 0)
        self.assertEqual(w.timeline_editor.model.to_json(), before)
        self.assertTrue(w.panels[0].stop_pending)

    def test_pending_command_blocks_example_without_resetting_preparation(self):
        self.ready(); w = self.win; w.show_workflow_step(0)
        before = w.timeline_editor.model.to_json(); w.pending_tasks = 1
        try: w.load_example_workflow()
        finally: w.pending_tasks = 0
        self.assertEqual(w.timeline_editor.model.to_json(), before)
        self.assertEqual(w.workflow.step, 0)

    def test_unconfirmed_stop_also_locks_manual_preparation_fields_and_updates(self):
        self.ready(); w = self.win
        w.panels[0].set_stop_pending(reset=True); w.show_workflow_step(1)
        self.assertFalse(w.workflow.diameter_inputs[0].isEnabled())
        self.assertFalse(w.workflow.mapping_inputs[0][0].isEnabled())
        self.assertFalse(w.update_preparation(0, diameter=4.699))
        self.assertEqual(w.preparation.plans[0].diameter, 10)
        self.assertTrue(w.panels[0].stop_button.isEnabled())

    def test_defaults_require_explicit_write_and_run_and_do_not_touch_other_pumps(self):
        self.ready(); w = self.win
        with patch.object(w.controller, 'send_command', wraps=w.controller.send_command) as sent:
            self.assertIsNone(w.panels[0].confirmed_diameter)
            self.write(0)
            self.assertFalse(any(c.args[1].startswith('RUN') for c in sent.call_args_list))
            w.run_single(0); self.idle(); w.stop_single(0); self.idle()
        self.assertEqual(w.panels[0].last_status, 'P')
        self.assertTrue(all(w.panels[a].confirmed_diameter is None for a in (1, 2, 3)))

    def test_retained_custom_diameter_drives_example_conversion_and_preview_without_io(self):
        self.ready(); w = self.win; w.update_preparation(0, diameter=4.699)
        with patch.object(w.controller, 'send_command') as sent:
            self.load_example(); w.show_workflow_step(3)
            clip = w.timeline_editor.model.clips[0]
            self.assertAlmostEqual(w.timeline_editor.model.plunger_speed(clip), 10 / (3.141592653589793 * 4.699 ** 2 / 4))
            w.timeline_editor.check_flow(); w.timeline_editor.start_preview()
            self.assertTrue(w.timeline_editor.running)
            sent.assert_not_called()

    def test_log_startup_failure_keeps_window_and_stop_controls_operational(self):
        self.win.close(); self.app.processEvents()
        with patch.object(CsvCommandLogger, '_initialize', side_effect=PermissionError('read-only log folder')):
            self.win = MainWindow({'addresses': [0, 1, 2, 3], 'port': 'MOCK'},
                                  settings=QSettings(str(Path(self.folder.name) / 'readonly.ini'), QSettings.Format.IniFormat))
            self.win.show(); self.app.processEvents(); self.ready()
            self.assertEqual(len(self.win._notice_windows), 1)
            self.write(0); self.win.run_single(0); self.idle(); self.win.stop_single(0); self.idle()
            self.assertEqual(self.win.panels[0].last_status, 'P')
            self.assertFalse(self.win.panels[0].stop_pending)


if __name__ == '__main__': unittest.main()
