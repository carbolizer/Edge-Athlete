# `services/` — the thinking

**This is not a Django convention.** Django gives you `models.py`, `views.py`,
`admin.py` and `tests.py`; this package is ours. It exists so `views.py` stays
thin — HTTP in, HTTP out — while the actual work lives in plain, testable
functions with no request object in sight.

The rule that created it: **anything that can be worked out from the tables we
already have is worked out, not stored.** A stored copy of a derivable fact drifts
from the truth and needs a second write path to keep it honest. So there is no
room-state table, no participation snapshot, no cached target weight.

There is exactly one exception, and it is deliberate: `DailyReport` freezes a
finished day, because a report must keep saying what was true on the day it was
made.

```
services/
├── __init__.py             The rule above, written down. Read it first
├── active_session.py       The one answer to "which training day is live right now?"
├── athlete_analytics.py    What the coach's athlete + history tabs read
├── cadence.py              Which weekdays a block trains on, and the dates that fall out
├── csv_import.py           Turning a coach's spreadsheet into real training data
├── csv_parsing.py          Reading that spreadsheet safely, before lifting matters
├── lifting_math.py         The lifting arithmetic — 1RM, rep-basis, bar rounding
├── plan_resolution.py      What an athlete does today, and what weight goes on the bar
├── planning.py             Turning a reusable template into a group's actual plan
├── report_pdf.py           A finished day, as a printable PDF
├── reports.py              Stored report snapshots → the shapes the reports UI reads
├── room_state.py           The live room picture, for the wall display and the coach
├── session_completion.py   Ending a day: freeze the report, then update everyone's maxes
└── tuning.py               Every number a coach might argue with, in one file
```

## If you only read three

| | |
|---|---|
| `__init__.py` | Why this folder exists at all |
| `plan_resolution.py` | How a percent becomes pounds on a bar — the core idea of the product |
| `tuning.py` | Where to change the numbers, without hunting |

## Two things to know before adding a file here

- **No `request` objects.** These functions take ids and values and return data.
  That is what makes them testable without HTTP, and reusable between the rack
  tablet, the coach view, and the PDF.
- **Deciding to store something is a decision, not a shortcut.** If you find
  yourself adding a table to cache a derived answer, that is a real design change
  — see `__init__.py` and SPEC §6.
