// roster.js — every athlete in the system, and which groups each one is in.
//
// The athlete record does NOT carry its groups. `AthleteSerializer` is
// id / name / nfc_tag_id / created_at / notes, and membership lives on the
// group side (`training-groups/{id}/athletes/`). So the reverse index — athlete
// → groups — has to be built here from one roster call per group.
//
// That is a handful of requests, not one per athlete: a department has a few
// groups and hundreds of lifters. It scales with the thing that stays small.
//
// ⚠️ AN ATHLETE CAN BE IN SEVERAL GROUPS. The model says so explicitly ("a team
// group, a position group, a rehab group"), so nothing here may assume one.
// Anything that reduces this to a single group name is wrong.

export const FILTER_ALL = "all";
export const FILTER_UNASSIGNED = "unassigned";

/**
 * athlete id → array of group objects they belong to.
 *
 * `membersByGroup` is { groupId: [athlete, ...] }, which is the shape the group
 * roster endpoint returns, one call per group.
 */
export function indexMembership(groups, membersByGroup) {
  const index = new Map();
  for (const group of groups || []) {
    for (const member of membersByGroup?.[group.id] || []) {
      if (!index.has(member.id)) index.set(member.id, []);
      index.get(member.id).push(group);
    }
  }
  return index;
}

/** Is this athlete in that group? */
export function isMember(index, athleteId, groupId) {
  return (index.get(athleteId) || []).some((group) => group.id === groupId);
}

/**
 * The roster for a given filter.
 *
 * ⚠️ PICKING A GROUP DOES NOT HIDE THE NON-MEMBERS, and that is the whole point.
 * It sorts them — members first — and scopes the add/remove column to that
 * group. An earlier version filtered them out, which made the screen unable to
 * do the job it exists for: you cannot add someone to a group from a list that
 * only shows people already in it. Worse, pressing Remove made the row vanish,
 * so an accidental removal had no undo on the screen that caused it.
 *
 * FILTER_UNASSIGNED still narrows hard — that one is a diagnostic ("who is
 * stranded"), not a workspace.
 *
 * Alphabetical within each half. A coach looking for one person scans by name,
 * and an order that shuffles on every click makes that impossible.
 */
export function filterRoster(athletes, index, filter) {
  const byName = (a, b) => String(a.name).localeCompare(String(b.name));
  const rows = [...(athletes || [])].sort(byName);
  if (filter === FILTER_ALL || filter === undefined || filter === null) return rows;
  if (filter === FILTER_UNASSIGNED) {
    return rows.filter((athlete) => (index.get(athlete.id) || []).length === 0);
  }
  const members = rows.filter((athlete) => isMember(index, athlete.id, filter));
  const others = rows.filter((athlete) => !isMember(index, athlete.id, filter));
  return [...members, ...others];
}

/**
 * Athletes in no group at all.
 *
 * Worth counting on its own: an imported roster that never got assigned is
 * invisible everywhere else in PLANNING — they have no group, so no program, so
 * no calendar, so nothing prescribed. They are the quietest failure in the
 * system and the one a coach most needs pointed out.
 */
export function unassignedCount(athletes, index) {
  return (athletes || []).filter((athlete) => (index.get(athlete.id) || []).length === 0).length;
}
