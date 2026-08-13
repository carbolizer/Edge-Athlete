# The journal

Why the system is the way it is: each decision, what it displaced, and what it cost.

## The groundwork

What everything else sits on. Read the relevant one before the screen that uses it.

- {doc}`database` — tables, the three weights, how a target is derived
- {doc}`apis` — endpoints, permissions, where auth lives
- {doc}`real-time` — the message broker, and what actually listens to it
- {doc}`scripts` — the base station, its Wi-Fi, and how a gym gets one

## The screens

Each one is a view onto the groundwork above.

- {doc}`rack-tablet` — what the athlete uses, and where durability lives
- {doc}`coach-tablet` — login, room setup, planning, spreadsheet import
- {doc}`dashboard` — the wall display

```{toctree}
:maxdepth: 2
:hidden:

database
apis
real-time
scripts
rack-tablet
coach-tablet
dashboard
```
