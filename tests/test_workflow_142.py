"""Functional tabs, demo backend and preview labels stay independent."""
from pathlib import Path
import unittest
from unittest.mock import patch

import test_workflow_141 as helpers
from ne501.controller import NE501Controller
from ne501.mock_controller import MockNE501Controller
from ui.i18n import manager
from ui.i18n_widgets import MessageBox


class TerminologyTests(unittest.TestCase):
    setUpClass = classmethod(helpers.ModeWorkflowTests.setUpClass.__func__)
    setUp = helpers.ModeWorkflowTests.setUp
    tearDown = helpers.ModeWorkflowTests.tearDown
    idle = helpers.ModeWorkflowTests.idle
    ready = helpers.ModeWorkflowTests.ready

    def test_blank_offline_project_has_function_tab_and_untitled_filename(self):
        w = self.win
        for language, tab, filename, offline in (
                ('zh_TW', '流程編輯', '未命名流程', '離線規劃'),
                ('en', 'Timeline Editor', 'Untitled workflow', 'Offline planning')):
            manager.set_language(language)
            w.workflow.mode_selector.setCurrentIndex(1)
            self.assertEqual(w.workflow.mode_selector.tabText(1), tab)
            self.assertEqual(w.timeline_editor.file_label.text(), filename)
            self.assertIn(offline, w.execution_label.text())
            self.assertNotIn('示範模式', w.execution_label.text())
            self.assertNotIn('Demo mode', w.execution_label.text())

    def test_demo_connection_is_explicit_and_preview_and_language_changes_never_run_pumps(self):
        w = self.win
        w.port_combo.setCurrentIndex(w.port_combo.findData('MOCK'))
        self.assertIn('示範模式', w.port_combo.currentText())
        w.connect_controller()
        self.idle()
        self.assertIsInstance(w.controller, MockNE501Controller)
        self.assertIn('示範模式', w.connection_label.text())
        with patch.object(w.controller, 'send_command', wraps=w.controller.send_command) as sent:
            w.load_example_workflow()
            w.timeline_editor.check_flow()
            w.timeline_editor.start_preview()
            self.assertTrue(w.timeline_editor.running)
            for language, kind in (('zh_TW', '示範模式'), ('en', 'Demo mode')):
                manager.set_language(language)
                self.assertIn(kind, w.execution_label.text())
                self.assertIn(kind, w.connection_label.text())
            self.assertFalse(any(p.running for p in w.panels.values()))
            sent.assert_not_called()
        manager.set_language('zh_TW')
        w.timeline_editor.stop_preview()
        w.show_workflow_step(0)
        self.capture('workflow-demo-status-zh_TW-100.png')

    def test_real_connection_stays_real_when_an_example_is_previewed(self):
        class InertSerial:
            is_open = True
            def close(self):
                self.is_open = False

        # Never open a serial port. The real controller type only supplies its
        # connection category; every device operation is patched and monitored.
        w = self.win
        controller = NE501Controller()
        controller._serial = InertSerial()
        w.controller = controller
        w.connection_label.setText('● Connected COM4')
        w.connection_label.setObjectName('onlineStatus')
        w.connection_label.style().unpolish(w.connection_label)
        w.connection_label.style().polish(w.connection_label)
        w.refresh_group_controls()
        with patch.object(controller, 'send_command') as sent:
            w.load_example_workflow()
            w.timeline_editor.check_flow()
            w.play_review_flow()
            self.assertTrue(w.timeline_editor.running)
            for language, kind, demo in (('zh_TW', '實機連線', '示範模式'),
                                          ('en', 'Real pump connection', 'Demo mode')):
                manager.set_language(language)
                self.assertIn(kind, w.execution_label.text())
                self.assertNotIn(demo, w.execution_label.text())
            sent.assert_not_called()
        manager.set_language('zh_TW')
        w.timeline_editor.stop_preview()
        w.show_workflow_step(4)
        self.assertIn('不傳送幫浦啟動指令', w.workflow.review_note.text())
        self.capture('workflow-real-preview-zh_TW-100.png')

    def test_disconnect_without_stop_retains_an_unconfirmed_stop_warning(self):
        self.ready()
        w = self.win
        w.controller.send_command(0, 'RUN 1')
        w.panels[0].update_from_status('I')
        with patch('ui.main_window.QMessageBox.question', return_value=MessageBox.StandardButton.No):
            w.disconnect_controller()
        self.assertIsNone(w.controller)
        self.assertTrue(w.panels[0].running)
        for language, warning in (('zh_TW', '停止未確認：P1'), ('en', 'Stop unconfirmed: P1')):
            manager.set_language(language)
            self.assertIn(warning, w.execution_label.text())
        self.assertFalse(w.can_use_timeline())

    def capture(self, filename):
        folder = Path(__file__).resolve().parents[1] / 'builds/ui-shots-source'
        folder.mkdir(parents=True, exist_ok=True)
        self.app.processEvents()
        self.assertTrue(self.win.grab().save(str(folder / filename)))


if __name__ == '__main__':
    unittest.main()
