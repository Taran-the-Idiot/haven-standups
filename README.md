# Haven Standups

A Slack bot that helps teams run daily standups.

## Features

- Adds the bot to any channel without activating it.
- A channel manager can enable it with a slash command.
- The activation modal collects the timezone and a Slack user group to ping.
- Once activated, the bot posts a standup prompt each morning at 08:00 in the channel timezone.
- It then sends reminder pings in the thread every two hours to anyone in the selected ping group who has not replied yet.
- Reminders continue until the next morning standup replaces the thread.

## Local setup

1. Install dependencies:
   - `python3 -m pip install -r requirements.txt`
2. Copy the environment example:
   - `cp .env.example .env`
3. Fill in your Slack credentials and a debug reset key.
4. Start the app:
   - `python3 app.py`
5. Run tests:
   - `python3 -m unittest discover -s tests`

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
- `/reset-standup <RESET_KEY>`

This keeps the bot dormant until explicitly enabled for a channel. The reset command clears the bot’s in-memory state for debugging and is protected by the `RESET_KEY` value in `.env`.
