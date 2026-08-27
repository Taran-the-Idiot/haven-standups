const test = require('node:test');
const assert = require('node:assert/strict');
const { DateTime } = require('luxon');
const {
  computeMissingUsers,
  nextStandupTime,
  isRunnableWindow,
  buildReminderText,
  isChannelManagerUser
} = require('../src/standup-logic');

test('computeMissingUsers keeps people who have not replied', () => {
  const members = ['U1', 'U2', 'U3', 'U4'];
  const replies = ['U1', 'U3'];

  assert.deepEqual(computeMissingUsers(members, replies), ['U2', 'U4']);
});

test('nextStandupTime picks the next local morning standup time in timezone', () => {
  const now = DateTime.fromISO('2026-08-27T14:00:00', { zone: 'UTC' });
  const next = nextStandupTime('America/New_York', now);

  assert.equal(next.zoneName, 'America/New_York');
  assert.equal(next.toFormat('yyyy-MM-dd HH:mm:ss'), '2026-08-28 08:00:00');
});

test('isRunnableWindow allows standup checks at the configured time', () => {
  const current = DateTime.fromISO('2026-08-28T08:00:00', { zone: 'America/New_York' });
  assert.equal(isRunnableWindow(current, 'America/New_York'), true);

  const late = DateTime.fromISO('2026-08-28T10:05:00', { zone: 'America/New_York' });
  assert.equal(isRunnableWindow(late, 'America/New_York'), false);
});

test('buildReminderText mentions everyone still missing', () => {
  const text = buildReminderText(['U1', 'U2']);

  assert.match(text, /<@U1>/);
  assert.match(text, /<@U2>/);
  assert.match(text, /missing/i);
});

test('isChannelManagerUser allows channel creators and owners', () => {
  assert.equal(isChannelManagerUser({ id: 'U123', is_admin: false }, 'U123'), true);
  assert.equal(isChannelManagerUser({ id: 'U456', is_owner: true }, 'U789'), true);
  assert.equal(isChannelManagerUser({ id: 'U456', is_admin: false }, 'U789'), false);
  assert.equal(isChannelManagerUser({ id: 'U777', is_admin: false }, 'U789', ['U777']), true);
});
