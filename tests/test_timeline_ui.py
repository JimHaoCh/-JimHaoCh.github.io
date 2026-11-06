"""GUI interaction checks. They use Qt offscreen and never access hardware."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from ui.timeline_editor import TimelineEditor
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class TimelineDesktopUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ui = TimelineEditor([5, 7, 8, 9])
        self.ui.resize(1500, 800)
        self.ui.show()
        self.app.processEvents()

    def tearDown(self):
        self.ui.stop_preview()
        self.ui.close()
        self.app.processEvents()

    @staticmethod
    def mouse(kind, x, y, held):
        button = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
        buttons = Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton
        return QMouseEvent(kind, QPointF(x, y), button, buttons, Qt.KeyboardModifier.NoModifier)

    def test_editor_renders_and_drags_clip_and_edge(self):
        c = self.ui.canvas
        pixmap = c.grab()  # Runs real paintEvent under Qt offscreen.
        self.assertFalse(pixmap.isNull())
        original = self.ui.model.get('a')
        rect = c.clip_rect(original)
        x, y = rect.center().x(), rect.center().y()
        c.mousePressEvent(self.mouse(QEvent.Type.MouseButtonPress, x, y, True))
        c.mouseMoveEvent(self.mouse(QEvent.Type.MouseMove, x + 30, y, True))
        c.mouseReleaseEvent(self.mouse(QEvent.Type.MouseButtonRelease, x + 30, y, False))
        moved = self.ui.model.get('a')
        self.assertGreater(moved.start, original.start)
        self.assertEqual(moved.end - moved.start, original.end - original.start)
        self.assertFalse(self.ui.checked)
        self.ui.undo()
        self.assertEqual(self.ui.model.get('a'), original)
        rect = c.clip_rect(original)
        x, y = rect.right() - 2, rect.center().y()
        c.mousePressEvent(self.mouse(QEvent.Type.MouseButtonPress, x, y, True))
        c.mouseMoveEvent(self.mouse(QEvent.Type.MouseMove, x + 30, y, True))
        c.mouseReleaseEvent(self.mouse(QEvent.Type.MouseButtonRelease, x + 30, y, False))
        self.assertGreater(self.ui.model.get('a').end, original.end)

    def test_preflight_dirty_pause_and_stop(self):
        self.assertFalse(self.ui.play_button.isEnabled())
        self.ui.check_flow()
        self.assertTrue(self.ui.play_button.isEnabled())
        self.ui.rate_spin.setValue(12.3)
        self.assertTrue(self.ui.dirty)
        self.assertFalse(self.ui.play_button.isEnabled())
        self.ui.apply_clip()
        self.assertFalse(self.ui.checked)
        self.assertEqual(self.ui.model.get('a').rate, 12.3)
        self.ui.check_flow()
        self.ui.start_preview()
        self.assertTrue(self.ui.running)
        self.assertFalse(self.ui.canvas.editable)
        self.assertTrue(self.ui.stop_button.isEnabled())
        self.ui.pause_preview()
        self.assertTrue(self.ui.paused)
        self.assertFalse(self.ui.add_button.isEnabled())
        self.ui.start_preview()
        self.assertTrue(self.ui.running)
        self.ui.stop_preview()
        self.assertFalse(self.ui.busy())
        self.assertEqual(self.ui.playhead, 0)

    def test_add_duplicate_delete_and_address_mapping(self):
        self.assertEqual(self.ui.model.addresses, [5, 7, 8, 9])
        n = len(self.ui.model.clips)
        self.ui.add_clip_at(0, 300)
        self.assertEqual(len(self.ui.model.clips), n + 1)
        self.ui.delete_clip()
        self.assertEqual(len(self.ui.model.clips), n)
        self.ui.undo()
        self.assertEqual(len(self.ui.model.clips), n + 1)


if __name__ == '__main__': unittest.main()
