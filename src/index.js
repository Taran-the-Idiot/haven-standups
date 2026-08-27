require('dotenv').config();

const { App } = require('@slack/bolt');
const { DateTime } = require('luxon');
const {
  computeMissingUsers,
  buildReminderText,
  isRunnableWindow,
  nextStandupTime,
  isChannelManagerUser
} = require('./standup-logic');

const app = new App({
  token: process.env.SLACK_BOT_TOKEN,
  signingSecret: process.env.SLACK_SIGNING_SECRET,
  appToken: process.env.SLACK_APP_TOKEN,
  socketMode: true,
  port: Number(process.env.PORT || 3000)
});

const channels = new Map();

function getChannelState(channelId) {
  if (!channels.has(channelId)) {
    channels.set(channelId, {
      active: false,
      timezone: 'UTC',
      lastStandupTs: null,
      lastThreadTs: null,
      lastThreadUsers: []
    });
  }

  return channels.get(channelId);
}

async function sendStandupMessage(channelId) {
  const state = getChannelState(channelId);
  const now = DateTime.now().setZone(state.timezone);

  const result = await app.client.conversations.members({
    channel: channelId,
    limit: 200
  });

  const members = result.members || [];
  const message = await app.client.chat.postMessage({
    channel: channelId,
    text: 'Good morning! Please post a standup update: what you did yesterday and what you plan to do today.'
  });

  state.lastStandupTs = message.ts;
  state.lastThreadTs = message.ts;
  state.lastThreadUsers = [];

  if (members.length) {
    state.lastThreadUsers = members;
  }

  const nextPing = nextStandupTime(state.timezone, now);
  console.log(`Standup scheduled for ${channelId} at ${nextPing.toISO()}`);
}

async function checkThreadReminders(channelId) {
  const state = getChannelState(channelId);
  if (!state.active || !state.lastThreadTs) {
    return;
  }

  const replies = await app.client.conversations.replies({
    channel: channelId,
    ts: state.lastThreadTs,
    limit: 200
  });

  const threadReplies = replies.messages || [];
  const members = state.lastThreadUsers.length ? state.lastThreadUsers : [];
  const participants = threadReplies
    .filter((message) => message.user && message.user !== 'USLACKBOT')
    .map((message) => message.user);

  const missingUsers = computeMissingUsers(members, participants);

  if (missingUsers.length > 0) {
    const text = buildReminderText(missingUsers);
    await app.client.chat.postMessage({
      channel: channelId,
      thread_ts: state.lastThreadTs,
      text
    });
  }
}

function getConfiguredManagerIds() {
  return (process.env.CHANNEL_MANAGER_USER_IDS || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

async function isChannelManager(channelId, userId) {
  try {
    const [channelInfo, userInfo] = await Promise.all([
      app.client.conversations.info({ channel: channelId }),
      app.client.users.info({ user: userId })
    ]);

    const channelCreatorId = channelInfo.channel?.creator;
    const user = userInfo.user || {};
    const configuredManagers = getConfiguredManagerIds();

    return isChannelManagerUser(user, channelCreatorId, configuredManagers);
  } catch (error) {
    console.error('Channel-manager check failed:', error);
    return false;
  }
}

app.command('/activate-standup', async ({ command, ack, respond }) => {
  await ack();
  const channelId = command.channel_id;
  const userId = command.user_id;
  const state = getChannelState(channelId);
  const timezone = command.text?.trim() || 'UTC';

  const canActivate = await isChannelManager(channelId, userId);
  if (!canActivate) {
    await respond({
      text: 'Only channel managers can activate standups in this channel.',
      response_type: 'ephemeral'
    });
    return;
  }

  state.active = true;
  state.timezone = timezone;

  await respond({
    text: `Standup bot activated for this channel in ${timezone}. The next morning standup will be sent at 08:00 ${timezone}.`
  });

  await sendStandupMessage(channelId);
});

app.event('app_mention', async ({ event, say }) => {
  if (event.channel_type === 'im') {
    return;
  }

  await say('Use /activate-standup <timezone> to enable standups in this channel. Example: /activate-standup America/New_York');
});

app.event('message', async ({ event }) => {
  if (!event.thread_ts || event.subtype) {
    return;
  }

  const channelId = event.channel;
  const state = getChannelState(channelId);
  if (!state.active || !state.lastThreadTs) {
    return;
  }

  if (event.thread_ts === state.lastThreadTs) {
    state.lastThreadUsers = [...new Set([...state.lastThreadUsers, event.user])];
  }
});

async function scheduleChecks() {
  const now = DateTime.now();

  for (const [channelId, state] of channels.entries()) {
    if (!state.active) continue;

    if (!state.lastStandupTs || !state.lastThreadTs) {
      continue;
    }

    const localNow = now.setZone(state.timezone);
    if (isRunnableWindow(localNow, state.timezone)) {
      const lastStandupTime = DateTime.fromSeconds(Number(state.lastStandupTs), { zone: state.timezone });
      if (lastStandupTime.day !== localNow.day) {
        await sendStandupMessage(channelId);
      }
    }

    const reminderTimes = [
      localNow.plus({ hours: 2 }),
      localNow.plus({ hours: 4 }),
      localNow.plus({ hours: 6 }),
      localNow.plus({ hours: 8 }),
      localNow.plus({ hours: 10 }),
      localNow.plus({ hours: 12 })
    ];

    const isReminderHour = reminderTimes.some((time) => time.hour === localNow.hour && time.minute === localNow.minute);
    if (isReminderHour) {
      await checkThreadReminders(channelId);
    }
  }
}

async function start() {
  await app.start(process.env.PORT || 3000);
  console.log('⚡️ Standup bot is running');

  setInterval(async () => {
    try {
      await scheduleChecks();
    } catch (error) {
      console.error('Schedule error:', error);
    }
  }, 60 * 1000);
}

start();
