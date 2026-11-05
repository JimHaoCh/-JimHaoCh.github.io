import unittest

from ne501.mock_controller import MockNE501Controller


class MockControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = MockNE501Controller(range(4), latency=0)
        self.controller.connect()

    def tearDown(self):
        self.controller.disconnect()

    def test_scan_four_pumps(self):
        responses = self.controller.scan(range(4))
        self.assertEqual(set(responses), {0, 1, 2, 3})

    def test_confirm_diameter(self):
        confirmation = self.controller.set_diameter(2, 14.43)
        self.assertTrue(confirmation.confirmed)
        self.assertAlmostEqual(confirmation.confirmed_mm, 14.43)

    def test_stop_idle_pump_uses_status_query_without_false_na(self):
        results = self.controller.stop_pump(0)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], "STATUS")
        self.assertTrue(results[0][2].ok)
        self.assertEqual(results[0][2].status, "S")

    def test_direct_stp_on_idle_pump_matches_real_firmware_na(self):
        response = self.controller.send_command(0, "STP")
        self.assertEqual(response.status, "S")
        self.assertEqual(response.error_code, "NA")

    def test_independent_run_stop(self):
        self.controller.send_command(0, "DIR INF")
        self.controller.send_command(0, "RUN")
        self.controller.send_command(2, "DIR WDR")
        self.controller.send_command(2, "RUN")
        self.assertEqual(self.controller.pumps[0].status, "I")
        self.assertEqual(self.controller.pumps[2].status, "W")
        self.assertEqual(self.controller.pumps[1].status, "S")
        self.controller.stop_all(range(4))
        self.assertTrue(all(pump.status == "S" for pump in self.controller.pumps.values()))


if __name__ == "__main__":
    unittest.main()
