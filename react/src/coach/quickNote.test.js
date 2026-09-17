// Quick Note must never eat the note that was already there.
//
// It writes the SAME `Athlete.notes` column the ANALYTICS notes tab writes, so a
// version of this that set the field instead of appending to it would silently
// destroy a coach's long-form note the first time anyone typed a thought at a
// rack. That is the case these tests exist for.

import { describe, expect, it } from "vitest";
import { appendQuickNote, quickNoteStamp } from "./quickNote.js";

const AT = new Date("2026-08-01T14:32:00");

describe("appendQuickNote", () => {
  it("keeps everything that was already written", () => {
    const existing = "Long-standing context another coach wrote.";
    const result = appendQuickNote(existing, "shoulder looked off on set 3", AT);
    expect(result).toContain(existing);
    expect(result).toContain("shoulder looked off on set 3");
  });

  it("puts the newest entry last, so it reads in the order it happened", () => {
    const result = appendQuickNote("older thing", "newer thing", AT);
    expect(result.indexOf("older thing")).toBeLessThan(result.indexOf("newer thing"));
  });

  it("stamps the entry so two identical notes can be told apart", () => {
    expect(appendQuickNote("", "same words", AT)).toContain(quickNoteStamp(AT));
  });

  it("starts a fresh note cleanly when there is nothing there yet", () => {
    const result = appendQuickNote("", "first ever note", AT);
    expect(result.startsWith("[")).toBe(true);
    expect(result).toContain("first ever note");
  });

  it("treats a null or undefined existing note as empty, not as the word null", () => {
    expect(appendQuickNote(null, "note", AT)).not.toContain("null");
    expect(appendQuickNote(undefined, "note", AT)).not.toContain("undefined");
  });

  // Saving whitespace would push a stamp with no content into the record.
  it("changes nothing when the addition is blank", () => {
    expect(appendQuickNote("existing", "   ", AT)).toBe("existing");
    expect(appendQuickNote("existing", "", AT)).toBe("existing");
  });
});
