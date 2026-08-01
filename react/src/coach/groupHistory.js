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

// "Behind" means TRENDING DOWN: at least 3 of an athlete's last 5 training days
// were slower than the day before.
//
// ⚠️ This replaced an attendance rule (a week without training). Attendance is
// already visible in the "Last trained" column, so flagging it there too said
// the same thing twice — and it missed the athlete a coach actually needs to
// catch: the one who turns up every session and gets slower every session.
// Three days out of five is a pattern rather than a bad night.
//
// Judged over ALL their history, not the selected window. Like "last trained",
// whether someone is declining is a fact about the athlete; if it moved with
// the dropdown the flag would describe the coach's filter instead of the lifter.
export const BEHIND_DOWN_DAYS = 3;
export const BEHIND_OF_LAST = 5;

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
  now = Date.now(), windowDays = 14,
  downDays = BEHIND_DOWN_DAYS, ofLast = BEHIND_OF_LAST,
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
    const inWindowDays = summariseTrainingDays(groupHistorySets(inWindow));
    const newest = inWindowDays[0] || null;

    // The behind test reads ALL history, not the window — see BEHIND_DOWN_DAYS.
    // Fewer than `ofLast` days is fine: three down out of three IS three down
    // out of the last five. Requiring a full five would let the athlete with
    // the shortest, steepest slide go unflagged.
    const recentDays = summariseTrainingDays(groupHistorySets(allSets)).slice(0, ofLast);
    const downCount = recentDays.filter((day) => day.trend === "down").length;

    return {
      athlete: member,
      lastTrained,
      lastTrainedLabel: lastTrainedLabel(lastTrained, now),
      sets: inWindow.length,
      avgVelocity,
      trend: newest?.trend ?? null,
      change: newest?.change ?? null,
      behind: downCount >= downDays,
      downCount,
      judgedOver: recentDays.length,
      // Nobody to judge. Kept separate from `behind` so an athlete with no
      // history is not quietly counted as fine — the column says which it is.
      noHistory: recentDays.length === 0,
      failed: payload === null || payload === undefined,
    };
  });

  // Behind first — the whole reason a coach opens this is to find them, and
  // making them scroll a squad of a hundred to spot a flag defeats the view.
  // Then the steepest slide first, then whoever has been away longest.
  return rows.sort((left, right) => {
    if (left.behind !== right.behind) return left.behind ? -1 : 1;
    if (left.downCount !== right.downCount) return right.downCount - left.downCount;
    return daysSince(right.lastTrained, now) - daysSince(left.lastTrained, now);
  });
}
