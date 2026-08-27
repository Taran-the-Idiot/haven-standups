const { DateTime } = require('luxon');

function computeMissingUsers(members, replies) {
  const replySet = new Set(replies || []);
  return (members || []).filter((member) => !replySet.has(member));
}

function nextStandupTime(timezone, now = DateTime.now().setZone(timezone)) {
  const current = now.setZone(timezone);
  const candidate = current.set({ hour: 8, minute: 0, second: 0, millisecond: 0 });

  if (candidate > current) {
    return candidate;
  }

  return candidate.plus({ days: 1 });
}

function isRunnableWindow(currentTime, timezone) {
  const now = currentTime.setZone(timezone);
  return now.hour === 8 && now.minute === 0 && now.second === 0;
}

function buildReminderText(missingUsers) {
  const userList = (missingUsers || []).map((user) => `<@${user}>`).join(' ');
  return `Standup reminder: ${userList || 'No one'} is still missing a reply in this thread. Please post an update of what you did yesterday and what you plan to do today.`;
}

function getGmtOffsetOptions() {
  const offsets = [-12, -11, -10, -9, -8, -7, -6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14];

  return offsets.map((offset) => {
    const sign = offset >= 0 ? '+' : '-';
    const label = offset === 0 ? 'GMT+0' : `GMT${sign}${Math.abs(offset)}`;
    const zone = offset === 0 ? 'UTC' : offset < 0 ? `Etc/GMT+${Math.abs(offset)}` : `Etc/GMT-${offset}`;

    return {
      label,
      value: zone
    };
  });
}

function getTimezoneOptions() {
  return getGmtOffsetOptions().map(({ label, value }) => ({
    text: {
      type: 'plain_text',
      text: label
    },
    value
  }));
}

function normalizeTimezoneValue(value) {
  if (!value) return 'UTC';

  const trimmed = String(value).trim();
  if (trimmed === 'UTC') return 'UTC';

  const match = trimmed.match(/^GMT([+-])(\d{1,2})(?::?(\d{2}))?$/i);
  if (!match) {
    return trimmed;
  }

  const sign = match[1] === '-' ? -1 : 1;
  const hours = Number(match[2]);
  const offset = sign * hours;

  if (offset === 0) {
    return 'UTC';
  }

  return offset < 0 ? `Etc/GMT+${Math.abs(offset)}` : `Etc/GMT-${offset}`;
}

function isChannelManagerUser(user, channelCreatorId, allowedManagerIds = []) {
  if (!user) return false;

  const normalizedAllowedIds = new Set((allowedManagerIds || []).map(String));
  const userId = user.id ? String(user.id) : null;

  const isCreator = Boolean(channelCreatorId && userId && userId === String(channelCreatorId));
  const isWorkspaceManager = Boolean(
    user.is_admin || user.is_owner || user.is_primary_owner
  );
  const isConfiguredManager = Boolean(userId && normalizedAllowedIds.has(userId));

  return isCreator || isWorkspaceManager || isConfiguredManager;
}

module.exports = {
  computeMissingUsers,
  nextStandupTime,
  isRunnableWindow,
  buildReminderText,
  getTimezoneOptions,
  normalizeTimezoneValue,
  isChannelManagerUser
};
