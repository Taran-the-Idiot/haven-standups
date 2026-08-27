# Haven Standups

A Slack bot that helps teams run daily standups.

## Features

- Adds the bot to any channel without activating it.
- A channel manager can enable it with a slash command:
  - `/activate-standup America/New_York`
- Once activated, the bot posts a standup prompt each morning at 09:00 in the channel timezone.
- It then sends reminder pings in the thread every two hours to anyone who has not replied yet and is still a member of the channel.
- Reminders continue until the next morning standup replaces the thread.

## Local setup

1. Install dependencies:
   - `npm install`
2. Copy the environment example:
   - `cp .env.example .env`
3. Fill in your Slack credentials.
4. Start the app:
   - `npm start`
5. Run tests:
   - `npm test`

## Slack configuration

Create a new Slack app using Socket Mode and add the following scopes:

- `chat:write`
- `channels:read`
- `groups:read`
- `im:read`
- `mpim:read`
- `channels:history`
- `groups:history`
- `chat:write.public`
- `commands`

The app should be installed to each target channel, and the channel manager can then run:

- `/activate-standup America/New_York`

This keeps the bot dormant until explicitly enabled for a channel.
