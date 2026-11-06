from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ne501 import config
from ne501.protocol import parse_response
from ne501.stop_report import stop_all_independently
from ne501.task_gate import TaskGate


class StopAllTests(unittest.TestCase):
    @staticmethod
    def response(address, status="S", data=""):
        return parse_response(f"\x02{address:02d}{status}{data}\x03".encode(), address)

    def test_attempts_remaining_pumps_when_one_times_out(self):
        class Controller:
            calls = []
            def stop_pump(self, address):
                self.calls.append(address)
                if address == 1:
                    raise TimeoutError("No reply")
                return [(address, "STATUS", StopAllTests.response(address))]

        controller = Controller()
        report = stop_all_independently(controller, range(4))
        self.assertEqual(controller.calls, [0, 1, 2, 3])
        self.assertEqual(report.confirmed, [0, 2, 3])
        self.assertIn(1, report.unconfirmed)

    def test_nonstopped_or_rejected_response_is_never_marked_stopped(self):
        class Controller:
            def stop_pump(self, address):
                if address == 0:
                    return [(address, "STP", StopAllTests.response(address, "P"))]
                if address == 1:
                    return [(address, "STP", StopAllTests.response(address, "S", "?OOR"))]
                return []
        report = stop_all_independently(Controller(), [0, 1, 2])
        self.assertEqual(report.confirmed, [])
        self.assertEqual(set(report.unconfirmed), {0, 1, 2})

    def test_already_stopped_na_is_accepted_only_for_stp(self):
        class Controller:
            def stop_pump(self, address):
                command = "STP" if address == 0 else "STATUS"
                return [(address, command, StopAllTests.response(address, "S", "?NA"))]
        report = stop_all_independently(Controller(), [0, 1])
        self.assertEqual(report.confirmed, [0])
        self.assertIn(1, report.unconfirmed)


class TaskGateTests(unittest.TestCase):
    def test_stop_invalidates_previously_queued_work(self):
        gate = TaskGate()
        old_ticket = gate.ordinary_ticket()
        stop_ticket = gate.begin_stop()
        self.assertFalse(gate.is_current(old_ticket))
        self.assertTrue(gate.is_current(stop_ticket))
        self.assertIsNone(gate.ordinary_ticket())
        self.assertIsNone(gate.begin_stop())
        gate.end_stop(stop_ticket)
        self.assertEqual(gate.ordinary_ticket(), stop_ticket)
        self.assertFalse(gate.is_current(old_ticket))

    def test_old_stop_completion_cannot_unlock_new_generation(self):
        gate = TaskGate()
        first = gate.begin_stop()
        gate.end_stop(first)
        second = gate.begin_stop()
        gate.end_stop(first)
        self.assertIsNone(gate.ordinary_ticket())
        gate.end_stop(second)
        self.assertEqual(gate.ordinary_ticket(), second)


class UserConfigTests(unittest.TestCase):
    def test_first_run_migrates_legacy_config_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            legacy = root / "legacy.json"
            legacy.write_text(json.dumps({"port": "COM9", "baudrate": 19200, "addresses": [0, 1, 2, 3]}))
            bundled = root / "missing.json"
            with patch.dict("os.environ", {"LOCALAPPDATA": str(root / "user")}):
                with patch.object(config, "external_config_path", return_value=legacy):
                    with patch.object(config, "resource_path", return_value=bundled):
                        self.assertEqual(config.load_config()["port"], "COM9")
                        user_file = config.user_config_path()
                        self.assertEqual(json.loads(user_file.read_text())["port"], "COM9")
                        legacy.write_text(json.dumps({"port": "COM6"}))
                        self.assertEqual(config.load_config()["port"], "COM9")

    def test_invalid_existing_user_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            user = root / "user" / "NE501_Timeline_UI_Preview" / "config.json"
            user.parent.mkdir(parents=True)
            user.write_text("invalid JSON")
            legacy = root / "legacy.json"
            legacy.write_text(json.dumps({"port": "COM7"}))
            with patch.dict("os.environ", {"LOCALAPPDATA": str(root / "user")}):
                with patch.object(config, "external_config_path", return_value=legacy):
                    self.assertEqual(config.load_config()["port"], "COM7")
            self.assertEqual(user.read_text(), "invalid JSON")


if __name__ == "__main__":
    unittest.main()
