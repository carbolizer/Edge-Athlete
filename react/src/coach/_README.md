# `coach/` — rack setup, and the coach's auth

Small folder, narrow job. **This is not the coach admin console** — that lives in
`src/` proper (`Dashboard.jsx`, `WorkoutCatalog.jsx`, `ScheduleWorkspace.jsx`,
`ReportsWorkspace.jsx`, and friends).

What is in here is the **setup** screen: log in, then wire tablets to rack numbers.
Sensor selection happens beside the physical rack before athlete check-in.

```
coach/
├── CoachTablet.jsx   Route /coach/setup — login gate, then assign screens to racks
├── CoachTablet.css   Its styles
├── api.js            JWT helpers: login, token storage, authorised fetch
└── DevPanel.jsx      ⚠️ Temporary demo tooling — see below
```

## Why rack assignment is a screen at all

A sensor (`Node`) and a tablet (`RackScreen`) are **separate identities**. This
screen assigns the tablet. The rack-local setup gate assigns its sensor so the
coach can verify the selection beside the hardware.

## `api.js` is the auth boundary

Every authenticated coach call goes through `coachFetch`. The token lives in
`localStorage` so a refresh doesn't drop a coach mid-demo.

If you are adding a coach screen, import from here rather than writing another
fetch wrapper — one place that knows about the token is the only way the 401
behaviour stays consistent.

## `DevPanel.jsx` is meant to be deleted

Two buttons that seed and reset the demo gym without a terminal. It exists so a
demo can be rescued in front of an audience.

It is **destructive to demo data** and has no place in anything a real gym runs.
Its own header says to delete it when the project no longer needs it — that is
still true.

---

**On the frozen line:** `src/rack/` is a fixed contract and must not be edited.
This folder is *not* frozen — it is normal code you can change freely. Don't let
the neighbouring folder make you nervous about this one.
