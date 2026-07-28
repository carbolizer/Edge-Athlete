# Importing your spreadsheets

You already keep your athletes, their numbers, and your workouts in spreadsheets.
You don't have to retype any of it. Save a sheet as a CSV, upload it, and the
system works out what it is on its own.

**You never have to tell it which kind of sheet you're uploading.** It reads your
column names and figures it out.

---

## Before you start: the two-step upload

Every upload happens twice, on purpose.

1. **Preview** — it reads your file and shows you what it understood. **Nothing is
   saved.** If something is wrong, it tells you which line and why.
2. **Import** — saves it.

If anything is wrong, the Import button stays off until you fix it. You can't
accidentally half-import a file.

### Saving a CSV out of Excel or Google Sheets

- **Excel:** File → Save As → choose **CSV UTF-8 (Comma delimited)**
- **Google Sheets:** File → Download → **Comma-separated values (.csv)**

The first row of your sheet must be the column names. Capital letters and extra
spaces in the column names don't matter — `Athlete Name`, `athlete_name`, and
`ATHLETE_NAME` all work.

---

## The three kinds of sheet

| What you have | Columns it needs | What happens |
|---|---|---|
| **A roster** — just a list of people | `athlete_name` | Adds them as athletes |
| **A max sheet** — what people can lift | `athlete_name`, `exercise`, and a weight | Records their maxes |
| **A workout plan** — the training itself | `workout_name`, `exercise`, … | Builds the workouts |

---

## 1. A roster — adding your athletes

**The smallest version that works:**

```
athlete_name
Jordan Lee
Sam Rivera
Alex Kim
```

**You can also add:**

| Column | What it does |
|---|---|
| `training_group` | Puts them straight into that squad |
| `nfc_tag_id` | Their tap-to-identify tag, if they have one |
| `notes` | Anything you want to remember about them |

```
athlete_name,training_group,notes
Jordan Lee,Varsity Football,Coming back from a knee
Sam Rivera,Varsity Football,
```

**Good to know**

- **Re-uploading is safe.** If someone is already on the roster, they're skipped —
  not duplicated. So you can add ten new names to last season's list and upload
  the whole thing again.
- Names written **surname-first** are understood. `Lee, Jordan` and `Jordan Lee`
  are the same person.
- The squad in `training_group` has to exist already. If it doesn't, you'll be
  told, and shown the closest squad names in case you just spelled it differently.

---

## 2. A max sheet — the most important one

**This is the sheet that makes everything else work.** Every weight the system
puts on a rack screen is a percentage of these numbers. Without them, workouts
show up with no weight on them.

### The easy version

If your numbers are one-rep maxes, call the column **`max_lbs`** and you're done:

```
athlete_name,exercise,max_lbs
Jordan Lee,Back Squat,405
Jordan Lee,Bench Press,275
Sam Rivera,Back Squat,365
```

One row per person per movement.

### If your numbers aren't one-rep maxes

Lots of coaches record something else — "what they did for 5" or "what they hit
at 80%". That's fine, you just have to say which. Use **`weight_lbs`** plus one
more column:

**They lifted this for this many reps:**

```
athlete_name,exercise,weight_lbs,reps
Jordan Lee,Back Squat,315,5
```

The system works out the one-rep max from that.

**This weight was a percentage:**

```
athlete_name,exercise,weight_lbs,target_percent
Jordan Lee,Back Squat,315,80
```

It works backwards to the full max.

### ⚠️ The one thing that gets skipped

If a row has a weight but **doesn't say what the weight means** — no `reps`, no
`target_percent`, and the column isn't called `max_lbs` — that row is **left out**,
and you're told which ones and why.

```
athlete_name,exercise,weight_lbs
Jordan Lee,Back Squat,315        ← is that a max? a set of 5? we don't know
```

**Why it isn't just guessed:** an athlete's max is whatever was recorded most
recently. A guessed number would quietly become their official max and then drag
down *every* weight prescribed for them, in every movement, until someone noticed.
An athlete with no max recorded is a normal situation the system handles fine.
A wrong max is not.

**The fix is easy** — rename the column to `max_lbs`, or add a `reps` or
`target_percent` column.

### Good to know

- **Nobody gets created from a max sheet.** If a name doesn't match anyone, it
  stops and asks — because a misspelling turned into a brand-new athlete would sit
  in your roster forever, looking like a real person.
- **Uploading again updates people.** Nothing is overwritten; the newest number is
  simply the one that counts, and the old ones stay as history you can look back at.
- A max can go **down**, and that's on purpose. It's "what can they do right now",
  not a trophy.

---

## 3. A workout plan

```
workout_name,exercise,position,sets,reps,target_percent
Day 1 - Lower,Back Squat,1,5,3,80
Day 1 - Lower,Romanian Deadlift,2,3,8,65
Day 2 - Upper,Bench Press,1,3,5,75
Day 2 - Upper,Barbell Row,2,4,8,70
```

| Column | What it means |
|---|---|
| `workout_name` | Which day this row belongs to. Rows with the same name become one workout. |
| `exercise` | The movement |
| `position` | The order within that day — **1, 2, 3… with no gaps** |
| `sets` / `reps` | How many |
| `target_percent` | **Percent of their max**, not pounds. `80` means 80%. |

**Optional:** `velocity_min` and `velocity_max` set the bar-speed range that colors
the reps on the rack screen. Fill in both or neither.

### Weights are percentages, not pounds

There's no column for a weight in pounds, and that's deliberate. You write the
plan once as percentages, and every athlete gets their own weight worked out from
their own max. One plan, thirty athletes, thirty correct bars.

Percentages above 100 are allowed — overload work is real training. Zero isn't.

### Where the workouts go

You choose one of two places when you upload:

| Choice | Use it when |
|---|---|
| **A template** | You'll run this again — next season, or with another squad |
| **One squad's plan** | This is a one-off for this group |

New workouts are **added after** whatever's already there. Importing two more days
into a template that has two gives you four, in order — nothing gets overwritten.

### The day order

The order your workouts appear in the file is the order they'll be in. The first
`workout_name` to show up is day one. There's no column for it, because your rows
are already in the right order.

---

## When something's wrong

You get told **which line** and **what's wrong with it**, and the rest of the file
is still read — one typo doesn't cost you the other 199 rows.

**Misspelled a name?** You'll be shown the closest matches:

> Line 7: No athlete named 'Jordn Lee'. **Did you mean: Jordan Lee?**

**Two people with the same name?** You'll be asked which one you meant. This comes
up much less often if you pick the squad you're importing for — two Jordan Lees in
a whole gym is likely, two in the same squad almost never happens.

**Common ones and their fixes:**

| What it says | What to do |
|---|---|
| Missing column(s) | Add the column, check the spelling |
| Unexpected column(s) | Remove it, or check the spelling |
| This file's columns don't match any sheet | Check the very first row is your column names |
| Must be a positive whole number | A blank or a typo in `sets`, `reps`, or `position` |
| Must number its exercises 1, 2, 3… | A gap or a repeat in `position` for that day |
| Fill in both velocity_min and velocity_max | You filled in one of the pair |
| The file must be saved as UTF-8 CSV | Re-save it as **CSV UTF-8** |

**Nothing is saved while any line is still wrong.** Fix it, preview again, import.

---

## Quick reference

**Roster**
```
athlete_name,training_group
Jordan Lee,Varsity Football
```

**Maxes**
```
athlete_name,exercise,max_lbs
Jordan Lee,Back Squat,405
```

**Maxes, when the number isn't a one-rep max**
```
athlete_name,exercise,weight_lbs,reps
Jordan Lee,Back Squat,315,5
```

**Workout plan**
```
workout_name,exercise,position,sets,reps,target_percent
Day 1 - Lower,Back Squat,1,5,3,80
```

---

*Movement names have to match the exercise list the system already knows. If one
doesn't, you'll be shown the closest matches — usually it's just a spelling
difference.*
