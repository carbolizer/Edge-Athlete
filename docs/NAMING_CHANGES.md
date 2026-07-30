# Naming changes — P9

Everything renamed on `merge-braydon`, and why. **No behaviour changed.** Same
data, same responses, same permissions — only names.

The one rule behind all of it: **a name should say what it actually is.** During
the merge we deliberately bent URLs to fit the existing front end, which was
right at the time and wrong to keep. A route named after a table that no longer
exists is a trap for whoever reads it next.

---

## 1. API routes

| Was | Now | Why |
|---|---|---|
| `POST/GET /api/workout-programs/` | `/api/training-blocks/` | It serves `TrainingBlock` — the reusable template. It was never a "program". |
| `POST/GET /api/workouts/` | `/api/training-blocks/{id}/workouts/` | A workout is one **day inside a block** and cannot exist without one. The block moved from the request body into the URL, so it can't be forgotten. |
| `POST /api/workouts/imports/preview/` | `/api/imports/preview/` | Imports handle **three** sheet types — roster, max sheet, and plan. Only one of them is workouts. |
| `POST /api/workouts/imports/` | `/api/imports/` | Same reason. |
| `GET/PUT/DELETE /api/athletes/{id}/workout-assignment/` | `/api/athletes/{id}/program/` | It returns the athlete's `TrainingProgram`s, not a workout. |
| `GET/PATCH/DELETE /api/athletes/{id}/workout-exercises/{id}/override/` | `/api/athletes/{id}/program-exercises/{id}/override/` | The id is a `TrainingProgramExercise`. The old name pointed at the wrong table and cost us a real bug. |
| `GET /api/programs/?athlete={id}` | `/api/prescriptions/?athlete={id}` | The `Program` table was deleted in P6. This now derives today's resolved targets, so it's named for what it returns. |

**Unchanged:** `sessions/`, `sets/`, `racks/`, `nodes/`, `athletes/`, `exercises/`,
`reports/`, `reference-maxes/`, `room-state/`, `training-groups/`,
`training-programs/`, `analytics/`.

---

## 2. Schema

| Was | Now | Notes |
|---|---|---|
| `Session` | `TrainingSession` | Migration `0012`, `RenameModel`. Table renamed; every FK re-pointed automatically. No data moved. |
| `TrainingGroup.coach` (one FK) | `TrainingGroupCoach` (join table) | Migration `0015`. **P11, and the one breaking API change since.** Each group's existing coach was carried across as its `head` coach — nobody lost a group. |

**Why:** a real weight room puts several staff on one group ("Sarah and Mike both
run Varsity"), which a single field cannot say. `coaches` is now a list and
`head_coach` is the one who answers for it — nullable, so don't assume it exists.
Being on the list is a *statement*, not a permission: nothing enforces it yet.

**Why:** "Session" is one of the most overloaded words in web software — Django
has sessions, HTTP has sessions, auth has sessions. Ours means one shared
training slot several groups can be scheduled into. Naming it `TrainingSession`
puts it alongside `TrainingBlock` / `TrainingProgram` / `TrainingGroup` so the
hierarchy reads as one family instead of three named things and one generic one.

`SessionParticipation` kept its name — it is unambiguous in context, and
`TrainingSessionParticipation` buys nothing.

---

## 3. Backend symbols

| Was | Now |
|---|---|
| `workout_programs_view` | `training_blocks_view` |
| `workouts_view` | `training_block_workouts_view` |
| `workout_import_preview` | `import_preview` |
| `workout_import` | `import_commit` |
| `athlete_workout_assignment` | `athlete_program_view` |
| `programs_view` | `prescriptions_view` |
| `SessionSerializer` | `TrainingSessionSerializer` |

---

## 4. Front end

| Was | Now |
|---|---|
| `WORKOUTS_URL` | `blockWorkoutsUrl(blockId)` — a function, since the block is in the path |
| `WORKOUT_PROGRAMS_URL` | `TRAINING_BLOCKS_URL` |
| `buildWorkoutPayload(name, exercises, blockId, position)` | `buildWorkoutPayload(name, exercises, position)` — block moved to the URL |

**One behavioural consequence, worth knowing:** days can no longer be listed
globally, because a day belongs to a block. The catalog's "Available workouts"
panel is now **"Days by block"**, built from the blocks already loaded — each
block arrives with its days nested inside it. One fewer request, and a day is
always shown with the block it belongs to.

---

## 5. Vocabulary

Use the model name, not the everyday word, in code, comments, and API docs.
Plain words are fine when introducing a concept to a coach — never as the
identifier.

| Don't say | Say | Because |
|---|---|---|
| squad | **TrainingGroup** | A named subset of athletes. Not the whole roster. |
| template | **TrainingBlock** | The reusable design: ordered days + cadence. No group, no dates. |
| plan / program | **TrainingProgram** | A block copied down for one group with real dates. |
| session | **TrainingSession** | One shared timeslot. Many groups can be on it. |

---

## What this does not fix

Names still carrying old assumptions, deliberately left for later phases:

- **`workout`** still means "a day inside a block". It's the coach's word and it
  survives in `TrainingBlockWorkout` and `TrainingProgramWorkout`.
- **`WorkoutCatalog.jsx`** and **`AthleteWorkoutPlanning.jsx`** keep their
  filenames. Renaming files makes every diff against `braydons-dev-branch`
  unreadable, which still has value while the merge is fresh.
- **`default_weight_lbs`** survives inside **stored report snapshots**. Those are
  frozen history written under that key — renaming them would blank the target
  column on every past report.
