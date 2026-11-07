"""Mode boundaries, stale-device-proof failures and retained cross-mode drafts."""
from dataclasses import replace
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QCheckBox
from ne501.mock_controller import MockNE501Controller
from ne501.timeline_model import Timeline, Clip
from ui.main_window import MainWindow
from ui.fonts import configure_ui_font
from ui.i18n import manager
from ui.style import build_stylesheet


class ModeWorkflowTests(unittest.TestCase):
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
        self.win.age_timer.stop()
        self.win.timeline_editor.stop_preview()
        if self.win.controller:
            self.win.controller.disconnect()
        self.win.controller = None
        self.win.timeline_editor.dirty = self.win.timeline_editor.duration_dirty = False
        self.win.timeline_editor.saved_snapshot = self.win.timeline_editor.model.to_json()
        self.win.close()
        self.app.processEvents()
        self.folder.cleanup()
        manager.set_language('zh_TW')
        self.app.setStyleSheet(build_stylesheet())

    def idle(self):
        deadline = time.monotonic() + 8
        while self.win.pending_tasks and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertEqual(self.win.pending_tasks, 0)

    def ready(self, addresses=(0,)):
        self.win.controller = MockNE501Controller([0, 1, 2, 3], latency=0)
        self.win.controller.connect()
        for panel in self.win.panels.values():
            panel.set_online(True)
            panel.update_from_status('S')
        for address in addresses:
            self.win.update_preparation(address, used=True, diameter=10)
        self.win.preparation.mapping_confirmed = True
        for address in addresses:
            self.win.change_tubing(address, 'done')
        self.win.refresh_group_controls()

    def arm_priming(self, address=0, volume=5, unit='UL'):
        view = self.win.workflow
        view.prep_pump.setCurrentIndex(view.prep_pump.findData(address))
        view.prep_rate_unit.setCurrentIndex(view.prep_rate_unit.findData('UM'))
        view.prep_rate.setValue(10)
        view.prep_volume_unit.setCurrentIndex(view.prep_volume_unit.findData(unit))
        view.prep_volume.setValue(volume)
        self.win.write_preparation()
        self.idle()
        self.assertTrue(view.prep_start.isEnabled())

    def load_flow(self):
        self.win.timeline_editor._load_model(Timeline(600, [Clip('a', 0, 0, 300, 'INF', 10, 'µL/min')],
                                                      diameters=[10, None, None, None]))

    def test_flow_has_four_steps_and_no_manual_device_write_entry(self):
        self.ready()
        self.arm_priming()
        self.win.show_workflow_step(2)
        view = self.win.workflow
        self.assertEqual(sum(b.isVisible() for b in view.steps), 5)
        view.mode_selector.setCurrentIndex(1)
        self.assertEqual(self.win.mode_tabs.currentIndex(), 1)
        self.assertEqual(view.step, 3)
        self.assertEqual(sum(b.isVisible() for b in view.steps), 4)
        self.assertTrue(view.steps[2].isHidden())
        self.win.show_workflow_step(2)
        self.assertEqual(view.step, 3)
        self.win.show_workflow_step(1)
        self.assertTrue(view.diameter_buttons[0].isHidden())
        # Force-enabled buttons cannot bypass the handlers' mode checks.
        view.prep_start.setEnabled(True)
        view.prep_write.setEnabled(True)
        with patch.object(self.win.controller, 'send_command', wraps=self.win.controller.send_command) as sent:
            self.win.write_preparation()
            self.win.start_preparation()
            self.win.write_plan_diameter(0)
            self.win.set_diameter(0, 10)
            self.win.write_review()
            self.win.start_review()
            self.win.apply_single(0, self.win.panels[0].current_settings())
            self.win.run_single_command(0, 'RUN 1', self.win.panels[0])
            self.win.group_command([self.win.panels[0]], 'RUN 1')
            self.idle()
            sent.assert_not_called()
        view.mode_selector.setCurrentIndex(0)
        self.assertTrue(view.prep_start.isEnabled())
        self.assertEqual(sum(b.isVisible() for b in view.steps), 5)

    def test_same_diameter_rewrite_cannot_rearm_stale_volume_units(self):
        self.ready()
        self.arm_priming(volume=10, unit='ML')
        self.assertEqual(self.win.controller.pumps[0].volume_unit, 'ML')
        self.win.set_diameter(0, 10)
        self.assertFalse(self.win.workflow.prep_start.isEnabled())
        self.idle()
        self.assertEqual(self.win.controller.pumps[0].volume_unit, 'UL')
        with patch.object(self.win.controller, 'send_command', wraps=self.win.controller.send_command) as sent:
            self.win.start_preparation()
            self.idle()
            sent.assert_not_called()
        self.arm_priming(volume=10, unit='ML')
        self.assertEqual(self.win.controller.pumps[0].volume_unit, 'ML')

    def test_failed_formal_write_and_diameter_recheck_require_new_priming_write(self):
        self.ready()
        self.arm_priming()
        panel = self.win.panels[0]
        panel.rate_unit_combo.setCurrentIndex(panel.rate_unit_combo.findData('UM'))
        panel.rate_input.setValue(99)
        configure = self.win.controller.configure_program

        def bad_readback(address, settings):
            return replace(configure(address, settings), verified=False, message='Injected read-back mismatch')

        with patch.object(self.win.controller, 'configure_program', side_effect=bad_readback):
            self.win.apply_single(0, panel.current_settings())
            self.idle()
        self.assertEqual(self.win.controller.pumps[0].phases[1].rate, 99)
        self.win.set_diameter(0, 10)
        self.idle()
        self.assertFalse(self.win.workflow.prep_start.isEnabled())
        with patch.object(self.win.controller, 'send_command', wraps=self.win.controller.send_command) as sent:
            self.win.start_preparation()
            self.idle()
            sent.assert_not_called()
        self.arm_priming()
        self.assertEqual(self.win.controller.pumps[0].phases[1].rate, 10)

    def test_write_exception_cannot_restore_old_proof_after_reconnect_checks(self):
        self.ready()
        self.arm_priming()
        with patch.object(self.win.controller, 'set_diameter', side_effect=TimeoutError('Injected timeout')):
            self.win.set_diameter(0, 10)
            self.idle()
        panel = self.win.panels[0]
        panel.set_online(True)
        panel.update_from_status('S')
        self.win.set_diameter(0, 10)
        self.idle()
        self.assertFalse(self.win.workflow.prep_start.isEnabled())
        self.assertNotIn(0, self.win._prep_verified)

    def test_rewrite_invalidates_only_the_target_pump(self):
        self.ready((0, 1))
        self.arm_priming(0)
        self.arm_priming(1)
        self.win.set_diameter(0, 10)
        self.idle()
        self.assertTrue(self.win.workflow.prep_start.isEnabled())
        self.assertIn(1, self.win._prep_verified)
        self.win.workflow.prep_pump.setCurrentIndex(0)
        self.assertFalse(self.win.workflow.prep_start.isEnabled())

    def test_hidden_block_draft_does_not_block_manual_review_or_shared_diameter(self):
        self.load_flow()
        self.ready()
        timeline = self.win.timeline_editor
        self.win.mode_tabs.setCurrentIndex(1)
        self.win.show_workflow_step(3)
        timeline.rate_spin.setValue(20)
        draft = timeline.rate_spin.lineEdit().text()
        self.assertTrue(timeline.dirty)
        self.win.mode_tabs.setCurrentIndex(0)
        self.win.review_single(0)
        self.assertEqual(self.win.workflow.step, 4)
        self.assertTrue(self.win.update_preparation(0, diameter=12))
        self.assertTrue(timeline.dirty)
        self.assertEqual(timeline.rate_spin.lineEdit().text(), draft)
        self.assertEqual(timeline.model.diameters[0], 12)
        self.assertFalse(timeline.checked)
        self.win.mode_tabs.setCurrentIndex(1)
        self.win.show_workflow_step(3)
        self.assertTrue(timeline.apply_clip())
        self.assertEqual(timeline.model.get('a').rate, 20)
        timeline.check_flow()
        self.assertTrue(timeline.checked)

    def test_duration_draft_survives_manual_metadata_update_and_cancel(self):
        self.load_flow()
        timeline = self.win.timeline_editor
        self.win.mode_tabs.setCurrentIndex(1)
        timeline.duration_spin.setValue(80)
        self.assertTrue(timeline.duration_dirty)
        self.win.mode_tabs.setCurrentIndex(0)
        self.assertTrue(self.win.update_preparation(0, fluid='Buffer A'))
        self.assertTrue(timeline.duration_dirty)
        self.assertEqual(timeline.duration_spin.value(), 80)
        self.assertEqual(timeline.model.names[0], 'Buffer A')
        timeline.cancel_duration()
        self.assertEqual(timeline.model.total, 600)
        self.assertEqual(timeline.model.names[0], 'Buffer A')

    def test_unrelated_clip_edit_retains_uncommitted_diameter_and_blocks_playback(self):
        self.load_flow()
        self.win.diameter_text_pending(0)
        self.win.workflow.diameter_inputs[0].lineEdit().setText('')
        self.win.mode_tabs.setCurrentIndex(1)
        timeline = self.win.timeline_editor
        timeline.rate_spin.setValue(20)
        self.assertTrue(timeline.apply_clip())
        self.assertIn(0, self.win._diameter_pending)
        timeline.check_flow()
        self.assertFalse(timeline.checked)
        self.assertFalse(timeline.can_start_preview())
        self.assertFalse(timeline.check_button.isEnabled())
        self.assertFalse(self.win.workflow.review_check.isEnabled())

    def test_single_review_guide_uses_the_same_targets_as_start(self):
        self.ready((0, 1))
        self.win.update_preparation(1, diameter=None)
        self.win.preparation.mapping_confirmed = True
        self.win.change_tubing(0, 'done')
        self.win.apply_single(0, self.win.panels[0].current_settings())
        self.idle()
        self.win.review_single(0)
        self.assertTrue(self.win.workflow.review_start.isEnabled())
        self.assertEqual(self.win.review_addresses(), [0])
        self.assertEqual(self.win.workflow_hint()[1], 4)
        self.assertNotIn('P2', self.win.workflow.next_hint.source_text)
        self.assertEqual(self.win.workflow.progress.source_text, 'Review targets: P1')
        self.win.workflow.review_scope.setCurrentIndex(0)
        self.assertIn('P2', self.win.workflow.next_hint.source_text)
        self.assertFalse(self.win.workflow.review_start.isEnabled())

    def test_review_and_direct_simulation_share_device_and_pending_command_locks(self):
        self.load_flow()
        self.ready()
        self.win.mode_tabs.setCurrentIndex(1)
        timeline = self.win.timeline_editor
        timeline.check_flow()
        self.assertTrue(timeline.checked)
        self.win.show_workflow_step(4)
        self.win.panels[0].update_from_status('I')
        self.win.refresh_group_controls()
        self.assertFalse(timeline.isEnabled())
        self.assertFalse(self.win.workflow.review_play.isEnabled())
        self.win.workflow.review_play.setEnabled(True)
        self.win.play_review_flow()
        timeline.start_preview()
        self.assertFalse(timeline.running)
        self.win.panels[0].update_from_status('S')
        self.win.pending_tasks = 1
        self.win.refresh_group_controls()
        self.win.play_review_flow()
        self.assertFalse(timeline.running)
        self.win.pending_tasks = 0
        self.win.refresh_group_controls()
        self.assertTrue(self.win.workflow.review_play.isEnabled())
        with patch.object(self.win.controller, 'send_command', wraps=self.win.controller.send_command) as sent:
            self.win.play_review_flow()
            self.assertTrue(timeline.running)
            sent.assert_not_called()

    def test_offline_flow_review_counts_all_blocks_without_manual_priming_columns(self):
        model = Timeline(600, [Clip('prime', 0, 0, 60, 'INF', 60, 'µL/min'),
                               Clip('main', 0, 60, 600, 'INF', 10, 'µL/min')], diameters=[10, None, None, None])
        self.win.timeline_editor._load_model(model)
        self.win.mode_tabs.setCurrentIndex(1)
        self.assertEqual(self.win.workflow_hint()[1], 3)
        self.assertTrue(self.win.workflow.steps[0].property('complete'))
        self.win.show_workflow_step(4)
        view = self.win.workflow
        self.assertEqual(view.review_table.columnCount(), 4)
        self.assertIn('15 µL', view.review_table.item(0, 2).text())
        self.assertTrue(view.review_scope.isHidden())
        self.assertTrue(view.review_write.isHidden())
        self.assertTrue(view.review_start.isHidden())
        view.review_check.click()
        view.review_play.click()
        self.assertTrue(self.win.timeline_editor.running)

    def test_mode_routes_fit_both_languages_small_screens_and_large_scale(self):
        self.load_flow()
        shots = Path(__file__).resolve().parents[1] / 'builds/ui-shots-source'
        shots.mkdir(parents=True, exist_ok=True)
        for language in ('zh_TW', 'en'):
            manager.set_language(language)
            for scale in (1., 1.3):
                self.win.ui_scale_combo.setCurrentIndex(self.win.ui_scale_combo.findData(scale))
                for mode, route in ((0, (0, 1, 2, 3, 4)), (1, (0, 1, 3, 4))):
                    self.win.workflow.mode_selector.setCurrentIndex(mode)
                    for width, height in ((1024, 768), (1366, 768)):
                        self.win.resize(width, height)
                        for step in route:
                            with self.subTest(language=language, scale=scale, mode=mode, width=width, step=step):
                                self.win.show_workflow_step(step)
                                self.app.processEvents()
                                self.assertLessEqual(self.win.width(), width)
                                self.assertLessEqual(self.win.height(), height)
                                self.assertEqual(sum(b.isVisible() for b in self.win.workflow.steps), len(route))
                                for button in [b for b in self.win.workflow.steps if b.isVisible()] + [self.win.emergency_button, self.win.workflow.mode_selector]:
                                    point = button.mapTo(self.win, QPoint(0, 0))
                                    self.assertGreaterEqual(point.x(), 0)
                                    self.assertLessEqual(point.x() + button.width(), width)
                                    self.assertLessEqual(point.y() + button.height(), height)
                                if language == 'en':
                                    for cls in (QLabel, QPushButton, QCheckBox):
                                        for widget in self.win.findChildren(cls):
                                            if widget.isVisible():
                                                self.assertFalse(re.search(r'[\u3400-\u9fff]', widget.text()), widget.text())
                                if width == 1366 and (mode == 1 and step in (0, 1, 4) or mode == 0 and step == 2):
                                    name = f'workflow-{"flow" if mode else "manual"}-step{route.index(step) + 1}-{language}-{round(scale * 100)}.png'
                                    self.assertTrue(self.win.grab().save(str(shots / name)))


if __name__ == '__main__':
    unittest.main()
