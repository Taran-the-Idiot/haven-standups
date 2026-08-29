from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Iterable, Optional

GMT_OFFSET_RANGE = list(range(-12, 15))


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


def next_standup_time(timezone_value: str, now: datetime | None = None) -> datetime:
    tzinfo = _timezone_from_value(timezone_value)
    current = (now or datetime.now(timezone.utc)).astimezone(tzinfo)
    candidate = current.replace(hour=8, minute=0, second=0, microsecond=0)

    if candidate > current:
        return candidate

    return candidate + timedelta(days=1)


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
        "*Keep in mind saying why you’re not able to do stuff if you are busy is an update!*"
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
