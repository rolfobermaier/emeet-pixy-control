import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from emeet_pixy_control.backend import build_hid_report, clamp


class BackendHelpersTest(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-5, 0, 10), 0)
        self.assertEqual(clamp(50, 0, 10), 10)

    def test_hid_report_is_32_bytes(self):
        report = build_hid_report([0x09, 0x01, 0x01])
        self.assertEqual(len(report), 32)
        self.assertEqual(report[:3], b"\x09\x01\x01")
        self.assertEqual(report[3:], bytes(29))

    def test_hid_report_rejects_oversize(self):
        with self.assertRaises(Exception):
            build_hid_report(range(33))


if __name__ == "__main__":
    unittest.main()
