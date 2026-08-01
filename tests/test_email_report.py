import unittest

from email_report import should_send_email_report


class TestEmailReportLogic(unittest.TestCase):
    def test_no_signal_day_still_sends_daily_summary(self):
        self.assertTrue(should_send_email_report(0, 0))

    def test_signal_day_sends_daily_summary(self):
        self.assertTrue(should_send_email_report(3, 1))


if __name__ == "__main__":
    unittest.main()
