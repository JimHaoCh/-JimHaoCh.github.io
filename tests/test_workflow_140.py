"""Shared preparation, explicit motion and cross-mode persistence regressions."""
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from ne501.preparation import PreparationState, write_verified_program
from ne501.mock_controller import MockNE501Controller
from ne501.controller import ProgramSettings
from ne501.timeline_model import Timeline, Clip, example_timeline


def program(diameter=10):
    return ProgramSettings(10, 'UM', 'INF', False, 1, 'UL', False, 1, 'UL', 'LOW', diameter)


class PreparationModelTests(unittest.TestCase):
    def test_only_selected_pumps_require_user_confirmation(self):
        state = PreparationState([5, 7, 8, 9])
        state.update(5, used=True, diameter=4.699, fluid='Sample', inlet='A')
        state.update(7, used=True, diameter=14.43)
        state.mapping_confirmed = True
        state.confirm_tubing(5, 'done')
        state.confirm_tubing(7, 'skipped')
        self.assertEqual(state.used_addresses(), [5, 7])
        self.assertFalse(state.physical_blocker(5))
        state.update(5, diameter=5)
        self.assertTrue(state.mapping_confirmed)
        self.assertEqual(state.tubing[5], 'pending')
        self.assertEqual(state.tubing[7], 'skipped')
        state.reset_session()
        self.assertFalse(state.mapping_confirmed)
        self.assertEqual(state.plans[5].diameter, 5)

    def test_shared_names_selection_and_diameters_survive_editing_and_files(self):
        model = example_timeline()
        model.set_preparation([4.699, 14.43, None, None], [True, True, False, False],
                              ['Sample', 'Buffer', '', ''], ['A', 'B', '', ''])
        copied = Timeline.from_json(model.to_json()).copy()
        copied.split('a', 100)
        copied.set_total(1300)
        self.assertEqual(copied.names, model.names)
        self.assertEqual(copied.inlets, model.inlets)
        self.assertEqual(copied.used, model.used)
        self.assertEqual(copied.diameters, model.diameters)
        self.assertEqual({c.pump for c in copied.active(200)}, {0, 1})
        copied.validate_syringes()
        for text in ('device', 'tubing', 'confirmed'):
            self.assertNotIn(text, copied.to_json())

    def test_old_file_infers_used_tracks_and_rejects_invalid_metadata(self):
        data = json.loads(example_timeline().to_json())
        for track in data['tracks']:
            for key in ('used', 'fluid', 'inlet'):
                del track[key]
        restored = Timeline.from_json(json.dumps(data))
        self.assertEqual(restored.used, [True] * 4)
        for field, value in (('used', 1), ('fluid', '\n'), ('inlet', 'x' * 65), ('fluid', None)):
            damaged = json.loads(json.dumps(data))
            damaged['tracks'][0][field] = value
            with self.assertRaises(ValueError):
                Timeline.from_json(json.dumps(damaged))

    def test_failed_add_is_atomic_including_track_selection(self):
        model = Timeline(100, [Clip('a', 0, 0, 100, 'INF', 10, 'µL/min')])
        before = model.to_json()
        with self.assertRaises(ValueError):
            model.add(Clip('a', 1, 0, 100, 'INF', 10, 'µL/min'))
        self.assertEqual(model.to_json(), before)

    def test_combined_write_reads_diameter_before_program_and_never_runs(self):
        controller = MockNE501Controller([5], latency=0)
        controller.connect()
        with patch.object(controller, 'send_command', wraps=controller.send_command) as sent:
            result = write_verified_program(controller, 5, program(4.699))
        self.assertTrue(result.verified)
        commands = [call.args[1] for call in sent.call_args_list]
        self.assertLess(commands.index('DIA'), commands.index('PHN 1'))
        self.assertFalse(any(command.startswith('RUN') for command in commands))
        self.assertEqual(controller.pumps[5].status, 'S')

    def test_failed_diameter_and_stop_ticket_prevent_later_writes(self):
        controller = MockNE501Controller([0], latency=0)
        controller.connect()
        with patch.object(controller, 'configure_program') as configure:
            checks = iter([True, False])
            result = write_verified_program(controller, 0, program(), lambda: next(checks))
            self.assertTrue(result.cancelled)
            configure.assert_not_called()
        confirmation = controller.set_diameter(0, 10)
        from dataclasses import replace
        wrong = replace(confirmation, confirmed_mm=10.01)
        with patch.object(controller, 'set_diameter', return_value=wrong), patch.object(controller, 'configure_program') as configure:
            self.assertFalse(write_verified_program(controller, 0, program()).verified)
            configure.assert_not_called()


from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QCheckBox
from ui.main_window import MainWindow
from ui.fonts import configure_ui_font
from ui.i18n import manager
from ui.style import build_stylesheet


class WorkflowUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        configure_ui_font(cls.app)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.win = MainWindow({'addresses': [0, 1, 2, 3], 'port': 'MOCK'},
                              settings=QSettings(str(Path(self.folder.name) / 'settings.ini'), QSettings.Format.IniFormat))
        self.win.resize(1280, 850)
        self.win.show()
        self.app.processEvents()

    def tearDown(self):
        self.idle()
        self.win.poll_timer.stop()
        if self.win.controller:
            self.win.controller.disconnect()
        self.win.controller = None
        timeline = self.win.timeline_editor
        timeline.stop_preview()
        timeline.dirty = timeline.duration_dirty = False
        timeline.saved_snapshot = timeline.model.to_json()
        self.win.close()
        self.folder.cleanup()
        manager.set_language('zh_TW')
        self.app.setStyleSheet(build_stylesheet())

    def idle(self):
        deadline = time.monotonic() + 8
        while self.win.pending_tasks and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertEqual(self.win.pending_tasks, 0)

    def ready(self, addresses=(0, 1)):
        self.win.controller = MockNE501Controller([0, 1, 2, 3], latency=0)
        self.win.controller.connect()
        self.win.connection_label.setText('● Connected MOCK')
        self.win.connect_button.setText('Disconnect')
        self.win._set_group_buttons_enabled(True)
        for panel in self.win.panels.values():
            panel.set_online(True)
            panel.update_from_status('S')
        for address in addresses:
            self.win.update_preparation(address, used=True, diameter=10, fluid=f'Fluid {address}', inlet=str(address + 1))
        self.win.preparation.mapping_confirmed = True
        for address in addresses:
            self.win.preparation.confirm_tubing(address, 'done')
        self.win.refresh_group_controls()

    def test_new_install_has_ten_mm_defaults_and_example_reviews_syringes(self):
        self.assertEqual(self.win.workflow.step, 0)
        self.assertEqual(self.win.preparation.used_addresses(), [])
        self.assertEqual(self.win.timeline_editor.model.diameters, [10] * 4)
        self.assertEqual(self.win.timeline_editor.model.clips, [])
        self.assertTrue(all(spin.value() == 10 for spin in self.win.workflow.diameter_inputs.values()))
        self.win.load_example_workflow()
        self.assertEqual(self.win.timeline_editor.model.diameters, [10] * 4)
        self.assertFalse(self.win.preparation.mapping_confirmed)
        self.assertEqual(self.win.workflow.step, 1)

    def test_next_step_orders_real_setup_and_routes_device_failures(self):
        self.win.update_preparation(0, used=True)
        self.assertEqual(self.win.workflow_hint()[1], 0)
        self.ready((0,))
        self.win.update_preparation(0, diameter=None)
        self.assertEqual(self.win.workflow_hint()[1], 1)
        self.win.update_preparation(0, diameter=4.699)
        self.assertEqual(self.win.workflow_hint()[1], 1)
        self.assertEqual(self.win.preparation.tubing[0], 'pending')
        self.win.follow_workflow_hint()
        self.assertEqual(self.win.workflow.step, 1)
        self.assertEqual(self.win.workflow_hint()[1], 3)
        self.win.follow_workflow_hint()
        self.assertEqual(self.win.workflow.step, 3)
        self.win.panels[0].set_online(False)
        self.assertEqual(self.win.workflow_hint()[1], 0)
        self.win.follow_workflow_hint()
        self.assertEqual(self.win.workflow.step, 0)

    def test_typing_diameter_and_shared_metadata_invalidates_only_affected_pump(self):
        self.ready()
        self.win.write_review()
        self.idle()
        self.assertTrue(self.win.panels[0].settings_applied)
        self.assertTrue(self.win.panels[1].settings_applied)
        spin = self.win.workflow.diameter_inputs[0]
        spin.setValue(4.699)
        self.win.commit_diameter(0, spin)
        self.assertEqual(self.win.timeline_editor.model.diameters[0], 4.699)
        self.assertIsNone(self.win.panels[0].confirmed_diameter)
        self.assertTrue(self.win.panels[1].settings_applied)
        self.assertFalse(self.win.workflow.review_start.isEnabled())
        self.assertIn('1/2', self.win.workflow.progress.source_text)

    def test_invalid_or_partial_diameter_cannot_write_or_start_old_settings(self):
        self.ready((0,))
        self.win.write_review()
        self.idle()
        spin = self.win.workflow.diameter_inputs[0]
        self.win.diameter_text_pending(0)
        spin.setValue(14.431)
        self.win.commit_diameter(0, spin)
        self.assertIn(0, self.win._diameter_pending)
        with patch.object(self.win.controller, 'send_command', wraps=self.win.controller.send_command) as sent:
            self.win.write_review()
            self.win.start_review()
            sent.assert_not_called()
        self.assertFalse(self.win.panels[0].editor_run_button.isEnabled())

    def test_planning_navigation_and_simulation_send_no_device_commands(self):
        self.ready((0,))
        self.assertTrue(self.win.panels[1].isHidden())
        with patch.object(self.win.controller, 'send_command', wraps=self.win.controller.send_command) as sent:
            self.win.show_unused_checkbox.setChecked(True)
            self.assertFalse(self.win.panels[1].isHidden())
            self.win.show_unused_checkbox.setChecked(False)
            sent.assert_not_called()
        self.win.timeline_editor._load_model(example_timeline())
        with patch.object(self.win.controller, 'send_command', wraps=self.win.controller.send_command) as sent:
            for step in range(5):
                self.win.show_workflow_step(step)
            self.win.mode_tabs.setCurrentIndex(1)
            self.win.timeline_editor.check_flow()
            self.win.timeline_editor.start_preview()
            self.assertTrue(self.win.timeline_editor.running)
            self.win.emergency_stop()
            self.idle()
            self.assertFalse(self.win.timeline_editor.running)
            self.assertFalse(any(call.args[1].startswith('RUN') for call in sent.call_args_list))

    def test_manual_start_after_write_needs_no_mapping_or_tubing_checkbox(self):
        self.ready((0,))
        self.win.preparation.mapping_confirmed = False
        self.win.preparation.confirm_tubing(0, 'pending')
        self.win.write_review()
        self.idle()
        self.assertTrue(self.win.panels[0].settings_applied)
        self.assertTrue(self.win.workflow.review_start.isEnabled())
        self.assertFalse(self.win.preparation.mapping_confirmed)
        self.assertEqual(self.win.preparation.tubing[0], 'pending')
        self.win.start_review()
        self.idle()
        self.assertTrue(self.win.panels[0].running)
        self.win.emergency_stop()
        self.idle()
        self.assertFalse(self.win.panels[0].running)

    def test_unified_priming_never_auto_starts_formal(self):
        self.ready((0,))
        view = self.win.workflow
        self.win.change_tubing(0, 'needed')
        view.prep_rate.setValue(10)
        view.prep_volume.setValue(5)
        self.win.write_preparation()
        self.idle()
        self.assertTrue(self.win.panels[0].settings_applied)
        self.assertEqual(self.win.controller.pumps[0].status, 'S')
        self.assertTrue(view.prep_start.isEnabled())
        self.win.start_preparation()
        self.idle()
        self.assertTrue(self.win.panels[0].running)
        self.assertFalse(view.review_start.isEnabled())
        self.win.stop_preparation()
        self.idle()
        self.assertEqual(self.win.controller.pumps[0].status, 'P')
        self.assertTrue(self.win.panels[0].settings_applied)
        self.assertEqual(self.win.preparation.tubing[0], 'needed')

    def test_priming_text_change_invalidates_previous_program_before_focus_leaves(self):
        self.ready((0,))
        view = self.win.workflow
        view.prep_rate.setValue(10)
        view.prep_volume.setValue(5)
        self.win.write_preparation()
        self.idle()
        self.assertTrue(view.prep_start.isEnabled())
        view.prep_rate.lineEdit().textEdited.emit('20')
        self.assertFalse(view.prep_start.isEnabled())
        with patch.object(self.win.controller, 'send_command') as sent:
            self.win.start_preparation()
            sent.assert_not_called()

    def test_unit_selection_preserves_quantity_and_rejects_clamping(self):
        self.ready((0,))
        panel = self.win.panels[0]
        panel.rate_input.setValue(.6)
        panel.rate_unit_combo.setCurrentIndex(panel.rate_unit_combo.findData('UM'))
        self.assertAlmostEqual(panel.rate_input.value(), 10)
        panel.volume_input.setValue(1)
        panel.volume_unit_combo.setCurrentIndex(panel.volume_unit_combo.findData('UL'))
        self.assertEqual(panel.volume_input.value(), 1000)
        panel.rate_input.setValue(9999)
        panel.rate_unit_combo.setCurrentIndex(panel.rate_unit_combo.findData('MH'))
        self.assertEqual(panel.rate_input.value(), 599.94)
        panel.rate_input.setValue(9999)
        panel.rate_unit_combo.setCurrentIndex(panel.rate_unit_combo.findData('UM'))
        self.assertEqual(panel.rate_unit_combo.currentData(), 'MH')
        self.assertEqual(panel.rate_input.value(), 9999)

    def test_import_and_undo_sync_plan_but_never_import_readback_proof(self):
        self.ready((0,))
        self.win.write_review()
        self.idle()
        timeline = self.win.timeline_editor
        self.win.update_preparation(0, diameter=4.699)
        timeline.undo()
        self.assertEqual(self.win.preparation.plans[0].diameter, 10)
        data = timeline.model.to_json()
        timeline._load_model(Timeline.from_json(data))
        self.assertIsNone(self.win.panels[0].confirmed_diameter)
        self.assertFalse(self.win.preparation.mapping_confirmed)
        self.assertEqual(self.win.preparation.tubing[0], 'pending')

    def test_global_stop_is_available_for_offline_simulation(self):
        self.win.load_example_workflow()
        self.win.timeline_editor.check_flow()
        self.win.timeline_editor.start_preview()
        self.assertTrue(self.win.emergency_button.isEnabled())
        self.win.emergency_button.click()
        self.assertFalse(self.win.timeline_editor.running)

    def test_error_notice_keeps_global_stop_accessible(self):
        self.ready((0,))
        self.win.write_review()
        self.idle()
        self.win.start_review()
        self.idle()
        from ui.i18n_widgets import MessageBox
        MessageBox.warning(self.win, 'Operation Failed', 'Check pump and rescan')
        self.app.processEvents()
        self.assertIsNone(self.app.activeModalWidget())
        self.assertTrue(self.win.emergency_button.isEnabled())
        self.win.emergency_button.click()
        self.idle()
        self.assertFalse(self.win.panels[0].running)
        for notice in list(self.win._notice_windows):
            notice.close()

    def test_requested_stop_must_confirm_before_disconnect_or_close(self):
        self.ready((0,))
        from ne501.stop_report import StopAllReport
        from ui.i18n_widgets import MessageBox
        controller = self.win.controller
        self.win.timeline_editor.saved_snapshot = self.win.timeline_editor.model.to_json()
        with patch('ui.main_window.stop_all_independently', return_value=StopAllReport(unconfirmed={0: 'No response'})), patch('ui.main_window.QMessageBox.question', return_value=MessageBox.StandardButton.Yes):
            self.win.disconnect_controller()
            self.assertIs(self.win.controller, controller)
            self.assertTrue(controller.is_connected)
            self.assertFalse(self.win.close())
            self.assertTrue(self.win.isVisible())
        self.assertTrue(self.win.emergency_button.isEnabled())
        for notice in list(self.win._notice_windows):
            notice.close()

    def test_manual_console_starts_exactly_one_pump_without_page_change(self):
        self.ready()
        self.win.write_review()
        self.idle()
        panel = self.win.panels[1]
        self.win.show_workflow_step(3)
        self.win.select_pump(1)
        with patch.object(self.win.controller, 'send_command', wraps=self.win.controller.send_command) as sent:
            panel.editor_run_button.click()
            self.idle()
            self.assertEqual(self.win.workflow.step, 3)
            self.assertEqual([c.args[0] for c in sent.call_args_list if c.args[1].startswith('RUN')],[1])
        self.assertTrue(panel.running)
        self.assertFalse(self.win.panels[0].running)
        self.win.emergency_stop()
        self.idle()

    def test_three_manual_stages_languages_sizes_scales_and_input_contrast(self):
        self.ready()
        self.win.show_workflow_step(1)
        shots = Path(__file__).resolve().parents[1] / 'builds/ui-shots-source'
        shots.mkdir(parents=True, exist_ok=True)
        for language in ('zh_TW', 'en'):
            manager.set_language(language)
            for scale in (1., 1.15, 1.3):
                self.app.setStyleSheet(build_stylesheet(scale))
                for width, height in ((1024, 768), (1366, 768)):
                    self.win.resize(width, height)
                    for step in (0,1,3):
                        self.win.show_workflow_step(step)
                        self.app.processEvents()
                        self.assertLessEqual(self.win.width(), width)
                        self.assertLessEqual(self.win.height(), height)
                        buttons = [b for b in self.win.workflow.steps if b.isVisible()] + [self.win.emergency_button]
                        if self.win.workflow.next_button.isVisible():
                            buttons.append(self.win.workflow.next_button)
                        for button in buttons:
                            point = button.mapTo(self.win, QPoint(0, 0))
                            self.assertGreaterEqual(point.x(), 0)
                            self.assertLessEqual(point.x() + button.width(), width)
                            self.assertLessEqual(point.y() + button.height(), height)
                        if scale in (1., 1.3) and width == 1366:
                            self.win.grab().save(str(shots / f'workflow-step{step + 1}-{language}-{round(scale * 100)}.png'))
                        if language == 'en':
                            for cls in (QLabel, QPushButton, QCheckBox):
                                for widget in self.win.findChildren(cls):
                                    if widget.isVisible():
                                        self.assertFalse(re.search(r'[\u3400-\u9fff]', widget.text()), widget.text())
        model = example_timeline()
        model.set_preparation([4.699, 14.43, None, None], [True, True, False, False], ['Sample', 'Buffer', '', ''], ['A', 'B', '', ''])
        self.win.timeline_editor._load_model(model)
        self.win.mode_tabs.setCurrentIndex(1)
        self.win.show_workflow_step(3)
        self.app.setStyleSheet(build_stylesheet(1.))
        self.win.resize(1366, 768)
        for language in ('zh_TW', 'en'):
            manager.set_language(language)
            self.app.processEvents()
            self.win.grab().save(str(shots / f'workflow-timeline-{language}-100.png'))
        # Compare the stylesheet's chosen text/control colors, not antialiased pixels.
        def luminance(hex_color):
            channels = [int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5)]
            linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
            return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))
        light, dark = luminance('#f5f8fc'), luminance('#172434')
        self.assertGreaterEqual((light + .05) / (dark + .05), 4.5)


if __name__ == '__main__':
    unittest.main()
