# React (and Vite)

**What it is.** The app every screen runs. One codebase, four faces — rack screen,
wall display, coach console, setup — chosen by URL. Vite is the build tool.

**How we use it.** The role comes from the path, and decides the PWA identity:

```
/rack/{n}      the athlete's screen at a rack
/dashboard     the wall display
/coach/setup   the room layout and admin
/rack/setup    a tablet waiting to be assigned
```

The bundle is built at image build time and served by nginx as static files. There
is no Node process in production.

**Where it lives.** `react/src/`. Built into `react/dist/`, which is gitignored —
the container builds its own.

**Worth knowing.** ⚠️ `react/src/rack/`, `react/src/db/repBuffer.js` and
`react/src/device.js` are a **frozen contract**. Build alongside them, not inside
them.

**More:** {doc}`../journal/rack-tablet` · {doc}`../journal/coach-tablet` ·
{doc}`../journal/dashboard`
