// schedule.js — reading the training calendar.
//
// A SLOT is a plan: "this program's Day 1, on the 5th". It is not a session. The
// session appears when a coach sets that day up, and even then it is not running
// until someone starts it. So a slot has four states a coach cares about, and the
// whole screen is really about showing which one each day is in:
//
//   planned    no session yet — the ordinary state of a future day
//   ready      the session exists, roster and plan attached, NOT started
//   running    started, holding the racks
//   done       ended, its report frozen
//
// "ready" is the state P14 exists to make possible: set Thursday up on Tuesday.

export const SLOT_STATES = ["planned", "ready", "running", "done"];

export function slotState(slot) {
  if (!slot?.session) return "planned";
  if (slot.session_ended_at) return "done";
  if (slot.session_started_at) return "running";
  return "ready";
}

// What a coach can do next, given the state. Returned as a name rather than a
// label so the component owns the wording and this stays testable.
//
// ⚠️ "ready" USED TO RETURN "start", AND THE CALENDAR STARTED THE DAY ITSELF.
// It no longer does. Staging is a PLANNING act and starting is a SESSION act
// (spec §2b), and having two screens that could both open the room meant two
// places to open the wrong day — the exact shape of the D18 bug, where a stray
// second session silently captured everyone's check-ins.
//
// So the calendar now hands the coach to SESSION and SESSION starts it. The
// calendar's job is answering "what is Monday?", not opening the room.
export function slotAction(slot) {
  switch (slotState(slot)) {
    case "planned": return "create";
    case "ready": return "open";   // → SESSION, which is where a day is started
    default: return null;          // running and done are not started again
  }
}

// Slots come back flat and date-ordered; a calendar reads better grouped by day.
// Several programs can train on one date — the one-slot-per-day constraint is per
// PROGRAM — so a date can legitimately hold more than one row.
export function groupSlotsByDate(slots) {
  const days = new Map();
  for (const slot of slots || []) {
    if (!days.has(slot.date)) days.set(slot.date, { date: slot.date, slots: [] });
    days.get(slot.date).slots.push(slot);
  }
  return [...days.values()];
}

// A date a coach can read at a glance, with today and tomorrow called out —
// those are the two rows they are actually looking for.
export function scheduleDayLabel(isoDate, today = new Date()) {
  // Parsed as a LOCAL date, not UTC. `new Date("2026-08-05")` is midnight UTC,
  // which is the previous evening in the Americas — the calendar would show every
  // day one early. Splitting the parts avoids that entirely.
  const [year, month, day] = String(isoDate).split("-").map(Number);
  if (!year || !month || !day) return String(isoDate);
  const date = new Date(year, month - 1, day);

  const midnight = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const dayDiff = Math.round((date - midnight) / 86400000);

  const full = date.toLocaleDateString([], {
    weekday: "long", month: "long", day: "numeric",
  });
  if (dayDiff === 0) return `Today · ${full}`;
  if (dayDiff === 1) return `Tomorrow · ${full}`;
  if (dayDiff === -1) return `Yesterday · ${full}`;
  return full;
}

// "Mon 3" — the compact date on a calendar CARD.
//
// The card view is scanned, not read: a coach is looking at a month of them at
// once, asking "what shape is this month?". A full "Monday, August 3" in that
// grid is four times the ink for the same fact, and the month is already in the
// heading above the cards.
//
// Same local-date parsing as scheduleDayLabel, and for the same reason —
// `new Date("2026-08-05")` is midnight UTC, which is the previous evening in
// the Americas, so every card would show the wrong day.
export function slotCardDate(isoDate) {
  const [year, month, day] = String(isoDate).split("-").map(Number);
  if (!year || !month || !day) return String(isoDate);
  const date = new Date(year, month - 1, day);
  // Composed by hand rather than asking toLocaleDateString for both parts at
  // once: given {weekday, day} it decides the ORDER by locale and returned
  // "5 Wed" here. The weekday name still comes from the locale — that part
  // should translate; the layout should not.
  return `${date.toLocaleDateString([], { weekday: "short" })} ${date.getDate()}`;
}

// The month a run of slots belongs to, for the heading above the card grid —
// "August 2026", or "August – October 2026" when the window spans several.
// Reads the FIRST and LAST slot rather than every one; they arrive date-ordered.
export function slotMonthRange(slots) {
  const dates = (slots || []).map((slot) => slot.date).filter(Boolean).sort();
  if (dates.length === 0) return "";
  const parse = (iso) => {
    const [year, month, day] = String(iso).split("-").map(Number);
    return year ? new Date(year, month - 1, day) : null;
  };
  const first = parse(dates[0]);
  const last = parse(dates[dates.length - 1]);
  if (!first || !last) return "";
  const label = (date, withYear) =>
    date.toLocaleDateString([], withYear ? { month: "long", year: "numeric" } : { month: "long" });
  if (first.getFullYear() === last.getFullYear() && first.getMonth() === last.getMonth()) {
    return label(first, true);
  }
  // Same year: name the year once, at the end.
  if (first.getFullYear() === last.getFullYear()) return `${label(first, false)} – ${label(last, true)}`;
  return `${label(first, true)} – ${label(last, true)}`;
}

export function isPastDate(isoDate, today = new Date()) {
  const [year, month, day] = String(isoDate).split("-").map(Number);
  if (!year) return false;
  const midnight = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return new Date(year, month - 1, day) < midnight;
}

// The window the calendar asks for. Defaults to a fortnight back and eight weeks
// on: far enough back to see the week just trained, far enough forward to cover a
// typical block, and bounded so a screen never pulls every slot ever deployed.
export function scheduleWindow(today = new Date(), { back = 14, forward = 56 } = {}) {
  const iso = (date) => {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  };
  const shift = (days) => {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    date.setDate(date.getDate() + days);
    return date;
  };
  return { from: iso(shift(-back)), to: iso(shift(forward)) };
}

export function scheduleUrl({ from, to }, programId) {
  const params = new URLSearchParams({ from, to });
  if (programId) params.set("training_program", String(programId));
  return `/api/scheduled-sessions/?${params.toString()}`;
}

// The dates a slot may be moved to, as options. Built rather than free-typed for
// the same reason the end-time picker is: an impossible or already-taken date
// should be unreachable, not merely rejected. Dates this program already trains
// on are excluded, because the server refuses them (one slot per program per day).
export function moveDateChoices(slot, allSlots, { back = 7, forward = 21 } = {}) {
  const taken = new Set((allSlots || [])
    .filter((row) => row.training_program === slot.training_program && row.id !== slot.id)
    .map((row) => row.date));

  const [year, month, day] = String(slot.date).split("-").map(Number);
  if (!year) return [];
  const anchor = new Date(year, month - 1, day);
  const pad = (n) => String(n).padStart(2, "0");

  const choices = [];
  for (let offset = -back; offset <= forward; offset += 1) {
    const date = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() + offset);
    const iso = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
    if (taken.has(iso)) continue;
    choices.push({ value: iso, label: scheduleDayLabel(iso, anchor), current: offset === 0 });
  }
  return choices;
}
