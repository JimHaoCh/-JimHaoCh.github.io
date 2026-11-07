"""Regression tests for real Qt events, editing state and project data loss."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QSettings
    from PySide6.QtGui import QMouseEvent, QWheelEvent, QRawFont
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ui.timeline_editor import TimelineEditor
    from ne501.timeline_model import Clip, Timeline, example_timeline
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class TimelineDesktopUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from ui.fonts import configure_ui_font
        configure_ui_font(cls.app)

    def setUp(self):
        self.ui = TimelineEditor([5, 7, 8, 9])
        self.ui.resize(1280, 760)
        self.ui.show()
        self.app.processEvents()

    def tearDown(self):
        self.ui.stop_preview()
        self.ui.close()
        self.app.processEvents()

    def mouse(self, kind, x, y, held, mods=Qt.KeyboardModifier.NoModifier):
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        buttons = Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton
        event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons, mods)
        self.app.sendEvent(self.ui.canvas, event)

    def press(self, x, y): self.mouse(QEvent.Type.MouseButtonPress, x, y, True)
    def move(self, x, y, mods=Qt.KeyboardModifier.NoModifier): self.mouse(QEvent.Type.MouseMove, x, y, True, mods)
    def release(self, x, y): self.mouse(QEvent.Type.MouseButtonRelease, x, y, False)

    def test_editor_renders_and_drags_clip_and_edge(self):
        c = self.ui.canvas
        self.assertFalse(c.grab().isNull())
        original = self.ui.model.get('a')
        rect = c.clip_rect(original)
        x, y = rect.center().x(), rect.center().y()
        self.press(x, y); self.move(x+30, y)
        self.assertEqual(self.ui.model.get('a'), original)  # Preview, before release.
        self.release(x+30, y)
        moved = self.ui.model.get('a')
        self.assertGreater(moved.start, original.start)
        self.assertEqual(moved.end-moved.start, original.end-original.start)
        self.assertFalse(self.ui.checked)
        self.ui.undo(); self.assertEqual(self.ui.model.get('a'), original)
        self.ui.redo(); self.assertEqual(self.ui.model.get('a'), moved)
        self.ui.undo()
        rect = c.clip_rect(original); x, y = rect.right()-2, rect.center().y()
        self.press(x, y); self.move(x+30, y); self.release(x+30, y)
        self.assertGreater(self.ui.model.get('a').end, original.end)

    def test_preflight_dirty_pause_seek_and_stop(self):
        self.assertEqual(self.ui.speed_combo.currentData(), 1)
        self.assertFalse(self.ui.play_button.isEnabled())
        self.ui.check_flow(); self.assertTrue(self.ui.play_button.isEnabled())
        self.ui.rate_spin.setValue(12.3)
        self.assertTrue(self.ui.dirty); self.assertFalse(self.ui.play_button.isEnabled())
        self.ui.apply_clip(); self.assertFalse(self.ui.checked)
        self.assertEqual(self.ui.model.get('a').rate, 12.3)
        self.ui.check_flow(); self.ui.start_preview()
        self.assertTrue(self.ui.running); self.assertFalse(self.ui.canvas.editable)
        self.ui.started_at -= 1
        self.ui.pause_preview(); self.assertTrue(self.ui.paused)
        self.assertGreater(self.ui.playhead, 9)
        self.ui.seek(200); self.assertEqual(self.ui.playhead, 200)
        self.assertFalse(self.ui.add_button.isEnabled())
        self.ui.start_preview(); self.assertTrue(self.ui.running)
        self.ui.stop_preview()
        self.assertFalse(self.ui.busy()); self.assertGreaterEqual(self.ui.playhead, 200)
        self.ui.return_to_start(); self.assertEqual(self.ui.playhead, 0)

    def test_exact_gap_add_and_nearest_selection_after_delete(self):
        self.assertEqual(self.ui.model.addresses, [5, 7, 8, 9])
        n = len(self.ui.model.clips)
        self.ui.add_clip_at(0, 540)
        added = self.ui.model.get(self.ui.canvas.selected)
        self.assertEqual((added.start, added.end), (540, 550))
        self.ui.delete_clip(); self.assertEqual(len(self.ui.model.clips), n)
        self.assertEqual(self.ui.canvas.selected, 'b')
        self.ui.undo(); self.assertEqual(len(self.ui.model.clips), n+1)
        self.ui.redo(); self.assertEqual(len(self.ui.model.clips), n)

    def test_add_button_uses_playhead_and_reveals_actual_gap(self):
        self.ui.seek(800); self.ui.add_clip()
        clip = self.ui.model.get(self.ui.canvas.selected)
        self.assertEqual((clip.start, clip.end), (800, 950))
        self.assertIn('01:20.0', self.ui.notice_label.text())

    def test_escape_discards_drag_without_creating_undo(self):
        c = self.ui.canvas; old = self.ui.model.to_json(); r = c.clip_rect(self.ui.model.get('a'))
        x, y = r.center().x(), r.center().y()
        self.press(x, y); self.move(x+40, y)
        self.assertIsNotNone(c.drag)
        QTest.keyClick(c, Qt.Key.Key_Escape)
        self.release(x+40, y)
        self.assertIsNone(c.drag); self.assertEqual(self.ui.model.to_json(), old)
        self.assertEqual(self.ui.history, [])

    def test_resize_clamps_at_adjacent_block(self):
        c = self.ui.canvas; r = c.clip_rect(self.ui.model.get('a'))
        x, y = r.right()-2, r.center().y()
        self.press(x, y); self.move(c.tick_to_x(900), y); self.release(c.tick_to_x(900), y)
        self.assertEqual(self.ui.model.get('a').end, 550)
        self.assertEqual(self.ui.model.get('b').start, 550)
        self.ui.model.validate()

    def test_cross_track_collision_is_cancelled_and_empty_track_allowed(self):
        c = self.ui.canvas; old = self.ui.model.get('a'); r = c.clip_rect(old)
        x, y = r.center().x(), r.center().y()
        target = c.clip_rect(self.ui.model.get('c')).center().y()
        self.press(x, y); self.move(x, target)
        self.assertFalse(c.drag['valid'])
        self.release(x, target)
        self.assertEqual(self.ui.model.get('a'), old); self.assertFalse(self.ui.history)
        target = c.clip_rect(self.ui.model.get('f')).center().y()
        self.press(x, y); self.move(x, target); self.release(x, target)
        self.assertEqual(self.ui.model.get('a').pump, 3)
        self.assertEqual(self.ui.pump_combo.currentData(), 3)

    def test_move_can_cross_existing_blocks_to_a_later_free_gap(self):
        c=self.ui.canvas;r=c.clip_rect(self.ui.model.get('a'));x,y=r.center().x(),r.center().y()
        self.press(x,y);self.move(c.tick_to_x(1000),y);self.release(c.tick_to_x(1000),y)
        self.assertEqual((self.ui.model.get('a').start,self.ui.model.get('a').end),(850,1150))
        self.ui.model.validate()

    def test_snap_to_other_track_and_alt_bypass(self):
        model = Timeline(1000, [Clip('a', 0, 0, 100, 'INF', 10, 'µL/min'), Clip('b', 1, 300, 400, 'INF', 10, 'µL/min')], [5,7,8,9])
        self.ui._load_model(model)
        c = self.ui.canvas; r = c.clip_rect(model.get('a')); x,y=r.center().x(),r.center().y()
        self.press(x,y); self.move(c.tick_to_x(345),y); self.release(c.tick_to_x(345),y)
        self.assertEqual(self.ui.model.get('a').start,300)
        self.ui.undo(); r=c.clip_rect(self.ui.model.get('a'));x,y=r.center().x(),r.center().y()
        self.press(x,y); self.move(c.tick_to_x(345),y,Qt.KeyboardModifier.AltModifier);self.release(c.tick_to_x(345),y)
        self.assertEqual(self.ui.model.get('a').start,295)

    def test_short_block_can_move_and_focus_without_giant_widget(self):
        model = Timeline(1200,[Clip('tiny',0,100,101,'INF',1,'µL/min')],[5,7,8,9])
        self.ui._load_model(model)
        c=self.ui.canvas; width=c.width();r=c.clip_rect(model.get('tiny'))
        self.press(r.center().x(),r.center().y())
        self.assertEqual(c.drag['kind'],'move');c.cancel_drag()
        self.ui.focus_clip()
        self.assertGreater(c.clip_rect(model.get('tiny')).width(),20)
        self.assertEqual(c.width(),width)
        self.assertEqual(c.visible_ticks,5)
        self.ui._load_model(Timeline(6048000,[Clip('tiny',0,100,101,'INF',1,'µL/min')],[5,7,8,9]))
        self.ui.focus_clip();self.assertEqual(c.visible_ticks,5);self.assertEqual(c.width(),width)
        self.assertEqual(self.ui.hscroll.maximum(),6047995)

    def test_zoom_keeps_time_under_pointer_and_scroll_header_fixed(self):
        c=self.ui.canvas;x=c.LEFT+c.track_width()*.5; tick=c.x_to_tick(x)
        self.ui.zoom_at(2,x)
        self.assertLessEqual(abs(c.x_to_tick(x)-tick),1)
        self.ui.hscroll.setValue(self.ui.hscroll.maximum())
        self.assertEqual(c.view_start,600)
        self.assertEqual(c.tick_to_x(c.view_start),c.LEFT)
        self.ui.fit_view();self.assertEqual(c.view_start,0);self.assertEqual(c.visible_ticks,1200)

    def test_keyboard_seek_nudge_split_and_volume_preservation(self):
        c=self.ui.canvas;c.setFocus()
        QTest.keyClick(c,Qt.Key.Key_Right)
        self.assertEqual(self.ui.playhead,1)
        QTest.keyClick(c,Qt.Key.Key_Right,Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.ui.playhead,11)
        QTest.keyClick(c,Qt.Key.Key_Right,Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.ui.model.get('a').start,1)
        before=self.ui.model.get('a').volume_ul
        self.ui.seek(100);QTest.keyClick(c,Qt.Key.Key_B,Qt.KeyboardModifier.ControlModifier)
        pieces=[b for b in self.ui.model.clips if b.pump==0 and b.start<301]
        self.assertEqual(len(pieces),2)
        self.assertAlmostEqual(sum(b.volume_ul for b in pieces),before)
        self.ui.undo();self.assertEqual(self.ui.model.get('a').end,301)
        self.ui.redo();self.assertEqual(len(self.ui.model.clips),7)

    def test_clock_floors_instead_of_anticipating_next_boundary(self):
        self.ui.playhead=99.9;self.ui.update_transport()
        self.assertEqual(self.ui.position_spin.value(),9.9)

    def test_typed_setting_blocks_playback_and_enter_applies(self):
        spin=self.ui.rate_spin;spin.setFocus();spin.selectAll()
        QTest.keyClicks(spin,'12.3')
        self.assertTrue(self.ui.dirty)
        self.ui.check_flow();self.assertFalse(self.ui.checked)
        QTest.keyClick(spin,Qt.Key.Key_Return)
        self.assertFalse(self.ui.dirty);self.assertEqual(self.ui.model.get('a').rate,12.3)

    def test_wheel_over_setting_does_not_change_rate_even_with_focus(self):
        spin=self.ui.rate_spin;spin.setFocus();before=spin.value()
        event=QWheelEvent(QPointF(10,10),QPointF(10,10),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        self.app.sendEvent(spin,event)
        self.assertEqual(spin.value(),before)

    def test_wheel_does_not_change_direction_unit_or_track(self):
        for combo in (self.ui.direction_combo,self.ui.unit_combo,self.ui.pump_combo,self.ui.speed_combo):
            combo.setFocus();before=combo.currentIndex()
            event=QWheelEvent(QPointF(10,10),QPointF(10,10),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
            self.app.sendEvent(combo,event)
            self.assertEqual(combo.currentIndex(),before)

    def test_panned_withdraw_block_does_not_paint_over_fixed_header(self):
        self.ui._load_model(Timeline(1200,[Clip('w',0,0,1200,'WDR',1,'µL/min')],[5,7,8,9]))
        c=self.ui.canvas;c.set_view(600,300)
        image=c.grab().toImage()
        for y in range(c.TOP+10,c.TOP+25):
            self.assertEqual(image.pixelColor(c.LEFT-4,y).name(),'#26313e')

    def test_save_modified_marker_close_cancel_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'flow.json'
            with patch('ui.timeline_editor.QFileDialog.getSaveFileName',return_value=(str(path),'')):
                self.assertTrue(self.ui.save_file())
            original=path.read_bytes()
            self.assertFalse(self.ui.modified())
            self.ui.rate_spin.setValue(11);self.ui.apply_clip()
            self.assertTrue(self.ui.modified());self.assertTrue(self.ui.file_label.text().startswith('●'))
            with patch('ui.timeline_editor.QMessageBox.question',return_value=QMessageBox.StandardButton.Cancel):
                self.assertFalse(self.ui.prepare_to_leave())
            self.assertEqual(path.read_bytes(),original)
            with patch('ui.timeline_editor.QSaveFile') as output,patch('ui.timeline_editor.QMessageBox.warning'):
                output.return_value.open.return_value=False
                self.assertFalse(self.ui.save_file())
            self.assertEqual(path.read_bytes(),original)
            self.assertTrue(self.ui.modified())
            self.assertTrue(self.ui.save_file());self.assertFalse(self.ui.modified())
            self.assertNotEqual(path.read_bytes(),original)

    def test_open_cancel_or_invalid_file_preserves_current_project(self):
        self.ui.rate_spin.setValue(11);self.ui.apply_clip();old=self.ui.model.to_json()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'other.json';path.write_text(example_timeline([5,7,8,9]).to_json(),encoding='utf-8')
            with patch('ui.timeline_editor.QFileDialog.getOpenFileName',return_value=(str(path),'')),patch('ui.timeline_editor.QMessageBox.question',return_value=QMessageBox.StandardButton.Cancel):
                self.ui.open_file()
            self.assertEqual(self.ui.model.to_json(),old)
            path.write_text('{invalid',encoding='utf-8')
            with patch('ui.timeline_editor.QFileDialog.getOpenFileName',return_value=(str(path),'')),patch('ui.timeline_editor.QMessageBox.warning') as warning:
                self.ui.open_file();warning.assert_called_once()
            self.assertEqual(self.ui.model.to_json(),old)

    def test_native_window_small_screen_and_scale_and_tab_pause(self):
        from ui.main_window import MainWindow
        from ui.style import build_stylesheet
        previous=self.app.styleSheet()
        settings_dir=tempfile.TemporaryDirectory()
        isolated_settings=QSettings(str(Path(settings_dir.name)/'settings.ini'),QSettings.Format.IniFormat)
        window=MainWindow({'addresses':[0,1,2,3],'port':'MOCK'},settings=isolated_settings)
        window.load_example_workflow()
        try:
            for scale in (1,1.3):
                self.app.setStyleSheet(build_stylesheet(scale))
                window.ui_scale_combo.setCurrentIndex(window.ui_scale_combo.findData(scale))
                window.resize(1024,768);window.show();self.app.processEvents()
                self.assertLessEqual(window.width(),1024)
                self.assertLessEqual(window.height(),768)
                self.assertGreater(window.timeline_page.viewport().height(),300)
            timeline=window.timeline_editor;timeline.check_flow();timeline.start_preview();timeline.started_at-=1
            window.mode_tabs.setCurrentIndex(0)
            self.assertTrue(timeline.paused);self.assertGreater(timeline.playhead,9)
            window.mode_tabs.setCurrentIndex(1);self.assertTrue(timeline.paused)
            timeline.stop_preview();timeline.rate_spin.setValue(11);timeline.apply_clip()
            with patch('ui.timeline_editor.QMessageBox.question',return_value=QMessageBox.StandardButton.Cancel):
                self.assertFalse(window.close())
            self.assertTrue(window.isVisible())
            timeline.saved_snapshot=timeline.model.to_json()
        finally:
            window.timeline_editor.stop_preview();window.close();self.app.setStyleSheet(previous);settings_dir.cleanup()

    def test_bundled_font_contains_interface_letters_units_and_chinese(self):
        raw=QRawFont.fromFont(self.app.font())
        self.assertTrue(raw.isValid())
        for char in 'NE5010123456789幫浦推注抽取方向流速設定復原重做µL/min→←▶◀Ⅱ■':
            self.assertTrue(raw.supportsCharacter(ord(char)),repr(char))


if __name__=='__main__':unittest.main()
