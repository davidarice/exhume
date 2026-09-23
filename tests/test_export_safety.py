import unittest

from orchestrator.export import _safe_channel_count


class ExportSafetyTests(unittest.TestCase):
    def test_accepts_plausible_channel_counts(self):
        self.assertEqual(_safe_channel_count(1), 1)
        self.assertEqual(_safe_channel_count("24"), 24)
        self.assertEqual(_safe_channel_count(64), 64)

    def test_rejects_binary_false_positives(self):
        self.assertEqual(_safe_channel_count(0), 2)
        self.assertEqual(_safe_channel_count(-1), 2)
        self.assertEqual(_safe_channel_count(6_619_138), 2)
        self.assertEqual(_safe_channel_count(9_633_793), 2)
        self.assertEqual(_safe_channel_count(None), 2)


if __name__ == "__main__":
    unittest.main()
