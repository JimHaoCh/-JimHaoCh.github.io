"""Exercise localized modal dialogs, rejection and JSON overwrite protection."""
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QMessageBox,QFileDialog
    from ui.fonts import configure_ui_font
    from ui.i18n import manager
    from ui.i18n_widgets import MessageBox,FileDialog
    HAVE_QT=True
except ImportError:HAVE_QT=False

@unittest.skipUnless(HAVE_QT,'PySide6 is not installed')
class BilingualDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);configure_ui_font(cls.app)
    def tearDown(self):
        manager.set_language('zh_TW')
    def timer(self,callback):
        timer=QTimer();timer.setInterval(10)
        attempts=[0]
        def tick():
            attempts[0]+=1
            dialog=self.app.activeModalWidget()
            if attempts[0]>200:
                timer.stop()
                if dialog is not None:dialog.reject()
                self.app.closeAllWindows();return
            if dialog is not None:
                try:
                    if callback(dialog):timer.stop()
                except Exception:
                    timer.stop();dialog.reject()
            elif attempts[0]>200:
                timer.stop();self.app.closeAllWindows()
        timer.timeout.connect(tick);timer.start()
        return timer
    def test_rejecting_save_question_is_cancel_in_both_languages(self):
        for language in ('zh_TW','en'):
            manager.set_language(language);observed=[]
            def reject(dialog):
                observed.append(isinstance(dialog,QMessageBox));dialog.reject();return True
            timer=self.timer(reject)
            result=MessageBox.question(None,'Unsaved workflow','Save the current workflow?',
                MessageBox.StandardButton.Save|MessageBox.StandardButton.Discard|MessageBox.StandardButton.Cancel,
                MessageBox.StandardButton.Save)
            timer.stop()
            self.assertTrue(observed);self.assertEqual(result,MessageBox.StandardButton.Cancel)
    def test_question_buttons_translate_and_return_the_clicked_choice(self):
        for language,yes in (('zh_TW','是'),('en','Yes')):
            manager.set_language(language);observed=[]
            def accept(dialog):
                button=dialog.button(QMessageBox.StandardButton.Yes)
                observed.append(button.text());button.click();return True
            timer=self.timer(accept)
            result=MessageBox.question(None,'Replace file','Replace the existing file?\nexample.json',
                MessageBox.StandardButton.Yes|MessageBox.StandardButton.No,MessageBox.StandardButton.No)
            timer.stop()
            self.assertEqual(observed,[yes]);self.assertEqual(result,MessageBox.StandardButton.Yes)
    def test_file_dialog_labels_and_cancel_translate(self):
        for language,label in (('zh_TW','檔案名稱：'),('en','File name:')):
            manager.set_language(language);observed=[]
            def reject(dialog):
                observed.append(dialog.labelText(QFileDialog.DialogLabel.FileName));dialog.reject();return True
            timer=self.timer(reject)
            chosen,_=FileDialog.getSaveFileName(None,'儲存流程','example.json','JSON (*.json)')
            timer.stop()
            self.assertEqual(chosen,'');self.assertEqual(observed,[label])
    def test_json_extension_and_rejected_overwrite_preserve_file(self):
        manager.set_language('zh_TW')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'existing.json';path.write_text('ORIGINAL',encoding='utf-8')
            seen=[]
            def interact(dialog):
                if isinstance(dialog,QFileDialog):
                    seen.append('file');dialog.selectFile(str(path.with_suffix('')));dialog.accept();return False
                if isinstance(dialog,QMessageBox):
                    seen.append('overwrite');dialog.reject();return True
                return False
            timer=self.timer(interact)
            chosen,_=FileDialog.getSaveFileName(None,'儲存流程',str(path.with_suffix('')),'JSON (*.json)')
            timer.stop()
            self.assertEqual(chosen,'');self.assertEqual(seen,['file','overwrite'])
            self.assertEqual(path.read_text(encoding='utf-8'),'ORIGINAL')
