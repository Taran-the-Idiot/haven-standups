# Haven Standups

A Slack bot that helps teams run daily standups.

## Features

- Adds the bot to any channel without activating it.
- A channel manager can enable it with a slash command.
- The activation modal collects the timezone, how often standups are sent, how often the bot reminds people, and a Slack user group to ping.
- Standups can go out every day (default, recommended), every other day, or once a week, always at 08:00 in the channel timezone.
- It then sends reminder pings in the thread to anyone in the selected ping group who has not replied yet. The interval is configurable from 1 to 12 hours; two hours is the default and what we recommend.
- Reminders stop once everyone has replied, when the next standup replaces the thread, or 24 hours after the standup was posted - whichever comes first.
- Channels configured before these settings existed keep working: any setting missing from `standup_state.json` falls back to its default.

## Local setup

1. Create and activate a virtualenv (keeps deps off the system Python):
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2. Install dependencies:
   - `python -m pip install -r requirements.txt`
3. Copy the environment example:
   - `cp .env.example .env`
4. Fill in your Slack credentials and a debug reset key.
5. Start the app (must be the venv's Python, or you get `ModuleNotFoundError`):
   - `python app.py`  (or `.venv/bin/python app.py` without activating)
6. Run tests:
   - `PYTHONPATH=. python -m unittest tests.test_standup_logic`

## Slack configuration

Create a new Slack app using Socket Mode and add the following scopes:

- `chat:write`
- `channels:read`
- `groups:read`
- `im:read`
- `mpim:read`
- `channels:history`
- `groups:history`
- `usergroups:read`
- `users:read`
- `chat:write.public`
- `commands`

The app should be installed to each target channel, and the channel manager can then run:

- `/activate-standup`
- `/reset-standup`

This keeps the bot dormant until explicitly enabled for a channel. The reset command clears the bot’s in-memory state for debugging and is protected by the `RESET_KEY` value in `.env`.
