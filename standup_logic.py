from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Iterable, Optional

GMT_OFFSET_RANGE = list(range(-12, 15))


@dataclass
class ChannelState:
    active: bool = False
    timezone: str = "UTC"
    next_standup_at: datetime | None = None
    next_reminder_at: datetime | None = None
    ping_group_id: str | None = None
    ping_group_users: list[str] = field(default_factory=list)
    last_standup_ts: str | None = None
    last_thread_ts: str | None = None
    last_thread_users: list[str] = field(default_factory=list)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def serialize_channel_state(state: ChannelState) -> dict:
    return {
        "active": state.active,
        "timezone": state.timezone,
        "next_standup_at": state.next_standup_at.isoformat() if state.next_standup_at else None,
        "next_reminder_at": state.next_reminder_at.isoformat() if state.next_reminder_at else None,
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
        next_standup_at=_parse_iso_datetime(data.get("next_standup_at")),
        next_reminder_at=_parse_iso_datetime(data.get("next_reminder_at")),
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
