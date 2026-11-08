from __future__ import annotations

import csv
from datetime import datetime
import os
from pathlib import Path
from typing import Optional
from uuid import uuid4

from .protocol import PumpResponse


def user_data_directory(*, create: bool = True) -> Path:
    base = os.getenv("LOCALAPPDATA")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".local" / "share"
    path = root / "NE501_Multi_Pump_Controller"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


class CsvCommandLogger:
    def __init__(self) -> None:
        log_dir = user_data_directory(create=False) / "logs"
        filename = datetime.now().strftime("pump_log_%Y%m%d_%H%M%S_%f_") + uuid4().hex + '.csv'
        self.path = log_dir / filename
        self.initialization_error = None
        try:
            self._initialize()
        except OSError as exc:
            self.initialization_error = exc

    def _initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            if file.tell() == 0:
                writer.writerow(
                    ["timestamp", "address", "command", "status", "data",
                     "error", "alarm", "raw_hex"]
                )

    def write(
        self,
        address: int,
        command: str,
        response: Optional[PumpResponse] = None,
        error: str = "",
    ) -> None:
        if self.initialization_error is not None or not self.path.exists():
            self._initialize()
            self.initialization_error = None
        with self.path.open("a", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    datetime.now().isoformat(timespec="milliseconds"),
                    f"{address:02d}",
                    command,
                    response.status if response else "",
                    response.data if response else "",
                    error or (response.error_label if response else ""),
                    response.alarm_label if response else "",
                    response.raw_hex if response else "",
                ]
            )
