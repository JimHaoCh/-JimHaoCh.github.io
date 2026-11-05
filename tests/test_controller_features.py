import unittest

from ne501.controller import (
    ProgramSettings,
    choose_program_volume_unit,
    convert_volume,
    format_pump_number,
    maximum_rate_ml_hr,
    normalize_rate,
    prime_rate_ml_hr,
    PRIME_SPEED_LEVELS,
    NE501Controller,
)
from ne501.protocol import parse_response
from ne501.mock_controller import MockNE501Controller


class ScriptedStopController(NE501Controller):
    def __init__(self, statuses):
        super().__init__()
        self.statuses = list(statuses)
        self.commands = []

    def send_command(self, address: int, command: str):
        self.commands.append(command)
        status, data = self.statuses.pop(0)
        raw = b"\x02" + f"{address:02d}{status}{data}".encode("ascii") + b"\x03"
        return parse_response(raw, expected_address=address)


class ControllerFeatureTests(unittest.TestCase):
    def test_four_digit_and_three_decimal_format(self):
        self.assertEqual(format_pump_number(123.456), "123.5")
        self.assertEqual(format_pump_number(12.345), "12.35")
        self.assertEqual(format_pump_number(1.23456), "1.235")
        self.assertEqual(format_pump_number(0.001), "0.001")
        with self.assertRaises(ValueError):
            format_pump_number(0.0001)

    def test_small_ml_hr_rate_auto_converts_to_ul_hr(self):
        value, unit, text = normalize_rate(0.0001, "MH")
        self.assertEqual(unit, "UH")
        self.assertEqual(text, "0.1")
        self.assertAlmostEqual(value, 0.1)

    def test_max_rate_for_14_43_mm_syringe(self):
        self.assertAlmostEqual(maximum_rate_ml_hr(14.43), 500.5, delta=0.3)

    def test_prime_speed_levels_are_bounded_and_ordered(self):
        self.assertEqual(PRIME_SPEED_LEVELS["MAX"], 1.0)
        rates = [prime_rate_ml_hr(10.0, level) for level in ["MAX", "HIGH", "MEDIUM", "LOW", "MIN"]]
        self.assertTrue(all(a > b for a, b in zip(rates, rates[1:])))
        self.assertAlmostEqual(rates[0], maximum_rate_ml_hr(10.0), places=6)
        self.assertAlmostEqual(rates[-1], maximum_rate_ml_hr(10.0) * 0.05, places=6)

    def test_mock_uses_selected_prime_speed_level(self):
        controller = MockNE501Controller([0], latency=0)
        controller.connect()
        self.assertTrue(controller.set_diameter(0, 10.0).confirmed)
        settings = ProgramSettings(
            rate=20.0, rate_unit="UM", direction="INF", continuous=True,
            volume=1.0, volume_unit="ML", prime_enabled=True,
            prime_volume=100.0, prime_volume_unit="UL", prime_speed_level="LOW",
            diameter_mm=10.0,
        )
        confirmation = controller.configure_program(0, settings)
        self.assertTrue(confirmation.verified)
        expected = prime_rate_ml_hr(10.0, "LOW")
        self.assertAlmostEqual(confirmation.prime_rate_ml_hr, expected, delta=0.05)

    def test_mixed_prime_and_target_volumes_use_one_global_unit(self):
        settings = ProgramSettings(
            rate=20.0,
            rate_unit="UM",
            direction="WDR",
            continuous=False,
            volume=1.0,
            volume_unit="ML",
            prime_enabled=True,
            prime_volume=100.0,
            prime_volume_unit="UL",
            prime_speed_level="LOW",
            diameter_mm=10.0,
        )
        unit, values = choose_program_volume_unit(settings)
        self.assertEqual(unit, "ML")
        self.assertEqual(values["Prime volume"][1], "0.1")
        self.assertEqual(values["Target volume"][1], "1")

    def test_ensure_stopped_does_not_send_stp_when_already_stopped(self):
        controller = ScriptedStopController([("S", "")])
        results = controller._ensure_program_stopped(0)
        self.assertEqual(controller.commands, [""])
        self.assertEqual(results[0][1], "STATUS")

    def test_ensure_stopped_resets_running_program(self):
        controller = ScriptedStopController([("I", ""), ("P", ""), ("S", "")])
        results = controller._ensure_program_stopped(0)
        self.assertEqual(controller.commands, ["", "STP", "STP"])
        self.assertEqual(results[-1][2].status, "S")

    def test_prime_then_continuous_steady_program(self):
        controller = MockNE501Controller([0], latency=0)
        controller.connect()
        self.assertTrue(controller.set_diameter(0, 14.43).confirmed)
        settings = ProgramSettings(
            rate=100.0,
            rate_unit="UM",
            direction="INF",
            continuous=True,
            volume=1.0,
            volume_unit="ML",
            prime_enabled=True,
            prime_volume=250.0,
            prime_volume_unit="UL",
            prime_speed_level="MEDIUM",
            diameter_mm=14.43,
        )
        confirmation = controller.configure_program(0, settings)
        self.assertTrue(confirmation.verified)
        state = controller.pumps[0]
        self.assertEqual(state.volume_unit, "UL")
        self.assertEqual(state.phases[1].volume, 250.0)
        self.assertEqual(state.phases[2].rate, 100.0)
        self.assertEqual(state.phases[2].rate_unit, "UM")
        self.assertEqual(state.phases[2].volume, 0.0)

    def test_prime_then_finite_steady_ends_with_stop(self):
        controller = MockNE501Controller([1], latency=0)
        controller.connect()
        self.assertTrue(controller.set_diameter(1, 10.0).confirmed)
        settings = ProgramSettings(
            rate=1.5,
            rate_unit="MH",
            direction="INF",
            continuous=False,
            volume=2.0,
            volume_unit="ML",
            prime_enabled=True,
            prime_volume=0.2,
            prime_volume_unit="ML",
            prime_speed_level="LOW",
            diameter_mm=10.0,
        )
        confirmation = controller.configure_program(1, settings)
        self.assertTrue(confirmation.verified)
        self.assertEqual(controller.pumps[1].phases[3].function, "STP")


class FakeSerial:
    def __init__(self, payload: bytes):
        self.payload = bytearray(payload)
        self.is_open = True
        self.written = bytearray()

    def reset_input_buffer(self):
        pass

    def write(self, data: bytes):
        self.written.extend(data)
        return len(data)

    def flush(self):
        pass

    def read(self, size: int = 1):
        if not self.payload:
            return b""
        data = bytes(self.payload[:size])
        del self.payload[:size]
        return data

    def close(self):
        self.is_open = False


class SerialHardeningTests(unittest.TestCase):
    def test_rejects_mismatched_response_address(self):
        from ne501.controller import PumpConnectionError

        controller = NE501Controller(timeout=0.02, inter_command_delay=0)
        controller._serial = FakeSerial(b"\x0201SNE501V3.934\x03")
        with self.assertRaises(PumpConnectionError):
            controller.send_command(0, "VER")

    def test_rejects_incomplete_response_without_etx(self):
        from ne501.controller import PumpTimeoutError

        controller = NE501Controller(timeout=0.005, inter_command_delay=0)
        controller._serial = FakeSerial(b"\x0200SNE501V3.934")
        with self.assertRaises(PumpTimeoutError):
            controller.send_command(0, "VER")


class ConfigValidationTests(unittest.TestCase):
    def test_duplicate_addresses_fall_back_to_defaults(self):
        from ne501.config import _validated_config, DEFAULT_CONFIG

        config = _validated_config({"addresses": [0, 0, 2, 3]})
        self.assertEqual(config["addresses"], DEFAULT_CONFIG["addresses"])

    def test_invalid_baudrate_falls_back_to_19200(self):
        from ne501.config import _validated_config

        config = _validated_config({"baudrate": 115200})
        self.assertEqual(config["baudrate"], 19200)


if __name__ == "__main__":
    unittest.main()
