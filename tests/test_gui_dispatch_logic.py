"""Dispatch regression checks with real Qt views and a deterministic worker queue."""
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings
    from ui.main_window import MainWindow
    from ui.fonts import configure_ui_font
    HAVE_QT=True
except ImportError:HAVE_QT=False
from ne501.protocol import parse_response

class Signal:
    def __init__(self):self.callbacks=[]
    def connect(self,callback,*_):self.callbacks.append(callback)
    def emit(self,*args):
        for callback in self.callbacks:callback(*args)
class FakeWorker:
    def __init__(self,function):
        self.function=function;self.signals=types.SimpleNamespace(result=Signal(),error=Signal(),finished=Signal())
    def run(self):
        try:result=self.function()
        except Exception as exc:self.signals.error.emit(str(exc))
        else:self.signals.result.emit(result)
        finally:self.signals.finished.emit()
class FakeCallbacks:
    def __init__(self,_parent,on_result,on_error,on_finished):
        self.receive_result,self.receive_error,self.receive_finished=on_result,on_error,on_finished
class FakePool:
    def __init__(self):self.queue=[]
    def start(self,worker,priority):self.queue.append((priority,worker))
    def run_next(self):
        self.queue.sort(key=lambda item:item[0],reverse=True);self.queue.pop(0)[1].run()
class Controller:
    is_connected=True
    def stop_pump(self,address):
        return [(address,'STATUS',parse_response(f'\x02{address:02d}S\x03'.encode(),address))]

@unittest.skipUnless(HAVE_QT,'PySide6 is not installed')
class DispatchIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);configure_ui_font(cls.app)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.win=MainWindow({'addresses':[0,1,2,3]},settings=QSettings(str(Path(self.temp.name)/'settings.ini'),QSettings.Format.IniFormat))
        self.win.controller=Controller();self.win.thread_pool=FakePool()
        self.actions=[]
        self.win.process_results=lambda results:self.actions.append(('stop',len(results)))
    def tearDown(self):
        self.win.controller=None;self.win.close();self.temp.cleanup()
    def test_stop_prevents_queued_run_and_waits_for_pending_panels(self):
        with patch('ui.main_window.FunctionWorker',FakeWorker),patch('ui.main_window.WorkerCallbacks',FakeCallbacks):
            self.win.run_task(lambda:self.actions.append('old run'),panels=[self.win.panels[0]])
            self.win.emergency_stop()
            self.win.run_task(lambda:self.actions.append('new run'))
            self.assertEqual(len(self.win.thread_pool.queue),2)
            self.win.thread_pool.run_next()
            self.assertTrue(self.win.panels[0].busy)
            self.win.thread_pool.run_next()
            self.assertEqual(self.actions,[('stop',4)])
            self.assertFalse(self.win.panels[0].busy);self.assertEqual(self.win.pending_tasks,0)
            self.assertFalse(self.win._active_callbacks)
    def test_single_stop_cancels_old_run_for_that_pump(self):
        with patch('ui.main_window.FunctionWorker',FakeWorker),patch('ui.main_window.WorkerCallbacks',FakeCallbacks):
            self.win.run_task(lambda:self.actions.append('old run'),panels=[self.win.panels[0]])
            self.win.stop_single(0)
            self.win.thread_pool.run_next();self.win.thread_pool.run_next()
            self.assertEqual(self.actions,[('stop',1)])
            self.assertEqual(self.win.pending_tasks,0)
    def test_single_stop_does_not_cancel_unrelated_pump_operation(self):
        with patch('ui.main_window.FunctionWorker',FakeWorker),patch('ui.main_window.WorkerCallbacks',FakeCallbacks):
            self.win.run_task(lambda:self.actions.append('pump 1 run'),panels=[self.win.panels[1]])
            self.win.stop_single(0)
            self.win.thread_pool.run_next();self.win.thread_pool.run_next()
            self.assertEqual(self.actions,[('stop',1),'pump 1 run'])
