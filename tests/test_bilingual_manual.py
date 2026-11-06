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
        self.win._set_group_buttons_enabled(True)
        for panel in self.win.panels.values():panel.set_online(True);panel.update_from_status('S')
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
        for language in ('zh_TW','en'):
            manager.set_language(language)
            for scale in (1.,1.3):
                self.win.ui_scale_combo.setCurrentIndex(self.win.ui_scale_combo.findData(scale))
                self.app.setStyleSheet(build_stylesheet(scale))
                for width,height in ((1280,850),(1024,768)):
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
        self.assertFalse(problems,problems)
