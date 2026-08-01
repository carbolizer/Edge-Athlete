// sessionTiming.js — how long has this training day been running?
//
// Pure arithmetic on two timestamps, kept away from the component so it can be
// tested without mounting anything and without waiting for real seconds to pass.
//
// ⚠️ THIS NEEDS NO BACKEND CHANGE, and that was worth checking. The elapsed time
// looks like something the server should send, but a number sent from the server
// is stale the instant it arrives. What the server sends is the START time —
// `services/room_state.py:369` already returns `session.started_at`
// unconditionally — and the browser counts up from it. Same pattern the rack
// screen already uses for its own per-second timers.
//
// A consequence worth knowing: this trusts the TABLET's clock to roughly agree
// with the base station's. A tablet whose clock is an hour out shows an elapsed
// time an hour out. That is a cosmetic wrong number on one device rather than
// wrong data — nothing here is ever saved.

/** Milliseconds a day has been running, or null if it has not started. */
export function elapsedMs(startedAt, now = Date.now()) {
  if (!startedAt) return null;
  const started = new Date(startedAt).getTime();
  if (Number.isNaN(started)) return null;
  // A tablet clock behind the base station's would otherwise count backwards.
  // Zero is the honest floor: the day has started, it has just not been long.
  return Math.max(0, now - started);
}

/**
 * "01:24:36" — hours:minutes:seconds, zero-padded, hours NOT wrapped at 24.
 *
 * A day open for 26 hours reads "26:10:04" rather than "02:10:04". That case is
 * real and it matters: a base station that lost power comes back with yesterday
 * still open, and a timer that quietly wrapped would say the day was two hours
 * old when it is a day and two hours old. The banner elsewhere says the day is
 * stale; the timer must not contradict it.
 */
export function elapsedLabel(startedAt, now = Date.now()) {
  const ms = elapsedMs(startedAt, now);
  if (ms === null) return "--:--:--";
  const total = Math.floor(ms / 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(Math.floor(total / 3600))}:${pad(Math.floor(total / 60) % 60)}:${pad(total % 60)}`;
}
