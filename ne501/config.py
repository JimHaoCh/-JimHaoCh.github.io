from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "port": "COM4",
    "baudrate": 19200,
    "addresses": [0, 1, 2, 3],
    "window_title": "NE-501 Multi Pump Controller v1.0.1",
}

VALID_BAUDRATES = {300, 1200, 2400, 9600, 19200}


def resource_path(relative: str) -> Path:
    """Return the bundled resource path for source or PyInstaller builds."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / relative


def external_config_path() -> Path:
    """Return an editable config.json beside the source tree or final EXE."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config.json"
    return Path(__file__).resolve().parents[1] / "config.json"


def user_config_path() -> Path:
    """A writable location shared by installs and preserved across upgrades."""
    root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share"))
    return root / "NE501_Multi_Pump_Controller" / "config.json"


def _validated_config(candidate: dict[str, Any]) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)

    port = candidate.get("port")
    if isinstance(port, str) and port.strip():
        config["port"] = port.strip()

    baudrate = candidate.get("baudrate")
    try:
        baudrate_int = int(baudrate)
    except (TypeError, ValueError):
        baudrate_int = DEFAULT_CONFIG["baudrate"]
    if baudrate_int in VALID_BAUDRATES:
        config["baudrate"] = baudrate_int

    addresses = candidate.get("addresses")
    if isinstance(addresses, list):
        try:
            normalized = [int(value) for value in addresses]
        except (TypeError, ValueError):
            normalized = []
        if normalized and len(normalized) == len(set(normalized)) and all(0 <= value <= 99 for value in normalized):
            config["addresses"] = normalized

    title = candidate.get("window_title")
    if isinstance(title, str) and title.strip():
        cleaned_title = title.strip()
        if cleaned_title == "NE-501 Multi Pump Controller v1.0.0":
            cleaned_title = DEFAULT_CONFIG["window_title"]
        config["window_title"] = cleaned_title

    return config


def load_config() -> dict[str, Any]:
    """Load validated configuration.

    The per-user copy takes precedence for installed builds. A portable or
    source-side config and then the bundled defaults provide fallbacks.
    Existing installations without a user copy retain their original settings.
    """
    candidates = [user_config_path(), external_config_path(), resource_path("config.json")]
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            config = _validated_config(loaded)
            # Preserve the first valid older beside-the-EXE config on first run.
            # Never overwrite an existing per-user file, even if it is malformed.
            user_path = user_config_path()
            try:
                user_path.parent.mkdir(parents=True, exist_ok=True)
                with user_path.open("x", encoding="utf-8") as output:
                    json.dump(config, output, ensure_ascii=False, indent=2)
                    output.write("\n")
            except (OSError, FileExistsError):
                pass
            return config
    return dict(DEFAULT_CONFIG)
