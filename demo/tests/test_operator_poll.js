"use strict";
const assert = require("assert");
const { createPoller, UNVERIFIED, INTERVAL_MS, TIMEOUT_MS } = require("../web/operator-status.js");

assert.ok(TIMEOUT_MS > INTERVAL_MS);

const poller = createPoller();
const first = poller.startRefresh();
assert.strictEqual(poller.startRefresh(), null, "a second refresh must not overlap the first");
assert.strictEqual(poller.finishRefresh(first, true), "apply", "a response slower than the interval still applies");

const beforeClick = poller.startRefresh();
poller.beginListen();
assert.strictEqual(poller.finishRefresh(beforeClick, true), "ignore", "a response from before the click must not apply");
assert.strictEqual(poller.startRefresh(), null, "no status poll while the click is in flight");
poller.endListen();

const afterClick = poller.startRefresh();
assert.ok(afterClick);
assert.strictEqual(poller.finishRefresh(afterClick, true), "apply");

const hung = poller.startRefresh();
assert.strictEqual(poller.finishRefresh(hung, false), "unverified");
assert.ok(!UNVERIFIED.headline.includes("Not receiving"));
assert.ok(UNVERIFIED.headline.includes("unavailable"));
assert.ok(UNVERIFIED.queue.includes("unavailable"));
assert.ok(UNVERIFIED.note.includes("not checked again"));

const recovered = poller.startRefresh();
assert.ok(recovered, "a failed refresh must not starve the next one");
assert.strictEqual(poller.finishRefresh(recovered, true), "apply");

const slow = [];
const paced = createPoller();
for (let i = 0; i < 4; i += 1) {
  const ticket = paced.startRefresh();
  if (ticket) slow.push(ticket);
}
assert.strictEqual(slow.length, 1, "ticks during an open refresh must not replace it");
assert.strictEqual(paced.finishRefresh(slow[0], true), "apply");

console.log("operator poll scheduler ok");
