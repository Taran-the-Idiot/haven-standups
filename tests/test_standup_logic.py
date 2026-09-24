from __future__ import annotations

from datetime import datetime, timedelta, timezone

import unittest

from standup_logic import (
    DEFAULT_REMINDER_INTERVAL_HOURS,
    DEFAULT_STANDUP_FREQUENCY,
    build_reminder_text,
    compute_missing_users,
    deserialize_channel_state,
    get_reminder_interval_options,
    get_standup_frequency_options,
    get_timezone_options,
    is_channel_manager_user,
    is_runnable_window,
    matches_reset_key,
    next_reminder_after,
    next_standup_time,
    normalize_reminder_interval_hours,
    normalize_standup_frequency,
    normalize_timezone_value,
    serialize_channel_state,
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


class StandupFrequencyTests(unittest.TestCase):
    def test_next_standup_time_respects_frequency(self):
        # 09:00 local, so today's 08:00 has passed and we step by the cadence.
        now = datetime(2026, 8, 27, 13, 0, tzinfo=timezone.utc)
        self.assertEqual(
            next_standup_time("UTC-4", now, "daily").strftime("%Y-%m-%d %H:%M"),
            "2026-08-28 08:00",
        )
        self.assertEqual(
            next_standup_time("UTC-4", now, "every_other_day").strftime("%Y-%m-%d %H:%M"),
            "2026-08-29 08:00",
        )
        self.assertEqual(
            next_standup_time("UTC-4", now, "weekly").strftime("%Y-%m-%d %H:%M"),
            "2026-09-03 08:00",
        )

    def test_next_standup_time_uses_todays_slot_when_still_ahead(self):
        # 06:00 local: the first standup lands today whatever the cadence.
        now = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(
            next_standup_time("UTC-4", now, "weekly").strftime("%Y-%m-%d %H:%M"),
            "2026-08-27 08:00",
        )

    def test_normalize_standup_frequency(self):
        self.assertEqual(normalize_standup_frequency("weekly"), "weekly")
        self.assertEqual(normalize_standup_frequency("Every Other Day"), "every_other_day")
        self.assertEqual(normalize_standup_frequency("nonsense"), DEFAULT_STANDUP_FREQUENCY)
        self.assertEqual(normalize_standup_frequency(None), DEFAULT_STANDUP_FREQUENCY)

    def test_normalize_reminder_interval_hours(self):
        self.assertEqual(normalize_reminder_interval_hours("3"), 3)
        self.assertEqual(normalize_reminder_interval_hours(99), DEFAULT_REMINDER_INTERVAL_HOURS)
        self.assertEqual(normalize_reminder_interval_hours(None), DEFAULT_REMINDER_INTERVAL_HOURS)

    def test_options_mark_the_recommended_choice(self):
        frequency_labels = [option["text"]["text"] for option in get_standup_frequency_options()]
        self.assertIn("Every day (recommended)", frequency_labels)
        interval_labels = [option["text"]["text"] for option in get_reminder_interval_options()]
        self.assertIn("Every 2 hours (recommended)", interval_labels)
        self.assertIn("Every hour", interval_labels)


class StateCompatibilityTests(unittest.TestCase):
    def test_state_without_new_keys_falls_back_to_defaults(self):
        legacy = {
            "active": True,
            "timezone": "UTC-5",
            "next_standup_at": "2026-09-03T08:00:00-05:00",
            "ping_group_id": "S123",
        }
        state = deserialize_channel_state(legacy)
        self.assertEqual(state.standup_frequency, DEFAULT_STANDUP_FREQUENCY)
        self.assertEqual(state.reminder_interval_hours, DEFAULT_REMINDER_INTERVAL_HOURS)
        self.assertIsNone(state.reminder_end_at)
        # Everything the old file did carry survives untouched.
        self.assertTrue(state.active)
        self.assertEqual(state.timezone, "UTC-5")
        self.assertEqual(state.ping_group_id, "S123")

    def test_bad_values_fall_back_instead_of_raising(self):
        state = deserialize_channel_state({"standup_frequency": "fortnightly", "reminder_interval_hours": "soon"})
        self.assertEqual(state.standup_frequency, DEFAULT_STANDUP_FREQUENCY)
        self.assertEqual(state.reminder_interval_hours, DEFAULT_REMINDER_INTERVAL_HOURS)

    def test_round_trip(self):
        state = deserialize_channel_state({"standup_frequency": "weekly", "reminder_interval_hours": 6})
        restored = deserialize_channel_state(serialize_channel_state(state))
        self.assertEqual(restored.standup_frequency, "weekly")
        self.assertEqual(restored.reminder_interval_hours, 6)

    def test_next_reminder_after_steps_one_interval_when_on_time(self):
        tz = timezone(timedelta(hours=9))
        previous = datetime(2026, 9, 24, 10, 0, tzinfo=tz)
        now = datetime(2026, 9, 24, 10, 0, 30, tzinfo=tz)
        self.assertEqual(next_reminder_after(previous, now, 2), datetime(2026, 9, 24, 12, 0, tzinfo=tz))

    def test_next_reminder_after_skips_missed_slots_instead_of_catching_up(self):
        tz = timezone(timedelta(hours=9))
        previous = datetime(2026, 9, 24, 10, 0, tzinfo=tz)
        now = datetime(2026, 9, 24, 19, 25, tzinfo=tz)
        # 12:00-18:00 were missed; the next reminder is 20:00, not 12:00.
        self.assertEqual(next_reminder_after(previous, now, 2), datetime(2026, 9, 24, 20, 0, tzinfo=tz))

    def test_next_reminder_after_exact_slot_moves_past_now(self):
        tz = timezone.utc
        previous = datetime(2026, 9, 24, 10, 0, tzinfo=tz)
        now = datetime(2026, 9, 24, 14, 0, tzinfo=tz)
        self.assertEqual(next_reminder_after(previous, now, 2), datetime(2026, 9, 24, 16, 0, tzinfo=tz))


if __name__ == "__main__":
    unittest.main()
