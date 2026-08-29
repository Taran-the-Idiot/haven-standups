require('dotenv').config();

const { App } = require('@slack/bolt');
const { DateTime } = require('luxon');
const {
  computeMissingUsers,
  buildReminderText,
  isRunnableWindow,
  nextStandupTime,
  isChannelManagerUser,
  getTimezoneOptions,
  normalizeTimezoneValue
} = require('./standup-logic');

const app = new App({
  token: process.env.SLACK_BOT_TOKEN,
  signingSecret: process.env.SLACK_SIGNING_SECRET,
  appToken: process.env.SLACK_APP_TOKEN,
  socketMode: true,
  port: Number(process.env.PORT || 3000)
});

const channels = new Map();
const standupTimers = new Map();

function getChannelState(channelId) {
  if (!channels.has(channelId)) {
    channels.set(channelId, {
      active: false,
      timezone: 'UTC',
      nextStandupAt: null,
      pingGroupId: null,
      pingGroupUsers: [],
      lastStandupTs: null,
      lastThreadTs: null,
      lastThreadUsers: []
    });
  }

  return channels.get(channelId);
}

function clearStandupTimer(channelId) {
  const existingTimer = standupTimers.get(channelId);
  if (existingTimer) {
    clearTimeout(existingTimer);
    standupTimers.delete(channelId);
  }
}

async function runStandupPost(channelId, source) {
  try {
    await sendStandupMessage(channelId);
  } catch (error) {
    console.error(`Failed to send standup for ${channelId} from ${source}:`, error);
  }
}

function normalizePingGroupId(value) {
  if (!value) {
    return '';
  }

  const trimmed = String(value).trim();
  const mentionMatch = trimmed.match(/^<!subteam\^([A-Z0-9]+)(?:\|[^>]+)?>$/i);
  if (mentionMatch) {
    return mentionMatch[1];
  }

  const directMatch = trimmed.match(/^([A-Z0-9]+)$/i);
  if (directMatch) {
    return directMatch[1];
  }

  return '';
}

async function fetchPingGroupUsers(pingGroupId) {
  const response = await app.client.usergroups.users.list({
    usergroup: pingGroupId
  });

  return response.users || [];
}

async function fetchPingGroupOptions() {
  const response = await app.client.usergroups.list();
  const usergroups = response.usergroups || [];

  return usergroups
    .filter((group) => !group.is_usergroup)
    .map((group) => ({
      text: {
        type: 'plain_text',
        text: group.handle || group.name
      },
      value: group.id
    }))
    .sort((left, right) => left.text.text.localeCompare(right.text.text));
}

function scheduleStandupTimer(channelId) {
  const state = getChannelState(channelId);

  clearStandupTimer(channelId);

  if (!state.active || !state.nextStandupAt) {
    return;
  }

  const now = DateTime.now().setZone(state.timezone);
  const delay = Math.max(0, Math.ceil(state.nextStandupAt.diff(now).as('milliseconds')));

  const timer = setTimeout(async () => {
    standupTimers.delete(channelId);

    const currentState = getChannelState(channelId);
    if (!currentState.active || !currentState.nextStandupAt) {
      return;
    }

    const currentNow = DateTime.now().setZone(currentState.timezone);
    if (currentNow.toMillis() >= currentState.nextStandupAt.toMillis()) {
      await runStandupPost(channelId, 'timer');
    }
  }, delay);

  standupTimers.set(channelId, timer);
}

async function sendStandupMessage(channelId) {
  const state = getChannelState(channelId);
  const now = DateTime.now().setZone(state.timezone);

  if (!state.pingGroupId) {
    throw new Error('Ping group is not configured for this channel');
  }

  try {
    state.pingGroupUsers = await fetchPingGroupUsers(state.pingGroupId);
  } catch (error) {
    console.error(`Failed to load ping group ${state.pingGroupId} for ${channelId}:`, error);
  }

  const pingText = `<!subteam^${state.pingGroupId}>`;
  const message = await app.client.chat.postMessage({
    channel: channelId,
    text: `Good morning ${pingText}!\n\n- What did you do yesterday?\n- What do you plan to do today?\n\n_If you did not do anything yesterday, still post an update so we know you are up to date._`
  });

  state.lastStandupTs = message.ts;
  state.lastThreadTs = message.ts;
  state.lastThreadUsers = [];

  if (state.pingGroupUsers.length) {
    state.lastThreadUsers = state.pingGroupUsers;
  }

  state.nextStandupAt = nextStandupTime(state.timezone, now);
  scheduleStandupTimer(channelId);

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

  const text = buildReminderText(missingUsers);
  if (text) {
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

function resetChannelState(channelId) {
  const state = getChannelState(channelId);
  state.active = false;
  state.timezone = 'UTC';
  state.nextStandupAt = null;
  state.pingGroupId = null;
  state.pingGroupUsers = [];
  state.lastStandupTs = null;
  state.lastThreadTs = null;
  state.lastThreadUsers = [];
  clearStandupTimer(channelId);
  return state;
}

function formatDurationUntilStandup(timezone) {
  const now = DateTime.now().setZone(timezone);
  const next = nextStandupTime(timezone, now);
  const totalMinutes = Math.max(0, Math.round(next.diff(now, 'minutes').minutes));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  return `${hours}h ${minutes}m`;
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

async function activateStandup(channelId, userId, timezone, pingGroupId) {
  const state = getChannelState(channelId);
  const canActivate = await isChannelManager(channelId, userId);

  if (!canActivate) {
    return {
      ok: false,
      text: 'Only channel managers can activate standups in this channel.'
    };
  }

  if (!pingGroupId) {
    return {
      ok: false,
      text: 'Please provide a valid ping group ID for this channel.'
    };
  }

  let pingGroupUsers = [];
  try {
    pingGroupUsers = await fetchPingGroupUsers(pingGroupId);
  } catch (error) {
    console.error(`Failed to validate ping group ${pingGroupId}:`, error);
    return {
      ok: false,
      text: 'That ping group could not be loaded. Check the user group ID and try again.'
    };
  }

  if (!pingGroupUsers.length) {
    return {
      ok: false,
      text: 'That ping group has no members to notify.'
    };
  }

  state.active = true;
  state.timezone = timezone;
  state.pingGroupId = pingGroupId;
  state.pingGroupUsers = pingGroupUsers;
  state.nextStandupAt = nextStandupTime(timezone, DateTime.now().setZone(timezone));
  state.lastStandupTs = null;
  state.lastThreadTs = null;
  state.lastThreadUsers = [];
  scheduleStandupTimer(channelId);

  console.log(`Standup activation for ${channelId} will send the first standup in ${formatDurationUntilStandup(timezone)}.`);

  return {
    ok: true,
    text: `Standup bot activated for this channel in ${timezone}. The next morning standup will be sent at 08:00 ${timezone}.`
  };
}

app.command('/activate-standup', async ({ command, ack, respond }) => {
  await ack();
  const channelId = command.channel_id;
  const userId = command.user_id;

  let pingGroupOptions = [];
  try {
    pingGroupOptions = await fetchPingGroupOptions();
  } catch (error) {
    console.error('Failed to load ping groups for activation modal:', error);
    await respond({
      text: 'I could not load ping groups right now. Check that the app has usergroups:read and try again.',
      response_type: 'ephemeral'
    });
    return;
  }

  if (!pingGroupOptions.length) {
    await respond({
      text: 'No ping groups were found for this workspace.',
      response_type: 'ephemeral'
    });
    return;
  }

  await app.client.views.open({
    trigger_id: command.trigger_id,
    view: {
      type: 'modal',
      callback_id: 'timezone_setup',
      private_metadata: JSON.stringify({ channelId, userId }),
      title: {
        type: 'plain_text',
        text: 'Set standup timezone'
      },
      submit: {
        type: 'plain_text',
        text: 'Activate'
      },
      close: {
        type: 'plain_text',
        text: 'Cancel'
      },
      blocks: [
        {
          type: 'input',
          block_id: 'timezone_block',
          label: {
            type: 'plain_text',
            text: 'Choose the timezone for this channel'
          },
          element: {
            type: 'static_select',
            action_id: 'timezone_select',
            placeholder: {
              type: 'plain_text',
              text: 'Select a timezone'
            },
            options: getTimezoneOptions()
          }
        },
        {
          type: 'input',
          block_id: 'ping_group_block',
          label: {
            type: 'plain_text',
            text: 'Choose the ping group'
          },
          element: {
            type: 'static_select',
            action_id: 'ping_group_select',
            placeholder: {
              type: 'plain_text',
              text: 'Select a ping group'
            },
            options: pingGroupOptions
          }
          }
      ]
    }
  });

  return;
});

app.command('/reset-standup', async ({ command, ack, respond }) => {
  await ack();

  const channelId = command.channel_id;
  const userId = command.user_id;

  const canReset = await isChannelManager(channelId, userId);
  if (!canReset) {
    await respond({
      text: 'Only channel managers can reset this standup bot.',
      response_type: 'ephemeral'
    });
    return;
  }

  resetChannelState(channelId);
  await respond({
    text: 'Standup bot reset for this channel. State has been cleared for debugging.',
    response_type: 'ephemeral'
  });
});

app.view('timezone_setup', async ({ ack, view, body }) => {
  await ack();

  const { channelId, userId } = JSON.parse(view.private_metadata || '{}');
  const timezone = normalizeTimezoneValue(view.state.values.timezone_block.timezone_select.selected_option?.value);
  const pingGroupValue = view.state.values.ping_group_block.ping_group_select.selected_option?.value;
  const pingGroupId = normalizePingGroupId(pingGroupValue);

  if (!channelId) {
    return;
  }

  const result = await activateStandup(channelId, userId || body.user.id, timezone, pingGroupId);
  if (!result.ok) {
    await app.client.chat.postEphemeral({
      channel: channelId,
      user: body.user.id,
      text: result.text
    });
    return;
  }

  await app.client.chat.postMessage({
    channel: channelId,
    text: result.text
  });
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

    if (!state.nextStandupAt) {
      continue;
    }

    const localNow = now.setZone(state.timezone);
    if (localNow.toMillis() >= state.nextStandupAt.toMillis()) {
      await runStandupPost(channelId, 'poll');
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
