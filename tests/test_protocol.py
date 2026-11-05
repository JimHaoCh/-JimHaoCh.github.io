import unittest

from ne501.protocol import build_command, first_float, parse_response


class ProtocolTests(unittest.TestCase):
    def test_build_normal_command(self):
        self.assertEqual(build_command(3, "ver"), b"03VER\r")

    def test_build_system_command(self):
        self.assertEqual(build_command(0, "*ADR"), b"*ADR\r")

    def test_build_status_query(self):
        self.assertEqual(build_command(3, ""), b"03\r")

    def test_parse_two_digit_address(self):
        response = parse_response(b"\x0203SNE501V3.9\x03", expected_address=3)
        self.assertEqual(response.address, 3)
        self.assertEqual(response.status, "S")
        self.assertEqual(response.data, "NE501V3.9")
        self.assertTrue(response.ok)

    def test_parse_one_digit_address(self):
        response = parse_response(b"\x023I12.4MH\x03", expected_address=3)
        self.assertEqual(response.address, 3)
        self.assertEqual(response.status, "I")
        self.assertEqual(response.data, "12.4MH")

    def test_parse_error(self):
        response = parse_response(b"\x0200S?OOR\x03", expected_address=0)
        self.assertEqual(response.error_code, "OOR")
        self.assertFalse(response.ok)

    def test_first_float(self):
        self.assertAlmostEqual(first_float("14.43 MM"), 14.43)
        self.assertIsNone(first_float("NONE"))


if __name__ == "__main__":
    unittest.main()
