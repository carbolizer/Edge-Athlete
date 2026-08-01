// quickNote.js — adding a thought to an athlete's notes without losing the rest.
//
// ⚠️ THE WHOLE REASON THIS IS NOT A ONE-LINER. Quick Note and the ANALYTICS
// notes tab write THE SAME FIELD — `Athlete.notes`, one text column. There is no
// separate quick-notes store, and inventing a name that implied one would be a
// lie about the database.
//
// So a quick note cannot SET that field. A coach mid-floor types "shoulder
// looked off on set 3"; if that replaced the column, the paragraph another coach
// wrote about this athlete's history would be gone, silently, with no undo. It
// APPENDS instead, under a timestamp, so the column only ever grows.
//
// ⚠️ STILL LAST-WRITE-WINS. `Athlete.notes` has no version to compare against
// (canon §8.1), so this reads the current value and writes it back with the new
// line on the end. Two coaches adding a note to one athlete in the same few
// seconds means the second write can drop the first one's line. Appending
// narrows that window to the length of one round trip; it does not close it.
// Closing it needs a column that does not exist.

/**
 * The stamp a quick note is filed under. Date AND time, because "shoulder looked
 * off" three weeks ago and the same words this morning are different facts, and
 * a coach reading back needs to tell them apart.
 */
export function quickNoteStamp(at = new Date()) {
  return at.toLocaleString([], {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

/**
 * Existing notes plus one new stamped entry.
 *
 * Newest goes at the BOTTOM, so the note reads as a history in the order it
 * happened. Returns the existing text untouched if there is nothing to add —
 * whitespace is not a note, and saving it would push a stamp with no content
 * into the record.
 */
export function appendQuickNote(existing, addition, at = new Date()) {
  const text = String(addition ?? "").trim();
  const before = String(existing ?? "").replace(/\s+$/, "");
  if (!text) return before;
  const entry = `[${quickNoteStamp(at)}] ${text}`;
  return before ? `${before}\n\n${entry}` : entry;
}
