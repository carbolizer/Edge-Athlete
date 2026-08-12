# Coach Block Calendar And Workspace Sprint

## Stories

- As a coach, I can edit a reusable block and inspect the calendars created from it without rebuilding the block.
- As a coach, I see room status and my current task before secondary detail on the coach tablet.

## Assumptions

- A block may have several deployed programs. Its calendar therefore shows each related deployment explicitly rather than implying one block owns one calendar.
- Each schedule state has at most one lifecycle action. Moving a planned or ready day remains a secondary date control.
- Athlete check-in continues to happen at the rack; the coach room view observes it.

## Acceptance Criteria

1. Selecting a block reveals its editable metadata, ordered days, prescription rows, category labels, deployments, and related calendar in one workspace.
2. A coach can rename, reorder, and delete days and can edit, reorder, and delete prescription rows; saved changes survive reload.
3. Prescription-row editing includes movement, sets, reps, target percentage, and velocity bounds.
4. Editing a reusable block does not change an already deployed program snapshot.
5. Category chips use any-of filtering and labels can be changed from the selected block.
6. Calendar rows distinguish Planned, Ready, Running, and Completed; Planned and Ready expose one lifecycle action each.
7. Move choices omit dates occupied by another day in the same program, and server conflicts remain visible.
8. The coach default view shows compact room status and navigation before detailed controls.
9. Room/planning and athlete destinations are visually distinct. Athlete selection appears with athlete navigation.
10. Training-day setup detail is collapsed by default and opens only when requested.
11. Rack detail opens after an explicit rack selection; the default room view does not expand the first rack automatically.
12. Existing note-change confirmation, live-room reconciliation, hardware workflow, and rack check-in behavior remain intact.

## Edge Cases

- A block with no deployments shows an explicit no-calendar state.
- A block with several deployments lets the coach choose which deployment calendar to inspect.
- Empty blocks, schedules, rooms, and athlete selections show an actionable empty state.
- Failed edits retain the current UI and show the server error.
- Deleting or reordering rows never edits deployed snapshots.

## Non-Goals

- New scheduling schema, coach-side athlete check-in, drag-and-drop, recurring-series moves, or changes to WT901/NFC behavior.
- Changing the existing authenticated-coach authorization model in this sprint.

## Test Plan

- Django regression tests for block editing, deployment snapshots, schedule moves, setup, and start.
- Vitest coverage for catalog payloads, schedule states/date choices, grouped navigation, disclosure defaults, and rendered schedule states.
- Production frontend build and Django system/migration checks.
- Manual `/coach` checks at tablet portrait and landscape sizes.

## Demo

1. Open Workouts, filter by category, select a block, edit a day and prescription, and reload.
2. Choose a deployment and inspect its calendar; move a planned day and set it up.
3. Return to Room and show the compact default view, then select a rack for detail.
4. Open the Athlete workspace, choose an athlete, and move among overview, history, program, and notes.
