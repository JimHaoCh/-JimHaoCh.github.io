"""Exercise dispatch wiring with Qt stand-ins; real Qt startup is a build smoke test."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch

from ne501.protocol import parse_response
from ne501.task_gate import TaskGate


class Signal:
    def __init__(self): self.callbacks = []
    def connect(self, callback, *_args): self.callbacks.append(callback)
    def emit(self, *args):
        for callback in self.callbacks: callback(*args)


class FakeWorker:
    def __init__(self, function):
        self.function = function
        self.signals = types.SimpleNamespace(result=Signal(), error=Signal(), finished=Signal())
    def run(self):
        try:
            result = self.function()
        except Exception as exc:
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class FakeCallbacks:
    def __init__(self, _parent, on_result, on_error, on_finished):
        self.receive_result, self.receive_error, self.receive_finished = on_result, on_error, on_finished


class FakePool:
    def __init__(self): self.queue = []
    def start(self, worker, priority): self.queue.append((priority, worker))
    def run_next(self):
        self.queue.sort(key=lambda item: item[0], reverse=True)
        self.queue.pop(0)[1].run()


class FakeLabel:
    def setText(self, text): self.text = text


class FakePanel:
    def __init__(self, address):
        self.address = address
        self.busy = False
        self.status_label, self.version_label = FakeLabel(), FakeLabel()
        self.last_response = ""
    def set_busy(self, busy): self.busy = busy
    def set_online(self, online): self.online = online
    def set_last_response(self, text): self.last_response = text


class FakeMessageBox:
    warnings = []
    @classmethod
    def warning(cls, _parent, title, text): cls.warnings.append((title, text))


def fake_qt_modules():
    dummy = type("Dummy", (), {})
    core = types.ModuleType("PySide6.QtCore")
    core.QSettings = core.QThreadPool = dummy
    core.Qt = types.SimpleNamespace(ConnectionType=types.SimpleNamespace(QueuedConnection=1))
    gui = types.ModuleType("PySide6.QtGui")
    gui.QCloseEvent = dummy
    widgets = types.ModuleType("PySide6.QtWidgets")
    for name in ("QApplication QComboBox QGridLayout QHBoxLayout QLabel QMainWindow "
                 "QMessageBox QPushButton QPlainTextEdit QScrollArea QSplitter QVBoxLayout QWidget").split():
        setattr(widgets, name, FakeMessageBox if name == "QMessageBox" else dummy)
    pyside = types.ModuleType("PySide6")
    pyside.QtCore, pyside.QtGui, pyside.QtWidgets = core, gui, widgets
    panel = types.ModuleType("ui.pump_panel")
    panel.PumpPanel, panel.PumpSettings = FakePanel, dummy
    style = types.ModuleType("ui.style")
    style.build_stylesheet = lambda *_: ""
    workers = types.ModuleType("ui.workers")
    workers.FunctionWorker, workers.WorkerCallbacks = FakeWorker, FakeCallbacks
    return {"PySide6": pyside, "PySide6.QtCore": core, "PySide6.QtGui": gui,
            "PySide6.QtWidgets": widgets, "ui.pump_panel": panel,
            "ui.style": style, "ui.workers": workers}


class DispatchIntegrationTests(unittest.TestCase):
    def test_stop_prevents_queued_run_and_waits_for_pending_panels(self):
        class Controller:
            is_connected = True
            def stop_pump(self, address):
                response = parse_response(f"\x02{address:02d}S\x03".encode(), address)
                return [(address, "STATUS", response)]

        sys.modules.pop("ui.main_window", None)
        with patch.dict(sys.modules, fake_qt_modules()):
            module = importlib.import_module("ui.main_window")
            win = module.MainWindow.__new__(module.MainWindow)
            win.controller = Controller()
            win.addresses = [0, 1, 2, 3]
            win.panels = {address: FakePanel(address) for address in win.addresses}
            win.thread_pool, win.task_gate = FakePool(), TaskGate()
            win._panel_pending, win.pending_tasks = {}, 0
            win._active_workers, win._active_callbacks = set(), set()
            messages, actions = [], []
            win.append_log = messages.append
            win.process_results = lambda results: actions.append(("stop", len(results)))
            win.run_task(lambda: actions.append("old run"), panels=[win.panels[0]])
            win.emergency_stop()
            win.run_task(lambda: actions.append("new run"))
            self.assertEqual(len(win.thread_pool.queue), 2)
            win.thread_pool.run_next()  # Higher-priority STOP first.
            self.assertTrue(win.panels[0].busy)  # Old queued command has not been drained yet.
            win.thread_pool.run_next()
            self.assertEqual(actions, [("stop", 4)])
            self.assertFalse(win.panels[0].busy)
            self.assertEqual(win.pending_tasks, 0)
            self.assertEqual(len(win._active_callbacks), 0)
        sys.modules.pop("ui.main_window", None)


if __name__ == "__main__":
    unittest.main()
