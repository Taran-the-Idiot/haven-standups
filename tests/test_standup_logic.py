from __future__ import annotations

from datetime import datetime, timezone

import unittest

from standup_logic import (
    build_reminder_text,
    compute_missing_users,
    get_timezone_options,
    is_channel_manager_user,
    is_runnable_window,
    matches_reset_key,
    next_standup_time,
    normalize_timezone_value,
)


class StandupLogicTests(unittest.TestCase):
    def test_compute_missing_users(self):
        self.assertEqual(compute_missing_users(["U1", "U2", "U3"], ["U1"]), ["U2", "U3"])

    def test_next_standup_time(self):
        now = datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)
        next_time = next_standup_time("UTC-4", now)
        self.assertEqual(next_time.strftime("%Y-%m-%d %H:%M:%S"), "2026-08-28 08:00:00")

    def test_is_runnable_window(self):
        current = datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)
        self.assertTrue(is_runnable_window(current, "UTC"))

    def test_build_reminder_text(self):
        text = build_reminder_text(["U1", "U2"])
        self.assertIsNotNone(text)
        self.assertIn("<@U1>", text)
        self.assertIn("<@U2>", text)

    def test_build_reminder_text_empty(self):
        self.assertIsNone(build_reminder_text([]))

    def test_timezone_normalization(self):
        self.assertEqual(normalize_timezone_value("GMT+10"), "UTC+10")
        self.assertEqual(normalize_timezone_value("GMT-2"), "UTC-2")

    def test_timezone_options(self):
        options = get_timezone_options()
        self.assertTrue(any(option["text"]["text"] == "GMT+10" for option in options))
        self.assertTrue(any(option["text"]["text"] == "GMT-2" for option in options))

    def test_channel_manager_check(self):
        self.assertTrue(is_channel_manager_user({"id": "U123"}, "U123", []))
        self.assertTrue(is_channel_manager_user({"id": "U456", "is_owner": True}, "U789", []))
        self.assertFalse(is_channel_manager_user({"id": "U456"}, "U789", []))

    def test_reset_key(self):
        self.assertTrue(matches_reset_key("secret", "secret"))
        self.assertFalse(matches_reset_key("secret", "other"))


if __name__ == "__main__":
    unittest.main()
