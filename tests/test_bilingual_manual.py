"""Language, manual-dashboard readiness and geometry regressions; no real hardware."""
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PySide6.QtCore import QSettings,QPoint
    from PySide6.QtWidgets import QApplication,QLabel,QPushButton,QCheckBox,QGroupBox
    from ui.main_window import MainWindow
    from ui.fonts import configure_ui_font
    from ui.style import build_stylesheet
    from ui.i18n import manager,tr,CATALOG
    HAVE_QT=True
except ImportError:HAVE_QT=False
from ne501.mock_controller import MockNE501Controller

@unittest.skipUnless(HAVE_QT,'PySide6 is not installed')
class BilingualManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion');configure_ui_font(cls.app)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.settings=QSettings(str(Path(self.temp.name)/'preferences.ini'),QSettings.Format.IniFormat)
        self.win=MainWindow({'addresses':[0,1,2,3],'port':'MOCK'},settings=self.settings)
        from ne501.timeline_model import example_timeline
        self.win.timeline_editor._load_model(example_timeline([0,1,2,3]))
        self.win.show_workflow_step(3)
        self.win.show();self.app.processEvents()
    def tearDown(self):
        self.win.poll_timer.stop();self.win.age_timer.stop()
        if self.win.controller is not None:self.win.controller.disconnect()
        self.win.controller=None
        self.win.timeline_editor.saved_snapshot=self.win.timeline_editor.model.to_json()
        self.win.timeline_editor.dirty=self.win.timeline_editor.duration_dirty=False
        self.win.close();manager.set_language('zh_TW');self.temp.cleanup()
    def ready_mock(self):
        self.win.controller=MockNE501Controller([0,1,2,3],latency=0);self.win.controller.connect('MOCK',19200)
        self.win.connection_label.setText('● Connected MOCK');self.win.connection_label.setObjectName('onlineStatus');self.win.connection_label.style().unpolish(self.win.connection_label);self.win.connection_label.style().polish(self.win.connection_label);self.win.connect_button.setText('Disconnect')
        self.win._set_group_buttons_enabled(True)
        for panel in self.win.panels.values():panel.set_online(True);panel.update_from_status('S')
        self.win.preparation.mapping_confirmed=True
        for a in self.win.addresses:self.win.preparation.confirm_tubing(a,'done')
        self.win.refresh_group_controls()
    def wait_idle(self):
        deadline=time.monotonic()+10
        while self.win.pending_tasks and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
        self.assertEqual(self.win.pending_tasks,0)
    def test_language_switch_preserves_values_selection_draft_and_playback(self):
        self.ready_mock();panel=self.win.panels[0]
        panel.confirm_diameter(10);panel.rate_input.setValue(2.5);panel.direction_combo.setCurrentIndex(1)
        panel.mark_settings_applied();panel.set_active(True)
        timeline=self.win.timeline_editor;timeline.check_flow();timeline.seek(200);timeline.start_preview();timeline.pause_preview()
        before=(panel.current_settings(),panel.confirmed_diameter,panel.settings_applied,panel.is_active(),timeline.model.to_json(),timeline.playhead,timeline.checked,timeline.canvas.selected)
        with patch.object(self.win.controller,'send_command',wraps=self.win.controller.send_command) as commands:
            for language in ('en','zh_TW','en','zh_TW'):
                self.win.language_combo.setCurrentIndex(self.win.language_combo.findData(language));self.app.processEvents()
                after=(panel.current_settings(),panel.confirmed_diameter,panel.settings_applied,panel.is_active(),timeline.model.to_json(),timeline.playhead,timeline.checked,timeline.canvas.selected)
                self.assertEqual(after,before)
            commands.assert_not_called()
        self.assertEqual(self.settings.value('language'),'zh_TW')
        timeline.stop_preview()
    def test_language_switch_retains_unapplied_timeline_fields(self):
        timeline=self.win.timeline_editor
        timeline.rate_spin.setValue(12.3);self.assertTrue(timeline.dirty)
        manager.set_language('en');manager.set_language('zh_TW')
        self.assertTrue(timeline.dirty);self.assertEqual(timeline.rate_spin.value(),12.3)
        self.assertFalse(timeline.play_button.isEnabled());self.assertFalse(timeline.save_button.isEnabled())
        timeline.cancel_clip()
    def test_manual_group_readiness_and_editor_selection_are_independent(self):
        self.ready_mock();p0,p1=self.win.panels[0],self.win.panels[1]
        self.assertFalse(self.win.run_active_button.isEnabled())
        p0.confirm_diameter(10);p0.set_active(True)
        self.assertTrue(self.win.apply_active_button.isEnabled());self.assertFalse(self.win.run_active_button.isEnabled())
        p0.mark_settings_applied();self.assertTrue(self.win.run_active_button.isEnabled())
        self.win.select_pump(1);self.assertEqual(self.win.selected_address,1);self.assertTrue(p0.is_active());self.assertFalse(p1.is_active())
        p0.rate_input.setValue(2);self.assertFalse(self.win.run_active_button.isEnabled())
        self.assertTrue(p0.stop_button.isEnabled())
        p0.set_online(False);self.assertTrue(p0.stop_button.isEnabled());self.assertFalse(p0.is_active())
    def test_manual_apply_readback_run_and_stop_use_existing_controller(self):
        self.ready_mock();panel=self.win.panels[0]
        self.win.set_diameter(0,10);self.wait_idle()
        self.assertIsNotNone(panel.confirmed_diameter)
        self.win.apply_single(0,panel.current_settings());self.wait_idle()
        self.assertTrue(panel.settings_applied)
        self.assertIsNotNone(panel.applied_snapshot)
        self.win.run_single(0);self.wait_idle();self.assertTrue(panel.running)
        self.win.stop_single(0);self.wait_idle()
        self.assertFalse(panel.running);self.assertEqual(panel.last_status,'S')
    def test_manual_status_refresh_and_opt_in_poll_do_not_accumulate(self):
        self.ready_mock();self.assertFalse(self.win.auto_refresh_checkbox.isChecked())
        self.win.refresh_status();self.wait_idle()
        self.assertTrue(all(p.last_checked for p in self.win.panels.values()))
        self.win.pending_tasks=1
        with patch.object(self.win,'refresh_status') as refresh:
            self.win.auto_refresh_checkbox.setChecked(True);self.win.mode_tabs.setCurrentIndex(0)
            self.win.maybe_refresh_status();refresh.assert_not_called()
        self.win.pending_tasks=0
    def test_translation_templates_preserve_raw_values(self):
        for en,zh in CATALOG:
            self.assertEqual(set(re.findall(r'\{(\w+)\}',en)),set(re.findall(r'\{(\w+)\}',zh)),en)
        manager.set_language('zh_TW')
        self.assertIn('COM4',tr('● Connected COM4'))
        self.assertIn('14.43',tr('✓ Verified: 14.43 mm'))
        self.assertIn('µL/min',tr('Draft: Infuse · 12.3 µL/min'))
        manager.set_language('en')
        self.assertEqual(tr('幫浦 1 · 區塊設定'),'Pump 1 · Clip settings')
    def test_english_view_has_no_untranslated_chinese_labels(self):
        manager.set_language('en')
        for index in (0,1):
            self.win.mode_tabs.setCurrentIndex(index);self.app.processEvents()
            for cls in (QLabel,QPushButton,QCheckBox,QGroupBox):
                for widget in self.win.findChildren(cls):
                    if not widget.isVisible():continue
                    text=widget.title() if isinstance(widget,QGroupBox) else widget.text()
                    self.assertFalse(re.search(r'[\u3400-\u9fff]',text),(type(widget).__name__,text))
    def test_both_modes_languages_sizes_and_scales_fit_and_capture(self):
        shots=Path(__file__).resolve().parents[1]/'builds/ui-shots-source';shots.mkdir(parents=True,exist_ok=True)
        problems=[]
        self.ready_mock()
        for address in (0,1,3):
            self.win.panels[address].confirm_diameter(10);self.win.panels[address].mark_settings_applied()
            panel=self.win.panels[address]
            confirmation=self.win.controller.configure_program(address,self.win.build_program_settings(panel,panel.current_settings()))
            panel.set_program_confirmation(confirmation)
        self.win.panels[1].update_from_status('I')
        self.win.panels[3].continuous_checkbox.setChecked(False);self.win.panels[3].direction_combo.setCurrentIndex(1)
        self.win.panels[3].mark_settings_applied()
        for language in ('zh_TW','en'):
            manager.set_language(language)
            for scale in (1.,1.3):
                self.win.ui_scale_combo.setCurrentIndex(self.win.ui_scale_combo.findData(scale))
                self.app.setStyleSheet(build_stylesheet(scale))
                for width,height in ((1280,850),(1024,768),(1366,768),(1920,1080)):
                    for index,name in ((0,'manual'),(1,'timeline')):
                        self.win.mode_tabs.setCurrentIndex(index);self.win.resize(width,height);self.app.processEvents()
                        filename=shots/f'{name}-{language}-{width}-{round(scale*100)}.png'
                        self.win.grab().save(str(filename))
                        if self.win.width()>width or self.win.height()>height:problems.append((filename.name,'window',self.win.size().toTuple()))
                        if index==0:
                            viewport=self.win.panel_scroll.viewport()
                            for address,panel in self.win.panels.items():
                                point=panel.stop_button.mapTo(viewport,QPoint(0,0))
                                if not viewport.rect().contains(point) or point.y()+panel.stop_button.height()>viewport.height():
                                    problems.append((filename.name,'stop',address,point.toTuple(),viewport.size().toTuple(),panel.size().toTuple()))
                        if index==0:
                            viewport=self.win.editor_scroll.viewport()
                            panel=self.win.panels[self.win.selected_address]
                            for field in (panel.diameter_input,panel.set_diameter_button,panel.rate_unit_combo,panel.direction_combo,panel.mode_combo):
                                if not field.isVisible():continue
                                point=field.mapTo(viewport,QPoint(0,0))
                                if point.x()<0 or point.x()+field.width()>viewport.width():problems.append((filename.name,'inspector width',point.toTuple(),field.size().toTuple(),viewport.size().toTuple()))
                            for button in (panel.apply_button,panel.editor_run_button,panel.editor_stop_button):
                                point=button.mapTo(self.win,QPoint(0,0))
                                if point.x()<0 or point.x()+button.width()>self.win.width() or point.y()+button.height()>self.win.height():
                                    problems.append((filename.name,'action footer',point.toTuple(),button.size().toTuple()))
        self.assertFalse(problems,problems)

    def test_group_apply_reports_successes_when_one_pump_fails(self):
        self.ready_mock()
        for panel in self.win.panels.values():panel.confirm_diameter(10);panel.set_active(True)
        original=self.win.controller.configure_program
        def configure(address,settings):
            if address==1:raise RuntimeError('Simulated channel failure')
            return original(address,settings)
        with patch.object(self.win.controller,'configure_program',side_effect=configure),patch('ui.main_window.QMessageBox.warning'):
            self.win.apply_active();self.wait_idle()
        self.assertTrue(self.win.panels[0].settings_applied)
        self.assertFalse(self.win.panels[1].online)
        self.assertTrue(self.win.panels[2].settings_applied)
        self.assertTrue(self.win.panels[3].settings_applied)
    def test_group_run_stops_sending_after_first_error(self):
        self.ready_mock()
        for address in (0,1,2):
            panel=self.win.panels[address];panel.confirm_diameter(10);panel.mark_settings_applied();panel.set_active(True)
        original=self.win.controller.send_command
        sent=[]
        def send(address,command):
            if command=='RUN 1':
                sent.append(address)
                if address==1:raise RuntimeError('Simulated channel failure')
            return original(address,command)
        with patch.object(self.win.controller,'send_command',side_effect=send),patch('ui.main_window.QMessageBox.warning'):
            self.win.run_active();self.wait_idle()
        self.assertEqual(sent,[0,1])
        self.assertTrue(self.win.panels[0].running)
        self.assertFalse(self.win.panels[2].running)
        self.assertEqual(self.win.panels[2].last_response_source,'Not sent after an earlier group error')
    def test_manual_and_timeline_use_same_logical_index_and_custom_addresses(self):
        isolated=QSettings(str(Path(self.temp.name)/'custom.ini'),QSettings.Format.IniFormat)
        other=MainWindow({'addresses':[5,7,8,9]},settings=isolated)
        try:
            self.assertEqual(other.timeline_editor.model.addresses,[5,7,8,9])
            for index,address in enumerate([5,7,8,9],1):
                self.assertEqual(other.panels[address].index,index)
                self.assertEqual(other.panels[address].address,address)
        finally:other.close()

    def test_alarm_invalidates_setup_and_keeps_stop_available(self):
        self.ready_mock();panel=self.win.panels[0]
        panel.confirm_diameter(10);panel.mark_settings_applied()
        panel.update_from_status('A')
        self.assertFalse(panel.settings_applied);self.assertIsNone(panel.confirmed_diameter)
        self.assertFalse(panel.run_button.isEnabled());self.assertTrue(panel.stop_button.isEnabled())
        self.assertFalse(panel.set_diameter_button.isEnabled())
        panel.update_from_status('S')
        self.assertTrue(panel.set_diameter_button.isEnabled());self.assertFalse(panel.run_button.isEnabled())
    def test_unknown_motion_status_never_enables_start(self):
        self.ready_mock();panel=self.win.panels[0]
        panel.confirm_diameter(10);panel.mark_settings_applied()
        panel.update_from_status(None)
        self.assertFalse(panel.settings_applied);self.assertFalse(panel.run_button.isEnabled())
        self.assertTrue(panel.stop_button.isEnabled())
        self.assertEqual(panel.status_label.source_text,'● STATUS UNCONFIRMED')

    def test_language_preference_is_restored_by_a_new_window(self):
        self.win.language_combo.setCurrentIndex(self.win.language_combo.findData('en'))
        self.settings.sync()
        second=MainWindow({'addresses':[0,1,2,3]},settings=self.settings)
        try:
            self.assertEqual(second.language_combo.currentData(),'en')
            self.assertEqual(second.mode_tabs.tabText(0),'Manual Control')
        finally:second.close()

    def test_auto_refresh_waits_while_a_modal_dialog_is_open(self):
        self.ready_mock();self.win.mode_tabs.setCurrentIndex(0);self.win.auto_refresh_checkbox.setChecked(True)
        with patch('ui.main_window.QApplication.activeModalWidget',return_value=object()),patch.object(self.win,'refresh_status') as refresh:
            self.win.maybe_refresh_status();refresh.assert_not_called()
    def test_group_apply_checks_stop_between_pumps(self):
        self.ready_mock()
        for panel in self.win.panels.values():panel.confirm_diameter(10);panel.set_active(True)
        original=self.win.controller.configure_program
        attempted=[];tickets=[]
        def configure(address,settings):
            attempted.append(address)
            result=original(address,settings)
            tickets.append(self.win.task_gate.begin_stop())
            return result
        try:
            with patch.object(self.win.controller,'configure_program',side_effect=configure):
                self.win.apply_active();self.wait_idle()
            self.assertEqual(attempted,[0])
        finally:
            for ticket in tickets:
                if ticket is not None:self.win.task_gate.end_stop(ticket)

    def test_fixed_editor_actions_complete_the_single_pump_workflow(self):
        self.ready_mock();self.win.mode_tabs.setCurrentIndex(0)
        panel=self.win.panels[1];self.win.select_pump(1)
        self.assertFalse(panel.editor_run_button.isEnabled())
        panel.set_diameter_button.click();self.wait_idle()
        self.assertIsNotNone(panel.confirmed_diameter)
        self.assertFalse(panel.diameter_fields.isVisible())
        self.assertFalse(panel.editor_run_button.isEnabled())
        self.assertIn('Apply and verify',panel.step_banner.source_text)
        panel.apply_button.click();self.wait_idle()
        self.assertTrue(panel.editor_run_button.isEnabled())
        self.assertIn('Start pump 2',panel.step_banner.source_text)
        self.assertFalse(panel.is_active())
        panel.editor_run_button.click();self.app.processEvents()
        self.assertEqual(self.win.workflow.step,4);self.assertFalse(panel.running)
        self.win.workflow.review_start.click();self.wait_idle()
        self.assertTrue(panel.running)
        self.assertFalse(panel.editor_run_button.isEnabled())
        self.assertFalse(self.win.panels[0].running)
        panel.editor_stop_button.click();self.wait_idle()
        self.assertFalse(panel.running);self.assertEqual(panel.last_status,'S')

    def test_group_resolve_identifies_the_blocking_pump_without_sending_commands(self):
        self.ready_mock();self.win.mode_tabs.setCurrentIndex(0)
        for address in (0,1):
            panel=self.win.panels[address];panel.confirm_diameter(10);panel.set_active(True)
        self.win.panels[1].mark_settings_applied();self.win.select_pump(1)
        self.assertIn('Pump 1 (address 00): Apply settings first',self.win.group_guide.source_text)
        self.assertFalse(self.win.run_active_button.isEnabled())
        with patch.object(self.win.controller,'send_command',wraps=self.win.controller.send_command) as commands:
            self.win.group_fix_button.click();self.app.processEvents()
            self.assertEqual(self.win.selected_address,0)
            self.assertTrue(self.win.panels[0].is_active());self.assertTrue(self.win.panels[1].is_active())
            commands.assert_not_called()

    def test_partial_numeric_input_blocks_both_start_paths_and_explains_the_field(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.ready_mock();self.win.mode_tabs.setCurrentIndex(0)
        panel=self.win.panels[0];panel.confirm_diameter(10);panel.mark_settings_applied();panel.set_active(True)
        panel.rate_input.setFocus();panel.rate_input.selectAll()
        QTest.keyClick(panel.rate_input,Qt.Key.Key_Backspace);self.app.processEvents()
        self.assertFalse(panel.rate_input.hasAcceptableInput())
        self.assertTrue(panel.validation_label.isVisible())
        self.assertIn('main flow rate',panel.validation_label.source_text)
        self.assertFalse(panel.editor_run_button.isEnabled());self.assertFalse(self.win.run_active_button.isEnabled())
        self.assertFalse(self.win.apply_active_button.isEnabled())
        QTest.keyClicks(panel.rate_input,'12.3');self.app.processEvents()
        self.win.apply_active();self.wait_idle()
        self.assertTrue(panel.settings_applied);self.assertEqual(panel.applied_snapshot.rate,12.3)

    def test_diameter_edit_explains_cleared_group_and_requires_verification(self):
        self.ready_mock();panel=self.win.panels[0]
        panel.confirm_diameter(10);panel.mark_settings_applied();panel.set_active(True)
        panel.open_diameter_editor();panel.diameter_input.setValue(12)
        self.assertFalse(panel.is_active());self.assertFalse(panel.editor_run_button.isEnabled())
        self.assertIn('Group selection cleared',panel.group_hint_label.source_text)
        panel.confirm_diameter(12)
        self.assertFalse(panel.settings_applied);self.assertFalse(panel.is_active())
        self.assertIn('Group selection cleared',panel.group_hint_label.source_text)
        panel.set_active(True);self.assertEqual(panel.group_hint_label.source_text,'')

    def test_status_age_is_information_and_does_not_reset_verified_settings(self):
        self.ready_mock();panel=self.win.panels[0]
        panel.confirm_diameter(10);panel.mark_settings_applied()
        panel.checked_at=time.monotonic()-20;panel.refresh_age()
        self.assertIn('s ago',panel.last_check_label.source_text)
        self.assertNotIn('needs refresh',panel.last_check_label.source_text)
        self.assertTrue(panel.settings_applied);self.assertTrue(panel.editor_run_button.isEnabled())

    def test_compact_group_reset_keeps_every_pump_stop_visible(self):
        self.ready_mock();self.win.mode_tabs.setCurrentIndex(0)
        self.win.ui_scale_combo.setCurrentIndex(self.win.ui_scale_combo.findData(1.3))
        self.win.resize(1024,768)
        for panel in self.win.panels.values():
            panel.confirm_diameter(10);panel.mark_settings_applied();panel.set_active(True)
            panel.open_diameter_editor();panel.diameter_input.setValue(12)
        for language in ('zh_TW','en'):
            manager.set_language(language)
            for _ in range(3):self.app.processEvents()
            viewport=self.win.panel_scroll.viewport()
            for address,panel in self.win.panels.items():
                pos=panel.stop_button.mapTo(viewport,QPoint(0,0))
                self.assertGreaterEqual(pos.y(),0)
                self.assertLessEqual(pos.y()+panel.stop_button.height(),viewport.height(),(language,address))
                self.assertFalse(panel.editor_run_button.isEnabled())
                self.assertIn('Group selection cleared',panel._source_tip)
