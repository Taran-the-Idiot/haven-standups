from __future__ import annotations

import json
import logging
import os
import ssl as ssl_lib
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import certifi
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from standup_logic import (
    ChannelState,
    build_reminder_text,
    compute_missing_users,
    deserialize_channels,
    get_timezone_options,
    is_channel_manager_user,
    is_runnable_window,
    matches_reset_key,
    next_standup_time,
    normalize_timezone_value,
    serialize_channels,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Some Python builds (notably the python.org macOS installer) ship without a
# usable system CA bundle, which makes every HTTPS call to Slack fail with
# CERTIFICATE_VERIFY_FAILED. Pin the client to certifi's bundle so both the Web
# API calls and the Socket Mode websocket verify correctly on any machine.
ssl_context = ssl_lib.create_default_context(cafile=certifi.where())

app = App(
    client=WebClient(
        token=os.environ.get("SLACK_BOT_TOKEN"),
        ssl=ssl_context,
    ),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    token_verification_enabled=False,
)

channels: dict[str, ChannelState] = {}
standup_timers: dict[str, threading.Timer] = {}

# Bot state (which channels are active, their timezone/ping group, and the
# next scheduled times) lives only in the `channels` dict above, so without
# persistence a process restart would silently deactivate every channel.
# Persist it to a small JSON file and reload it on startup.
STATE_FILE = Path(os.environ.get("STANDUP_STATE_FILE", "standup_state.json"))
_state_file_lock = threading.Lock()


def save_state() -> None:
    with _state_file_lock:
        try:
            data = serialize_channels(channels)
            tmp_path = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
            tmp_path.write_text(json.dumps(data, indent=2))
            tmp_path.replace(STATE_FILE)
        except OSError:
            logger.exception("Failed to save standup state to %s", STATE_FILE)


def load_state() -> None:
    if not STATE_FILE.exists():
        return

    try:
        raw = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to read standup state from %s; starting with no state", STATE_FILE)
        return

    channels.update(deserialize_channels(raw))
    logger.info("Loaded standup state for %d channel(s) from %s", len(channels), STATE_FILE)


def restore_standup_timers() -> None:
    for channel_id, state in channels.items():
        if state.active:
            schedule_standup_timer(channel_id)


def get_channel_state(channel_id: str) -> ChannelState:
    if channel_id not in channels:
        channels[channel_id] = ChannelState()
    return channels[channel_id]


def clear_standup_timer(channel_id: str) -> None:
    timer = standup_timers.pop(channel_id, None)
    if timer:
        timer.cancel()


def schedule_standup_timer(channel_id: str) -> None:
    state = get_channel_state(channel_id)
    clear_standup_timer(channel_id)

    if not state.active or not state.next_standup_at:
        return

    now = datetime.now(timezone.utc).astimezone(state.next_standup_at.tzinfo or timezone.utc)
    delay = max(0.0, (state.next_standup_at - now).total_seconds())

    def fire() -> None:
        standup_timers.pop(channel_id, None)
        current_state = get_channel_state(channel_id)
        if not current_state.active or not current_state.next_standup_at:
            return

        current_now = datetime.now(timezone.utc).astimezone(current_state.next_standup_at.tzinfo or timezone.utc)
        if current_now >= current_state.next_standup_at:
            run_standup_post(channel_id, "timer")

    timer = threading.Timer(delay, fire)
    timer.daemon = True
    standup_timers[channel_id] = timer
    timer.start()


def parse_ping_group_id(value: str | None) -> str:
    if not value:
        return ""

    trimmed = value.strip()
    if trimmed.startswith("<!subteam^") and trimmed.endswith(">"):
        inner = trimmed[len("<!subteam^") : -1]
        return inner.split("|", 1)[0]

    return trimmed


def fetch_ping_group_users(client, ping_group_id: str) -> list[str]:
    response = client.api_call("usergroups.users.list", params={"usergroup": ping_group_id})
    return response.get("users", []) or []


def fetch_ping_group_options(client, query: str | None = None) -> list[dict[str, str]]:
    response = client.api_call("usergroups.list")
    usergroups = response.get("usergroups", []) or []
    normalized_query = (query or "").strip().lower()

    options: list[dict[str, str]] = []
    for group in usergroups:
        # Skip deleted user groups; keep the active ones.
        if group.get("date_delete"):
            continue

        label = group.get("handle") or group.get("name") or group.get("id")
        searchable_text = f"{group.get('handle', '')} {group.get('name', '')}".lower()
        if normalized_query and normalized_query not in searchable_text:
            continue

        options.append(
            {
                "text": {"type": "plain_text", "text": label},
                "value": group.get("id", ""),
            }
        )

    options.sort(key=lambda item: item["text"]["text"].lower())
    return options


def reset_channel_state(channel_id: str) -> ChannelState:
    state = get_channel_state(channel_id)
    state.active = False
    state.timezone = "UTC"
    state.next_standup_at = None
    state.next_reminder_at = None
    state.ping_group_id = None
    state.ping_group_users = []
    state.last_standup_ts = None
    state.last_thread_ts = None
    state.last_thread_users = []
    clear_standup_timer(channel_id)
    save_state()
    return state


def format_duration_until_standup(timezone_value: str) -> str:
    now = datetime.now(timezone.utc)
    next_run = next_standup_time(timezone_value, now)
    total_minutes = max(0, round((next_run - now.astimezone(next_run.tzinfo or timezone.utc)).total_seconds() / 60))
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes}m"


def is_channel_manager(client, channel_id: str, user_id: str) -> bool:
    try:
        channel_info = client.api_call("conversations.info", params={"channel": channel_id})
        user_info = client.api_call("users.info", params={"user": user_id})
        configured = [value.strip() for value in os.environ.get("CHANNEL_MANAGER_USER_IDS", "").split(",") if value.strip()]
        return is_channel_manager_user(user_info.get("user", {}), channel_info.get("channel", {}).get("creator"), configured)
    except SlackApiError:
        logger.exception("Channel-manager check failed")
        return False


def activate_standup(channel_id: str, user_id: str, timezone_value: str, ping_group_id: str) -> dict[str, object]:
    state = get_channel_state(channel_id)

    if not is_channel_manager(app.client, channel_id, user_id):
        return {"ok": False, "text": "Only channel managers can activate standups in this channel."}

    if not ping_group_id:
        return {"ok": False, "text": "Please choose a ping group for this channel."}

    try:
        ping_group_users = fetch_ping_group_users(app.client, ping_group_id)
    except SlackApiError:
        logger.exception("Failed to validate ping group %s", ping_group_id)
        return {"ok": False, "text": "That ping group could not be loaded. Check the user group and try again."}

    if not ping_group_users:
        return {"ok": False, "text": "That ping group has no members to notify."}

    state.active = True
    state.timezone = timezone_value
    state.ping_group_id = ping_group_id
    state.ping_group_users = ping_group_users
    state.next_standup_at = next_standup_time(timezone_value, datetime.now(timezone.utc))
    state.next_reminder_at = state.next_standup_at + timedelta(hours=2)
    state.last_standup_ts = None
    state.last_thread_ts = None
    state.last_thread_users = []
    schedule_standup_timer(channel_id)
    save_state()

    logger.info(
        "Standup activation for %s will send the first standup in %s.",
        channel_id,
        format_duration_until_standup(timezone_value),
    )

    return {
        "ok": True,
        "text": f"Standup bot activated for this channel in {timezone_value}. The next morning standup will be sent at 08:00 {timezone_value}.",
    }


def send_standup_message(channel_id: str) -> None:
    state = get_channel_state(channel_id)
    now = datetime.now(timezone.utc)

    if not state.ping_group_id:
        raise RuntimeError("Ping group is not configured for this channel")

    try:
        state.ping_group_users = fetch_ping_group_users(app.client, state.ping_group_id)
    except SlackApiError:
        logger.exception("Failed to load ping group %s for %s", state.ping_group_id, channel_id)

    ping_text = f"<!subteam^{state.ping_group_id}>"
    response = app.client.api_call(
        "chat.postMessage",
        json={
            "channel": channel_id,
            "text": (
                f"Good morning {ping_text}!\n\n"
                "- What did you do yesterday?\n"
                "- What do you plan to do today?\n\n"
                "_If you didn’t do anything yesterday and/or won’t get anything done today that’s fine! Please just say so & why you won’t get anything done instead of not replying._"
            ),
        },
    )

    state.last_standup_ts = response.get("ts")
    state.last_thread_ts = response.get("ts")
    state.last_thread_users = list(state.ping_group_users)
    state.next_standup_at = next_standup_time(state.timezone, now)
    state.next_reminder_at = now.astimezone(state.next_standup_at.tzinfo or timezone.utc) + timedelta(hours=2)
    schedule_standup_timer(channel_id)
    save_state()

    logger.info("Standup scheduled for %s at %s", channel_id, state.next_standup_at.isoformat())


def run_standup_post(channel_id: str, source: str) -> None:
    try:
        send_standup_message(channel_id)
    except Exception:
        logger.exception("Failed to send standup for %s from %s", channel_id, source)


def check_thread_reminders(channel_id: str) -> None:
    state = get_channel_state(channel_id)
    if not state.active or not state.last_thread_ts or not state.ping_group_id:
        return

    try:
        group_users = fetch_ping_group_users(app.client, state.ping_group_id)
    except SlackApiError:
        logger.exception("Failed to reload ping group %s for reminders", state.ping_group_id)
        group_users = list(state.ping_group_users)

    state.ping_group_users = group_users or state.ping_group_users

    replies = app.client.api_call(
        "conversations.replies",
        params={"channel": channel_id, "ts": state.last_thread_ts, "limit": 200},
    )
    thread_replies = replies.get("messages", []) or []
    participants = [message.get("user") for message in thread_replies if message.get("user") and message.get("user") != "USLACKBOT"]
    missing_users = compute_missing_users(state.ping_group_users, participants)
    text = build_reminder_text(missing_users)

    if text:
        app.client.api_call(
            "chat.postMessage",
            json={
                "channel": channel_id,
                "thread_ts": state.last_thread_ts,
                "text": text,
            },
        )


def schedule_checks() -> None:
    now = datetime.now(timezone.utc)

    for channel_id, state in list(channels.items()):
        if not state.active:
            continue

        if state.next_standup_at and now.astimezone(state.next_standup_at.tzinfo or timezone.utc) >= state.next_standup_at:
            run_standup_post(channel_id, "poll")

        if state.next_reminder_at and state.last_thread_ts:
            current_local = now.astimezone(state.next_reminder_at.tzinfo or timezone.utc)
            if current_local >= state.next_reminder_at and state.next_standup_at and state.next_reminder_at < state.next_standup_at:
                check_thread_reminders(channel_id)
                state.next_reminder_at = state.next_reminder_at + timedelta(hours=2)
                if state.next_reminder_at >= state.next_standup_at:
                    state.next_reminder_at = None
                save_state()


def scheduler_loop() -> None:
    while True:
        try:
            schedule_checks()
        except Exception:
            logger.exception("Schedule error")
        time.sleep(60)


@app.command("/activate-standup-dev")
def activate_command(ack, body, respond):
    ack()
    channel_id = body["channel_id"]
    user_id = body["user_id"]

    try:
        app.client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "standup_setup",
                "private_metadata": f'{channel_id}:{user_id}',
                "title": {"type": "plain_text", "text": "Set standup timezone"},
                "submit": {"type": "plain_text", "text": "Activate"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "timezone_block",
                        "label": {"type": "plain_text", "text": "Choose the timezone for this channel"},
                        "element": {
                            "type": "static_select",
                            "action_id": "timezone_select",
                            "placeholder": {"type": "plain_text", "text": "Select a timezone"},
                            "options": get_timezone_options(),
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "ping_group_block",
                        "label": {"type": "plain_text", "text": "Choose the ping group"},
                        "element": {
                            "type": "external_select",
                            "action_id": "ping_group_select",
                            "placeholder": {"type": "plain_text", "text": "Search ping groups"},
                            "min_query_length": 0,
                        },
                    },
                ],
            },
        )
    except SlackApiError:
        logger.exception("Failed to open activation modal")
        respond(text="I could not open the activation form. Check that the app has interactivity enabled and try again.", response_type="ephemeral")


@app.view("standup_setup")
def handle_setup_submission(ack, body, respond):
    ack()
    channel_id, user_id = body.get("view", {}).get("private_metadata", ":").split(":", 1)
    values = body["view"]["state"]["values"]
    timezone_value = normalize_timezone_value(values["timezone_block"]["timezone_select"]["selected_option"]["value"])
    ping_group_value = values["ping_group_block"]["ping_group_select"]["selected_option"]["value"]
    ping_group_id = parse_ping_group_id(ping_group_value)

    result = activate_standup(channel_id, user_id or body["user"]["id"], timezone_value, ping_group_id)
    if not result["ok"]:
        app.client.chat_postEphemeral(channel=channel_id, user=body["user"]["id"], text=result["text"])
        return

    app.client.chat_postMessage(channel=channel_id, text=result["text"])


@app.options("ping_group_select")
def load_ping_group_options(ack, body):
    try:
        options = fetch_ping_group_options(app.client, body.get("value", ""))
        ack(options=options)
    except SlackApiError:
        logger.exception("Failed to load ping group options")
        ack(options=[])


@app.command("/reset-standup-dev")
def reset_command(ack, body, respond):
    ack()
    channel_id = body["channel_id"]
    user_id = body["user_id"]

    if not is_channel_manager(app.client, channel_id, user_id):
        respond(text="Only channel managers can reset this standup bot.", response_type="ephemeral")
        return

    reset_channel_state(channel_id)
    respond(text="Standup bot reset for this channel. State has been cleared for debugging.", response_type="ephemeral")


@app.event("message")
def track_thread_replies(body, event, logger):
    if not event.get("thread_ts") or event.get("subtype"):
        return

    channel_id = event["channel"]
    state = get_channel_state(channel_id)
    if not state.active or not state.last_thread_ts:
        return

    if event["thread_ts"] == state.last_thread_ts and event.get("user"):
        if event["user"] not in state.last_thread_users:
            state.last_thread_users.append(event["user"])
            save_state()


@app.event("app_mention")
def remind_about_activation(event, say):
    if event.get("channel_type") == "im":
        return

    say("Use /activate-standup to enable standups in this channel. The modal will let you choose timezone and ping group.")


if __name__ == "__main__":
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not app_token:
        raise RuntimeError("SLACK_APP_TOKEN is required for Socket Mode")

    load_state()
    restore_standup_timers()

    threading.Thread(target=scheduler_loop, daemon=True).start()
    SocketModeHandler(app, app_token).start()
