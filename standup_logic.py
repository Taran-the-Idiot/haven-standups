from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Iterable, Optional

GMT_OFFSET_RANGE = list(range(-12, 15))

# How often the bot re-pings people who still haven't replied in the standup
# thread. Two hours is the default and what we recommend in the setup modal.
DEFAULT_REMINDER_INTERVAL_HOURS = 2
REMINDER_INTERVAL_HOUR_CHOICES = [1, 2, 3, 4, 5, 6, 8, 12]

# How often a standup is posted. The keys are what gets written to the state
# file; "days" is how far apart two consecutive standups are.
DEFAULT_STANDUP_FREQUENCY = "daily"
STANDUP_FREQUENCIES: dict[str, dict] = {
    "daily": {"label": "Every day", "days": 1},
    "every_other_day": {"label": "Every other day", "days": 2},
    "weekly": {"label": "Once a week", "days": 7},
}

# Reminders stop this long after the standup was posted. Without it a weekly
# cadence would keep nagging every few hours for a full week.
REMINDER_WINDOW_HOURS = 24


@dataclass
class ChannelState:
    active: bool = False
    timezone: str = "UTC"
    standup_frequency: str = DEFAULT_STANDUP_FREQUENCY
    reminder_interval_hours: int = DEFAULT_REMINDER_INTERVAL_HOURS
    next_standup_at: datetime | None = None
    next_reminder_at: datetime | None = None
    reminder_end_at: datetime | None = None
    ping_group_id: str | None = None
    ping_group_users: list[str] = field(default_factory=list)
    last_standup_ts: str | None = None
    last_thread_ts: str | None = None
    last_thread_users: list[str] = field(default_factory=list)


def normalize_reminder_interval_hours(value) -> int:
    """Coerce a stored/submitted reply interval to one of the offered choices.

    Anything missing or unrecognised (including state files written before this
    setting existed) falls back to the default.
    """
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return DEFAULT_REMINDER_INTERVAL_HOURS

    if hours not in REMINDER_INTERVAL_HOUR_CHOICES:
        return DEFAULT_REMINDER_INTERVAL_HOURS

    return hours


def normalize_standup_frequency(value) -> str:
    """Same idea for how often a standup is posted: unknown -> the default."""
    if not value:
        return DEFAULT_STANDUP_FREQUENCY

    key = re.sub(r"[\s-]+", "_", str(value).strip().lower())
    if key not in STANDUP_FREQUENCIES:
        return DEFAULT_STANDUP_FREQUENCY

    return key


def standup_frequency_days(frequency: str | None) -> int:
    return STANDUP_FREQUENCIES[normalize_standup_frequency(frequency)]["days"]


def standup_frequency_label(frequency: str | None) -> str:
    return STANDUP_FREQUENCIES[normalize_standup_frequency(frequency)]["label"]


def describe_reminder_interval(hours) -> str:
    hours = normalize_reminder_interval_hours(hours)
    return "every hour" if hours == 1 else f"every {hours} hours"


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def serialize_channel_state(state: ChannelState) -> dict:
    return {
        "active": state.active,
        "timezone": state.timezone,
        "standup_frequency": state.standup_frequency,
        "reminder_interval_hours": state.reminder_interval_hours,
        "next_standup_at": state.next_standup_at.isoformat() if state.next_standup_at else None,
        "next_reminder_at": state.next_reminder_at.isoformat() if state.next_reminder_at else None,
        "reminder_end_at": state.reminder_end_at.isoformat() if state.reminder_end_at else None,
        "ping_group_id": state.ping_group_id,
        "ping_group_users": list(state.ping_group_users),
        "last_standup_ts": state.last_standup_ts,
        "last_thread_ts": state.last_thread_ts,
        "last_thread_users": list(state.last_thread_users),
    }


def deserialize_channel_state(data: dict) -> ChannelState:
    return ChannelState(
        active=bool(data.get("active", False)),
        timezone=data.get("timezone") or "UTC",
        standup_frequency=normalize_standup_frequency(data.get("standup_frequency")),
        reminder_interval_hours=normalize_reminder_interval_hours(data.get("reminder_interval_hours")),
        next_standup_at=_parse_iso_datetime(data.get("next_standup_at")),
        next_reminder_at=_parse_iso_datetime(data.get("next_reminder_at")),
        reminder_end_at=_parse_iso_datetime(data.get("reminder_end_at")),
        ping_group_id=data.get("ping_group_id"),
        ping_group_users=list(data.get("ping_group_users") or []),
        last_standup_ts=data.get("last_standup_ts"),
        last_thread_ts=data.get("last_thread_ts"),
        last_thread_users=list(data.get("last_thread_users") or []),
    )


def serialize_channels(channels: dict[str, ChannelState]) -> dict:
    return {channel_id: serialize_channel_state(state) for channel_id, state in channels.items()}


def deserialize_channels(data: dict | None) -> dict[str, ChannelState]:
    result: dict[str, ChannelState] = {}
    for channel_id, state_data in (data or {}).items():
        try:
            result[channel_id] = deserialize_channel_state(state_data)
        except (TypeError, ValueError):
            continue
    return result


def compute_missing_users(members: Iterable[str] | None, replies: Iterable[str] | None) -> list[str]:
    reply_set = set(replies or [])
    return [member for member in (members or []) if member not in reply_set]


def normalize_timezone_value(value: str | None) -> str:
    if not value:
        return "UTC"

    trimmed = str(value).strip()
    if trimmed.upper() == "UTC":
        return "UTC"

    match = re.match(r"^(?:GMT|UTC)([+-])(\d{1,2})(?::?(\d{2}))?$", trimmed, re.IGNORECASE)
    if not match:
        return trimmed

    sign, hours_text, minutes_text = match.groups()
    hours = int(hours_text)
    minutes = int(minutes_text or 0)
    if hours == 0 and minutes == 0:
        return "UTC"

    minute_suffix = f":{minutes:02d}" if minutes else ""
    return f"UTC{sign}{hours}{minute_suffix}"


def _timezone_from_value(value: str | None):
    normalized = normalize_timezone_value(value)
    if normalized == "UTC":
        return timezone.utc

    match = re.match(r"^UTC([+-])(\d{1,2})(?::?(\d{2}))?$", normalized, re.IGNORECASE)
    if match:
        sign, hours_text, minutes_text = match.groups()
        hours = int(hours_text)
        minutes = int(minutes_text or 0)
        offset = timedelta(hours=hours, minutes=minutes)
        if sign == "-":
            offset = -offset
        return timezone(offset)

    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        return timezone.utc


def next_standup_time(
    timezone_value: str,
    now: datetime | None = None,
    frequency: str | None = DEFAULT_STANDUP_FREQUENCY,
) -> datetime:
    """The next 08:00 to post at.

    If today's 08:00 hasn't happened yet we use it - that way activating a
    channel always gets a standup soon, whatever the cadence. Otherwise we skip
    ahead by the cadence, so calling this right after posting gives the day
    after / two days later / a week later.
    """
    tzinfo = _timezone_from_value(timezone_value)
    current = (now or datetime.now(timezone.utc)).astimezone(tzinfo)
    candidate = current.replace(hour=8, minute=0, second=0, microsecond=0)

    if candidate > current:
        return candidate

    return candidate + timedelta(days=standup_frequency_days(frequency))


def next_reminder_after(previous: datetime, now: datetime, interval_hours: int) -> datetime:
    """The first reminder slot after `now`, stepping from `previous`.

    Stepping by a single interval would leave the next slot still in the past
    whenever reminders fell behind (bot down, checks failing), and the minute
    poll would then fire one reminder per missed slot back to back.
    """
    step = timedelta(hours=interval_hours)
    candidate = previous + step
    if candidate <= now:
        missed = (now - candidate) // step + 1
        candidate += step * missed
    return candidate


def is_runnable_window(current_time: datetime, timezone_value: str) -> bool:
    tzinfo = _timezone_from_value(timezone_value)
    current = current_time.astimezone(tzinfo)
    return current.hour == 8 and current.minute == 0 and current.second == 0


def build_reminder_text(missing_users: Iterable[str] | None) -> str | None:
    users = list(missing_users or [])
    if not users:
        return None

    user_list = " ".join(f"<@{user}>" for user in users)
    return (
        f"Standup reminder: {user_list} - Yall haven't replied with an update yet! "
        "*Keep in mind saying why you’re not able to do stuff if you are busy is still an update!*"
    )


def get_timezone_options() -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for offset in GMT_OFFSET_RANGE:
        sign = "+" if offset >= 0 else "-"
        label = "GMT+0" if offset == 0 else f"GMT{sign}{abs(offset)}"
        value = "UTC" if offset == 0 else f"UTC{sign}{abs(offset)}"
        options.append(
            {
                "text": {"type": "plain_text", "text": label},
                "value": value,
            }
        )
    return options


def _select_option(label: str, value: str) -> dict:
    return {"text": {"type": "plain_text", "text": label}, "value": value}


def _find_option(options: list[dict], value: str) -> dict:
    for option in options:
        if option["value"] == value:
            return option
    return options[0]


def get_reminder_interval_options() -> list[dict]:
    options = []
    for hours in REMINDER_INTERVAL_HOUR_CHOICES:
        label = "Every hour" if hours == 1 else f"Every {hours} hours"
        if hours == DEFAULT_REMINDER_INTERVAL_HOURS:
            label += " (recommended)"
        options.append(_select_option(label, str(hours)))
    return options


def get_default_reminder_interval_option() -> dict:
    return _find_option(get_reminder_interval_options(), str(DEFAULT_REMINDER_INTERVAL_HOURS))


def get_standup_frequency_options() -> list[dict]:
    options = []
    for key, info in STANDUP_FREQUENCIES.items():
        label = info["label"]
        if key == DEFAULT_STANDUP_FREQUENCY:
            label += " (recommended)"
        options.append(_select_option(label, key))
    return options


def get_default_standup_frequency_option() -> dict:
    return _find_option(get_standup_frequency_options(), DEFAULT_STANDUP_FREQUENCY)


def is_channel_manager_user(user: dict | None, channel_creator_id: str | None, allowed_manager_ids: Iterable[str] | None = None) -> bool:
    if not user:
        return False

    allowed_ids = {str(value) for value in (allowed_manager_ids or [])}
    user_id = str(user.get("id")) if user.get("id") else None

    is_creator = bool(channel_creator_id and user_id and user_id == str(channel_creator_id))
    is_workspace_manager = bool(user.get("is_admin") or user.get("is_owner") or user.get("is_primary_owner"))
    is_configured_manager = bool(user_id and user_id in allowed_ids)

    return is_creator or is_workspace_manager or is_configured_manager


def matches_reset_key(provided_key: str | None, configured_key: str | None) -> bool:
    if not configured_key:
        return False

    return str(provided_key or "").strip() == str(configured_key).strip()
