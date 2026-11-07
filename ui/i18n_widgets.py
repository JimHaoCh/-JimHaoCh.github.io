"""Localized Qt views; updates retain the widgets, values and connections."""
from collections import deque
from pathlib import Path
from PySide6 import QtWidgets as W, QtGui as G
from PySide6.QtCore import Qt, QSignalBlocker
from .i18n import manager, tr

class Tooltip:
    def setToolTip(self, text):
        self._source_tip = str(text)
        super().setToolTip(tr(text))
    def _translate_tip(self):
        if hasattr(self, '_source_tip'):
            super().setToolTip(tr(self._source_tip))

class Label(Tooltip, W.QLabel):
    def __init__(self, text='', parent=None):
        super().__init__('', parent)
        self.source_text = str(text)
        manager.changed.connect(self.retranslate)
        self.retranslate()
    def setText(self, text):
        self.source_text = str(text)
        super().setText(tr(text))
    def retranslate(self):
        super().setText(tr(self.source_text))
        self._translate_tip()

class Button(Tooltip, W.QPushButton):
    def __init__(self, text='', parent=None):
        super().__init__('', parent)
        self.source_text = str(text)
        manager.changed.connect(self.retranslate)
        self.retranslate()
    def setText(self, text):
        self.source_text = str(text)
        super().setText(tr(text))
    def retranslate(self):
        super().setText(tr(self.source_text))
        self._translate_tip()

class CheckBox(Tooltip, W.QCheckBox):
    def __init__(self, text='', parent=None):
        super().__init__('', parent)
        self.source_text = str(text)
        manager.changed.connect(self.retranslate)
        self.retranslate()
    def setText(self, text):
        self.source_text = str(text)
        super().setText(tr(text))
    def retranslate(self):
        super().setText(tr(self.source_text))
        self._translate_tip()

class GroupBox(Tooltip, W.QGroupBox):
    def __init__(self, title='', parent=None):
        super().__init__('', parent)
        self.source_title = str(title)
        manager.changed.connect(self.retranslate)
        self.retranslate()
    def setTitle(self, text):
        self.source_title = str(text)
        super().setTitle(tr(text))
    def retranslate(self):
        super().setTitle(tr(self.source_title))
        self._translate_tip()

class ComboBox(Tooltip, W.QComboBox):
    SOURCE_ROLE = int(Qt.ItemDataRole.UserRole) + 100
    def __init__(self, parent=None):
        super().__init__(parent)
        manager.changed.connect(self.retranslate)
    def addItem(self, text, userData=None):
        super().addItem(tr(text), userData)
        self.setItemData(self.count()-1, str(text), self.SOURCE_ROLE)
    def addItems(self, texts):
        for text in texts: self.addItem(text)
    def setItemText(self, index, text):
        self.setItemData(index, str(text), self.SOURCE_ROLE)
        super().setItemText(index, tr(text))
    def retranslate(self):
        blocker=QSignalBlocker(self)
        for index in range(self.count()):
            source=self.itemData(index,self.SOURCE_ROLE)
            if source is not None: super().setItemText(index,tr(source))
        del blocker
        self._translate_tip()
    def wheelEvent(self, event):
        event.ignore()

class SpinBox(Tooltip, W.QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setKeyboardTracking(False)
        manager.changed.connect(self._translate_tip)
    def wheelEvent(self, event):
        event.ignore()

class LogView(W.QPlainTextEdit):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.sources=deque(maxlen=3000)
        self.placeholder_source=''
        manager.changed.connect(self.retranslate)
    def setPlaceholderText(self,text):
        self.placeholder_source=str(text)
        super().setPlaceholderText(tr(text))
    def appendPlainText(self,text):
        self.sources.append(str(text))
        super().appendPlainText(self._translate_line(str(text)))
    @staticmethod
    def _translate_line(line):
        if line.startswith('[') and '] ' in line:
            stamp, message=line.split('] ',1)
            return stamp+'] '+(message if message.startswith('TX ') else tr(message))
        return tr(line)
    def retranslate(self):
        bar=self.verticalScrollBar()
        was_bottom=bar.value()>=bar.maximum()
        previous=bar.value()
        super().setPlainText('\n'.join(self._translate_line(line) for line in self.sources))
        super().setPlaceholderText(tr(self.placeholder_source))
        bar.setValue(bar.maximum() if was_bottom else previous)

class Painter(G.QPainter):
    def drawText(self,*args):
        if args and isinstance(args[-1],str): args=(*args[:-1],tr(args[-1]))
        return super().drawText(*args)

class Menu(W.QMenu):
    def addAction(self,*args):
        if args and isinstance(args[0],str): args=(tr(args[0]),*args[1:])
        return super().addAction(*args)

class NonModalNotice(W.QMessageBox):
    def __init__(self, parent, title, text):
        super().__init__(parent)
        self.source_title, self.source_text = title, text
        self.setIcon(W.QMessageBox.Icon.Warning)
        self.setStandardButtons(W.QMessageBox.StandardButton.Ok)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        manager.changed.connect(self.retranslate)
        self.retranslate()

    def retranslate(self):
        self.setWindowTitle(tr(self.source_title))
        self.setText(tr(self.source_text))
        self.button(W.QMessageBox.StandardButton.Ok).setText(tr('OK'))


class MessageBox:
    StandardButton=W.QMessageBox.StandardButton
    Icon=W.QMessageBox.Icon
    @staticmethod
    def _show(parent,title,text,buttons,default,icon):
        dialog=W.QMessageBox(parent)
        dialog.setWindowTitle(tr(title))
        dialog.setText(tr(text))
        dialog.setIcon(icon)
        dialog.setStandardButtons(buttons)
        if default is not None: dialog.setDefaultButton(default)
        names=('Save','Discard','Cancel','Yes','No','Ok','Close','Retry')
        for name in names:
            flag=getattr(W.QMessageBox.StandardButton,name)
            button=dialog.button(flag)
            if button: button.setText(tr('OK' if name=='Ok' else name))
        dialog.exec()
        clicked=dialog.clickedButton()
        if clicked is not None:return dialog.standardButton(clicked)
        for flag in (W.QMessageBox.StandardButton.Cancel,W.QMessageBox.StandardButton.No,W.QMessageBox.StandardButton.Close,W.QMessageBox.StandardButton.Ok):
            if buttons & flag:return flag
        return W.QMessageBox.StandardButton.NoButton
    @staticmethod
    def question(parent,title,text,buttons=None,default=None):
        buttons=buttons if buttons is not None else W.QMessageBox.StandardButton.Yes|W.QMessageBox.StandardButton.No
        return MessageBox._show(parent,title,text,buttons,default,W.QMessageBox.Icon.Question)
    @staticmethod
    def warning(parent,title,text,buttons=None,default=None):
        if parent is not None and hasattr(parent, 'show_nonmodal_warning') and buttons is None:
            parent.show_nonmodal_warning(title, text)
            return W.QMessageBox.StandardButton.Ok
        return MessageBox._show(parent,title,text,buttons or W.QMessageBox.StandardButton.Ok,default,W.QMessageBox.Icon.Warning)
    @staticmethod
    def information(parent,title,text,buttons=None,default=None):
        return MessageBox._show(parent,title,text,buttons or W.QMessageBox.StandardButton.Ok,default,W.QMessageBox.Icon.Information)

class FileDialog:
    @staticmethod
    def _get(parent,title,path,filter,save):
        dialog=W.QFileDialog(parent,tr(title))
        dialog.setOption(W.QFileDialog.Option.DontUseNativeDialog,True)
        dialog.setOption(W.QFileDialog.Option.DontConfirmOverwrite,True)
        dialog.setAcceptMode(W.QFileDialog.AcceptMode.AcceptSave if save else W.QFileDialog.AcceptMode.AcceptOpen)
        dialog.setFileMode(W.QFileDialog.FileMode.AnyFile if save else W.QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilter(filter)
        if 'json' in filter.lower(): dialog.setDefaultSuffix('json')
        if path: dialog.selectFile(path)
        for field,label in ((W.QFileDialog.DialogLabel.LookIn,'Look in:'),(W.QFileDialog.DialogLabel.FileName,'File name:'),
                            (W.QFileDialog.DialogLabel.FileType,'Files of type:'),(W.QFileDialog.DialogLabel.Accept,'Save' if save else 'Open'),
                            (W.QFileDialog.DialogLabel.Reject,'Cancel')):
            dialog.setLabelText(field,tr(label))
        if dialog.exec()!=W.QDialog.DialogCode.Accepted or not dialog.selectedFiles(): return '', ''
        chosen=dialog.selectedFiles()[0]
        if save and Path(chosen).exists():
            choice=MessageBox.question(parent,'Replace file','Replace the existing file?\n'+chosen,
                                       MessageBox.StandardButton.Yes|MessageBox.StandardButton.No,MessageBox.StandardButton.No)
            if choice!=MessageBox.StandardButton.Yes: return '', ''
        return chosen,dialog.selectedNameFilter()
    @staticmethod
    def getSaveFileName(parent,title,path='',filter=''):
        return FileDialog._get(parent,title,path,filter,True)
    @staticmethod
    def getOpenFileName(parent,title,path='',filter=''):
        return FileDialog._get(parent,title,path,filter,False)
