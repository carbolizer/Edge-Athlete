import { describe, expect, it } from "vitest";
import { groupSlotsByDate, isPastDate, moveDateChoices, scheduleDayLabel,
         scheduleUrl, scheduleWindow, slotAction, slotState } from "./schedule.js";

const planned = { id: 1, date: "2026-08-05", training_program: 3, session: null,
                  session_started_at: null, session_ended_at: null };
const ready = { ...planned, id: 2, session: 40, session_started_at: null, session_ended_at: null };
const running = { ...planned, id: 3, session: 41, session_started_at: "2026-08-05T14:00:00Z", session_ended_at: null };
const done = { ...planned, id: 4, session: 42, session_started_at: "2026-08-05T14:00:00Z",
               session_ended_at: "2026-08-05T16:00:00Z" };

describe("slotState", () => {
  // The four states are the whole screen. "ready" is the one P14 exists to make
  // possible: a day set up ahead of time that is deliberately NOT running.
  it("reads each stage of a slot's life", () => {
    expect(slotState(planned)).toBe("planned");
    expect(slotState(ready)).toBe("ready");
    expect(slotState(running)).toBe("running");
    expect(slotState(done)).toBe("done");
  });

  it("treats a missing slot as planned rather than throwing", () => {
    expect(slotState(undefined)).toBe("planned");
    expect(slotState({})).toBe("planned");
  });

  // An ended session that somehow lacks a start time is still finished. Reading
  // it as "running" would put a stale day on the racks in the UI's eyes.
  it("prefers ended over started when both are set", () => {
    expect(slotState({ session: 9, session_started_at: null, session_ended_at: "x" })).toBe("done");
  });
});

describe("slotAction", () => {
  it("offers exactly one next step, and none once the day has run", () => {
    expect(slotAction(planned)).toBe("create");
    expect(slotAction(ready)).toBe("start");
    expect(slotAction(running)).toBeNull();
    expect(slotAction(done)).toBeNull();
  });
});

describe("groupSlotsByDate", () => {
  it("groups slots under their date, preserving order", () => {
    const days = groupSlotsByDate([
      { id: 1, date: "2026-08-03" },
      { id: 2, date: "2026-08-05" },
      { id: 3, date: "2026-08-05" },
    ]);
    expect(days.map((day) => day.date)).toEqual(["2026-08-03", "2026-08-05"]);
    expect(days[1].slots).toHaveLength(2);
  });

  // One slot per day is per PROGRAM, so two groups training Monday is normal.
  it("keeps several programs on one date together", () => {
    const days = groupSlotsByDate([
      { id: 1, date: "2026-08-03", training_program: 1 },
      { id: 2, date: "2026-08-03", training_program: 2 },
    ]);
    expect(days).toHaveLength(1);
    expect(days[0].slots).toHaveLength(2);
  });

  it("handles no slots at all", () => {
    expect(groupSlotsByDate([])).toEqual([]);
    expect(groupSlotsByDate(undefined)).toEqual([]);
  });
});

describe("scheduleDayLabel", () => {
  const today = new Date(2026, 7, 5);   // 5 Aug 2026, local

  it("calls out the rows a coach is actually looking for", () => {
    expect(scheduleDayLabel("2026-08-05", today)).toContain("Today");
    expect(scheduleDayLabel("2026-08-06", today)).toContain("Tomorrow");
    expect(scheduleDayLabel("2026-08-04", today)).toContain("Yesterday");
  });

  it("names the weekday for anything further out", () => {
    const label = scheduleDayLabel("2026-08-12", today);
    expect(label).toContain("Wednesday");
    expect(label).not.toContain("Today");
  });

  // ⚠️ The bug this exists to prevent: `new Date("2026-08-05")` is midnight UTC,
  // which is the evening of the 4th in the Americas — every date would render one
  // day early. Parsing the parts keeps it local.
  it("does not shift the date by a timezone", () => {
    expect(scheduleDayLabel("2026-08-05", today)).toContain("August 5");
  });

  it("passes through something unparseable rather than showing Invalid Date", () => {
    expect(scheduleDayLabel("not-a-date", today)).toBe("not-a-date");
  });
});

describe("isPastDate", () => {
  const today = new Date(2026, 7, 5);

  it("counts today as not past, so the current day stays visible", () => {
    expect(isPastDate("2026-08-05", today)).toBe(false);
    expect(isPastDate("2026-08-04", today)).toBe(true);
    expect(isPastDate("2026-08-06", today)).toBe(false);
  });
});

describe("scheduleWindow", () => {
  const today = new Date(2026, 7, 5);

  it("looks a fortnight back and eight weeks on", () => {
    expect(scheduleWindow(today)).toEqual({ from: "2026-07-22", to: "2026-09-30" });
  });

  it("pads the month and day, so the server can parse it", () => {
    expect(scheduleWindow(new Date(2026, 0, 3), { back: 1, forward: 1 }))
      .toEqual({ from: "2026-01-02", to: "2026-01-04" });
  });
});

describe("scheduleUrl", () => {
  it("always bounds the request to a window", () => {
    expect(scheduleUrl({ from: "2026-08-01", to: "2026-08-31" }))
      .toBe("/api/scheduled-sessions/?from=2026-08-01&to=2026-08-31");
  });

  it("can narrow to one program", () => {
    expect(scheduleUrl({ from: "2026-08-01", to: "2026-08-31" }, 3))
      .toContain("training_program=3");
  });
});

describe("moveDateChoices", () => {
  const slot = { id: 1, date: "2026-08-05", training_program: 3 };

  it("offers a window around the current date, marking the current one", () => {
    const choices = moveDateChoices(slot, [slot], { back: 1, forward: 1 });
    expect(choices.map((choice) => choice.value))
      .toEqual(["2026-08-04", "2026-08-05", "2026-08-06"]);
    expect(choices.find((choice) => choice.current).value).toBe("2026-08-05");
  });

  // The server refuses a date the program already trains on, so it should never
  // be offered — unreachable rather than rejected, same as the end-time picker.
  it("hides dates this program already trains on", () => {
    const others = [slot, { id: 2, date: "2026-08-06", training_program: 3 }];
    const values = moveDateChoices(slot, others, { back: 1, forward: 1 })
      .map((choice) => choice.value);
    expect(values).not.toContain("2026-08-06");
  });

  it("still offers a date another PROGRAM trains on, which is allowed", () => {
    const others = [slot, { id: 3, date: "2026-08-06", training_program: 9 }];
    const values = moveDateChoices(slot, others, { back: 1, forward: 1 })
      .map((choice) => choice.value);
    expect(values).toContain("2026-08-06");
  });

  it("returns nothing for a slot with an unusable date", () => {
    expect(moveDateChoices({ id: 1, date: "nope", training_program: 3 }, [])).toEqual([]);
  });
});
