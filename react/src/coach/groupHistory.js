// groupHistory.js — "who in this group is falling behind?"
//
// The per-athlete history answers "what is Jordan doing". At a hundred athletes
// that is the wrong question — a coach cannot ask it ninety-nine more times.
// This turns the same data sideways: one row per group member, so the person
// who has stopped showing up is visible without anyone going looking.
//
// ⚠️ THIS IS THE ONE VIEW IN THE REDESIGN THAT IS NOT FREE. There is no
// group-scoped analytics route, so it costs 1 + N requests: the group roster,
// then one `/api/analytics/athlete/{id}/` per member. Fine for a squad of four,
// noticeably slow at twenty-eight — which is exactly the size that makes the
// view worth having. A `?group=` parameter would make it one request, but that
// is a backend change and the spec (Phase H) says to prove the view earns it
// first. This file is the proof; the decision comes after.

import { groupHistorySets, summariseTrainingDays } from "../historyView.js";

export const WINDOW_CHOICES = [
  { days: 14, label: "Last 14 days" },
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
];

// "Behind" means a week without training, NOT "no training in the window".
//
// The spec's wording was "has not trained in the window", but read literally
// that flags nobody when the window is short and everybody when it is long —
// the flag would say more about the dropdown than about the athlete. A fixed
// week is a fact about the person: a lifter who has not trained in seven days
// has missed roughly a full rotation, whatever range the coach is looking at.
export const BEHIND_AFTER_DAYS = 7;

const DAY_MS = 86400000;

/** "Today", "Yesterday", "11 days ago", or "Never" — how a coach says it. */
export function lastTrainedLabel(lastTrained, now = Date.now()) {
  if (!lastTrained) return "Never";
  const then = new Date(lastTrained).getTime();
  if (Number.isNaN(then)) return "Never";
  // Compare CALENDAR days, not elapsed hours. A set finished at 9pm and read at
  // 8am the next morning is "Yesterday", not "11 hours ago" and not "Today".
  const startOfDay = (ms) => { const d = new Date(ms); d.setHours(0, 0, 0, 0); return d.getTime(); };
  const days = Math.round((startOfDay(now) - startOfDay(then)) / DAY_MS);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return `${days} days ago`;
}

export function daysSince(lastTrained, now = Date.now()) {
  if (!lastTrained) return Infinity;
  const then = new Date(lastTrained).getTime();
  if (Number.isNaN(then)) return Infinity;
  return Math.max(0, (now - then) / DAY_MS);
}

/**
 * One row per group member.
 *
 * `analytics` is a map of athlete id → that athlete's analytics payload (or
 * null if the request failed). A member whose call failed still gets a row —
 * dropping them would quietly shrink the roster, and a missing athlete is the
 * one thing this view exists to make visible.
 */
export function buildGroupRows(members, analytics, {
  now = Date.now(), windowDays = 14, behindAfterDays = BEHIND_AFTER_DAYS,
} = {}) {
  const cutoff = now - windowDays * DAY_MS;

  const rows = (members || []).map((member) => {
    const payload = analytics?.[member.id];
    const allSets = payload?.sets || [];
    const inWindow = allSets.filter((s) => s.ended_at && new Date(s.ended_at).getTime() >= cutoff);

    const endedTimes = allSets.map((s) => s.ended_at).filter(Boolean);
    const lastTrained = endedTimes.length
      ? endedTimes.reduce((latest, t) => (new Date(t) > new Date(latest) ? t : latest))
      : null;

    const velocities = inWindow.map((s) => s.avg_velocity).filter((v) => v !== null && v !== undefined);
    const avgVelocity = velocities.length
      ? velocities.reduce((total, v) => total + v, 0) / velocities.length
      : null;

    // Trend uses the SAME day-summary the per-athlete table uses, so the two
    // screens can never disagree about which way someone is going.
    const summaries = summariseTrainingDays(groupHistorySets(inWindow));
    const newest = summaries[0] || null;

    return {
      athlete: member,
      lastTrained,
      lastTrainedLabel: lastTrainedLabel(lastTrained, now),
      sets: inWindow.length,
      avgVelocity,
      trend: newest?.trend ?? null,
      change: newest?.change ?? null,
      behind: daysSince(lastTrained, now) >= behindAfterDays,
      failed: payload === null || payload === undefined,
    };
  });

  // Behind first. The whole reason a coach opens this is to find them, and
  // making them scroll a squad of a hundred to spot a flag defeats the view.
  // Within each half, least recent first — the same question, one level down.
  return rows.sort((left, right) => {
    if (left.behind !== right.behind) return left.behind ? -1 : 1;
    return daysSince(right.lastTrained, now) - daysSince(left.lastTrained, now);
  });
}
