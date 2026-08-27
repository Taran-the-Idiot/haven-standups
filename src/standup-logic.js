const { DateTime } = require('luxon');

function computeMissingUsers(members, replies) {
  const replySet = new Set(replies || []);
  return (members || []).filter((member) => !replySet.has(member));
}

function nextStandupTime(timezone, now = DateTime.now().setZone(timezone)) {
  const current = now.setZone(timezone);
  const candidate = current.set({ hour: 9, minute: 0, second: 0, millisecond: 0 });

  if (candidate > current) {
    return candidate;
  }

  return candidate.plus({ days: 1 });
}

function isRunnableWindow(currentTime, timezone) {
  const now = currentTime.setZone(timezone);
  return now.hour === 9 && now.minute === 0 && now.second === 0;
}

function buildReminderText(missingUsers) {
  const userList = (missingUsers || []).map((user) => `<@${user}>`).join(' ');
  return `Standup reminder: ${userList || 'No one'} is still missing a reply in this thread. Please post an update of what you did yesterday and what you plan to do today.`;
}

module.exports = {
  computeMissingUsers,
  nextStandupTime,
  isRunnableWindow,
  buildReminderText
};
