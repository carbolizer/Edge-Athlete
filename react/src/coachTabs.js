// coachTabs.js — the coach workspace's tab row, split into two groups.
//
// The coach page used to show eight flat tabs, mixing room-level views
// (room, workouts, schedule, reports) with per-athlete ones (athlete, history,
// programs, notes). A per-athlete view needs an athlete selected first; a
// room-level one never does. Splitting them makes that dependency visible, so
// the thing a coach came for is the thing they reach first.

export const ROOM_TABS = ["room", "workouts", "schedule", "reports"];
export const ATHLETE_TABS = ["athlete", "history", "programs", "notes"];
export const ALL_TABS = [...ROOM_TABS, ...ATHLETE_TABS];

// Room-level tabs are always reachable. A per-athlete tab is only meaningful
// once an athlete is chosen — otherwise it is dimmed with a prompt to pick one.
export function tabDisabled(tab, selectedAthleteId) {
  return ATHLETE_TABS.includes(tab) && !selectedAthleteId;
}

export function tabGroup(tab) {
  if (ROOM_TABS.includes(tab)) return "room";
  if (ATHLETE_TABS.includes(tab)) return "athlete";
  return "room";
}
