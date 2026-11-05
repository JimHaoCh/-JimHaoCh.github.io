from __future__ import annotations

import csv
from datetime import datetime
import os
from pathlib import Path
from typing import Optional

from .protocol import PumpResponse


def user_data_directory() -> Path:
    base = os.getenv("LOCALAPPDATA")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".local" / "share"
    path = root / "NE501_Multi_Pump_Controller"
    path.mkdir(parents=True, exist_ok=True)
    return path


class CsvCommandLogger:
    def __init__(self) -> None:
        log_dir = user_data_directory() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        filename = datetime.now().strftime("pump_log_%Y%m%d_%H%M%S.csv")
        self.path = log_dir / filename
        with self.path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "timestamp",
                    "address",
                    "command",
                    "status",
                    "data",
                    "error",
                    "alarm",
                    "raw_hex",
                ]
            )

    def write(
        self,
        address: int,
        command: str,
        response: Optional[PumpResponse] = None,
        error: str = "",
    ) -> None:
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
