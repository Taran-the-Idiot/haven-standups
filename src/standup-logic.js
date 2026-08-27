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
  isChannelManagerUser
};
