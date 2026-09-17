// The reverse index is built from group rosters because the athlete record does
// not carry its groups. The case these tests guard hardest is the multi-group
// athlete — the model explicitly allows one, and anything that collapses it to
// a single group is wrong.

import { describe, expect, it } from "vitest";
import {
  FILTER_ALL, FILTER_UNASSIGNED, filterRoster, indexMembership, isMember, unassignedCount,
} from "./roster.js";

const varsity = { id: 1, name: "Varsity" };
const rehab = { id: 2, name: "Rehab" };
const groups = [varsity, rehab];

const jordan = { id: 10, name: "Jordan Lee" };
const alex = { id: 11, name: "Alex Kim" };
const taylor = { id: 12, name: "Taylor Fox" };
const athletes = [jordan, alex, taylor];

// Jordan is in both — the case the model exists to allow.
const membersByGroup = { 1: [jordan, alex], 2: [jordan] };
const index = indexMembership(groups, membersByGroup);

describe("indexMembership", () => {
  it("keeps every group an athlete belongs to, not just the first", () => {
    expect(index.get(jordan.id).map((g) => g.name)).toEqual(["Varsity", "Rehab"]);
  });

  it("leaves an athlete in no group out of the index entirely", () => {
    expect(index.has(taylor.id)).toBe(false);
  });

  it("survives missing rosters", () => {
    expect(indexMembership(groups, {}).size).toBe(0);
    expect(indexMembership(null, null).size).toBe(0);
  });
});

describe("isMember", () => {
  it("answers for each group independently", () => {
    expect(isMember(index, jordan.id, varsity.id)).toBe(true);
    expect(isMember(index, jordan.id, rehab.id)).toBe(true);
    expect(isMember(index, alex.id, rehab.id)).toBe(false);
    expect(isMember(index, taylor.id, varsity.id)).toBe(false);
  });
});

describe("filterRoster", () => {
  it("is alphabetical with no filter", () => {
    expect(filterRoster(athletes, index, FILTER_ALL).map((a) => a.name))
      .toEqual(["Alex Kim", "Jordan Lee", "Taylor Fox"]);
  });

  // ⚠️ Picking a group must NOT hide the non-members: you cannot add someone to
  // a group from a list that only shows people already in it, and Remove would
  // make the row vanish with no undo on the screen that caused it.
  it("keeps every athlete visible when a group is picked, members first", () => {
    expect(filterRoster(athletes, index, rehab.id).map((a) => a.name))
      .toEqual(["Jordan Lee", "Alex Kim", "Taylor Fox"]);
  });

  it("stays alphabetical inside each half", () => {
    expect(filterRoster(athletes, index, varsity.id).map((a) => a.name))
      .toEqual(["Alex Kim", "Jordan Lee", "Taylor Fox"]);
  });

  it("finds the athletes in no group at all", () => {
    expect(filterRoster(athletes, index, FILTER_UNASSIGNED).map((a) => a.name))
      .toEqual(["Taylor Fox"]);
  });

  it("does not mutate the list it was given", () => {
    const original = [taylor, jordan, alex];
    filterRoster(original, index, FILTER_ALL);
    expect(original.map((a) => a.name)).toEqual(["Taylor Fox", "Jordan Lee", "Alex Kim"]);
  });

  it("survives an empty roster", () => {
    expect(filterRoster([], index, FILTER_ALL)).toEqual([]);
    expect(filterRoster(null, index, varsity.id)).toEqual([]);
  });
});

describe("unassignedCount", () => {
  // An imported roster nobody assigned is invisible everywhere else in
  // PLANNING — no group, so no program, so nothing prescribed.
  it("counts the athletes who would otherwise be invisible", () => {
    expect(unassignedCount(athletes, index)).toBe(1);
  });

  it("is zero when everyone has a group", () => {
    expect(unassignedCount([jordan, alex], index)).toBe(0);
  });
});
