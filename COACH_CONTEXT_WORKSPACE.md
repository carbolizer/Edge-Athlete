# Feature Spec: Coach Context Workspace

- Status: Done
- Date: 2026-07-14
- Owner: Braydon

## User story

As a coach, I want room, athlete, history, program, and note context in one tablet workspace so I can make decisions from saved evidence instead of memory.

## Scope

- `Room`: live rack monitoring from the existing revision-aware room snapshot.
- `Athlete`: all-time summary, exercise summaries, and recent measured performance.
- `History`: newest 50 completed real sets grouped into local calendar days and
  saved workouts. Each set presents its summary first and expands into a
  rep-by-rep mean/peak/duration comparison.
- `Programs`: read-only prescriptions; no active/current claim.
- `Notes`: one persistent athlete note with optimistic concurrency.

## Non-goals

- Program editing, note timelines/authorship, athlete mutations, fatigue/readiness/form/load recommendations, and unsaved reps.

## Acceptance criteria

- [x] All five tabs preserve the selected athlete.
- [x] Athlete and History use completed, non-false persisted sets only and display unavailable measurements as `--`.
- [x] History groups sets by training day and workout, then exposes one
  keyboard-accessible set comparison at a time without loading another endpoint.
- [x] All-time and per-exercise summaries include older sets even though detail history is capped at 50.
- [x] Programs are read-only and do not label a prescription active.
- [x] Notes require a coach JWT, preserve drafts on failure, and reject stale saves with HTTP 409.
- [x] Authentication loss clears athlete context and notes before returning to login.
- [x] Historical tabs remain available when no room session is active.
- [x] Backend and frontend validation pass at landscape and portrait tablet widths.

## Security

- Analytics and notes use `IsCoach` and `Cache-Control: private, no-store`.
- Responses omit NFC IDs, athlete/session notes outside the notes endpoint, and node identifiers.
- Generic athlete PATCH cannot update notes.

## Evidence

- `npm test -- --run`: 6 frontend tests passed, including local-day/workout
  grouping, newest-first ordering, and rep delta calculations.
- `npm run build`: production build passed; the existing bundle-size warning remains.
- Live CDP check at 1280×800: day/workout headings rendered, one set expanded
  to three rep rows, and the page had no horizontal overflow.
- Live CDP check at 390×844: the page had no horizontal overflow and the 720 px
  rep table scrolled inside its 318 px detail region.
- Component interaction automation is waived until this repository adopts a DOM
  test harness; native disclosure button behavior and ARIA state were observed in
  the live check.
