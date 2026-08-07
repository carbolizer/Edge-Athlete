# Importing your spreadsheets

:::{note}
Written for coaches. Developers should read the import decisions in
{doc}`../journal/coach-tablet`.
:::


Save your sheet as **CSV UTF-8**, then upload it. The column names tell the system
what kind of sheet it is — you don't pick.

Preview first. Nothing saves until you press Import.

> Excel: File → Save As → **CSV UTF-8 (Comma delimited)**
> Google Sheets: File → Download → **Comma-separated values**

---

## Roster

```
athlete_name,training_group
Jordan Lee,Varsity Football
Sam Rivera,Varsity Football
```

`training_group` is optional, as are `nfc_tag_id` and `notes`.

Upload it again after adding names — people already on the roster are skipped, not
duplicated. `Lee, Jordan` and `Jordan Lee` are the same person.

---

## Maxes

Every weight on a rack screen comes from these.

```
athlete_name,exercise,max_lbs
Jordan Lee,Back Squat,405
Jordan Lee,Bench Press,275
```

**If your numbers aren't one-rep maxes**, use `weight_lbs` and say what they are:

```
athlete_name,exercise,weight_lbs,reps        │  athlete_name,exercise,weight_lbs,target_percent
Jordan Lee,Back Squat,315,5                  │  Jordan Lee,Back Squat,315,80
```

**A weight with nothing to explain it is skipped:**

```
athlete_name,exercise,weight_lbs
Jordan Lee,Back Squat,315      ← a max? a set of 5? 80%?  → skipped, and you're told
```

Rename the column to `max_lbs`, or add `reps` or `target_percent`.

A guessed max would become that athlete's official number and shrink every weight
prescribed for them. No max at all is harmless.

Re-uploading updates people. The newest number counts; the old ones stay as history.
Maxes are allowed to go down.

---

## Workout plan

```
workout_name,exercise,position,sets,reps,target_percent
Day 1 - Lower,Back Squat,1,5,3,80
Day 1 - Lower,Romanian Deadlift,2,3,8,65
Day 2 - Upper,Bench Press,1,3,5,75
Day 2 - Upper,Barbell Row,2,4,8,70
```

- `target_percent` — percent of each athlete's own max. One plan, thirty correct
  bars. Over 100 is allowed.
- `position` — the order within a day. 1, 2, 3, no gaps.
- Same `workout_name` = same day. Whichever appears first is day one.
- `velocity_min` + `velocity_max` are optional. Both or neither.

There's no column for pounds.

On upload you choose a **template** (you'll run it again) or **one TrainingGroup's plan**.
Either way the new days are added after what's already there.

---

## When something's wrong

> Line 7: No athlete named 'Jordn Lee'. **Did you mean: Jordan Lee?**

The rest of the file still reads — one typo doesn't cost you 199 rows. Nothing
saves until every line is clean.

| Message | Fix |
|---|---|
| Missing / unexpected column | Check the spelling in row 1 |
| Columns don't match any sheet | Row 1 must be your column names |
| Must be a positive whole number | Blank or typo in `sets`, `reps`, `position` |
| Must number its exercises 1, 2, 3… | Gap or repeat in `position` |
| Fill in both velocity_min and velocity_max | You filled in one |
| Must be saved as UTF-8 CSV | Re-save as **CSV UTF-8** |

Two athletes with the same name? You'll be asked which — and asked far less often
if you pick the TrainingGroup you're importing for.

A max sheet never creates people. An unknown name stops and asks, so a typo can't
become a second Jordan Lee.

Movement names must match the exercise list. If one doesn't, you'll be shown the
closest matches.