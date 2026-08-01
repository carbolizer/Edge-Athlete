// historyRange.js — the stretch of time ANALYTICS → History is looking at.
//
// ⚠️ THE RANGE IS THE MODEL, NOT THE PRESET. "Last 14 days" is stored as the two
// dates it resolves to, never as the number 14. That matters for one reason: a
// coach picking their own start and end has to produce the same shape as a
// preset, or every reader downstream needs two code paths. Presets are just
// buttons that fill the range in.
//
// Dates are LOCAL calendar days as `YYYY-MM-DD`, inclusive at both ends. Not
// timestamps — a coach asking for "the 3rd to the 18th" means whole days, and
// the moment this carried a time-of-day, "today" would start excluding sets
// finished later this afternoon.

export const RANGE_PRESETS = [
  { days: 14, label: "Last 14 days" },
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
];

export const DEFAULT_PRESET_DAYS = 14;

/** `YYYY-MM-DD` for a Date, in local time rather than UTC. */
export function isoDay(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** The last `days` days, ending today. Inclusive, so 14 days covers 14 days. */
export function presetRange(days, now = new Date()) {
  const to = new Date(now);
  const from = new Date(now);
  from.setDate(from.getDate() - (days - 1));
  return { from: isoDay(from), to: isoDay(to) };
}

/** Does this range match a preset, so the button can show as selected? */
export function matchesPreset(range, days, now = new Date()) {
  const preset = presetRange(days, now);
  return Boolean(range) && range.from === preset.from && range.to === preset.to;
}

/**
 * Is this timestamp inside the range?
 *
 * Compares CALENDAR DAYS, which is why the ISO string is sliced rather than
 * parsed. `new Date("2026-08-03")` is midnight UTC — the previous evening in
 * the Americas — so a set finished at 8pm on the last day of the range would
 * fall outside it. Slicing the local day out of the timestamp avoids the whole
 * class of bug (the same one `schedule.js` documents).
 */
export function rangeContains(range, timestamp) {
  if (!range || !timestamp) return false;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return false;
  const day = isoDay(date);
  return day >= range.from && day <= range.to;
}

/** How many whole days the range covers, both ends included. */
export function rangeDays(range) {
  if (!range?.from || !range?.to) return 0;
  const parse = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
  return Math.round((parse(range.to) - parse(range.from)) / 86400000) + 1;
}

/** "Last 14 days" when it is one, otherwise "3 Jul – 18 Jul". */
export function rangeLabel(range, now = new Date()) {
  if (!range?.from || !range?.to) return "All time";
  const preset = RANGE_PRESETS.find((choice) => matchesPreset(range, choice.days, now));
  if (preset) return preset.label;
  const show = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString([], { day: "numeric", month: "short" });
  };
  return `${show(range.from)} – ${show(range.to)}`;
}

/**
 * A range with its ends the right way round.
 *
 * Two date inputs let a coach pick an end before the start, and every reader
 * downstream would then quietly show nothing. Swapping is friendlier than an
 * error for something with one obvious correct reading.
 */
export function normaliseRange(from, to) {
  if (!from || !to) return null;
  return from <= to ? { from, to } : { from: to, to: from };
}
