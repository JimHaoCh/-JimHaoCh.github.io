from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class WorkerCallbacks(QObject):
    """Receive worker events on the GUI thread before calling UI callbacks."""
    def __init__(self, parent, on_result, on_error, on_finished) -> None:
        super().__init__(parent)
        self._on_result = on_result
        self._on_error = on_error
        self._on_finished = on_finished

    @Slot(object)
    def receive_result(self, result: Any) -> None:
        self._on_result(result)

    @Slot(str)
    def receive_error(self, message: str) -> None:
        self._on_error(message)

    @Slot()
    def receive_finished(self) -> None:
        try:
            self._on_finished()
        finally:
            self.deleteLater()


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:  # UI boundary: show a readable message.
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()
