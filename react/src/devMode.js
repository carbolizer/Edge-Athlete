// devMode.js — "should this screen show developer instrumentation?"
//
// Some things on the coach screen exist to tell US the plumbing is working, not
// to help a coach train anyone: reconciliation timestamps, queue depths, raw
// counters. They are genuinely useful while building and pure noise in a weight
// room, so they hide behind this instead of being deleted.
//
// TWO WAYS TO BE ON, because there are two ways we look at this app:
//   1. `npm run dev` — always on. If you are running the dev server you are
//      developing, and Vite sets import.meta.env.DEV for exactly this.
//   2. localStorage `ea_dev` = "1" — on in a BUILT container. The Docker image
//      is a production build, so flag 1 is false there, but the container is
//      where we actually demo and debug. There is a switch for this in Room
//      Layout's dev panel, so nobody has to remember the key name. The console
//      still works:
//
//        localStorage.setItem('ea_dev', '1')   // then reload
//        localStorage.removeItem('ea_dev')
//
// Deliberately NOT tied to the coach login: "is a coach" and "is a developer"
// are different questions, and every coach in a real gym would otherwise see it.

export function isDevMode() {
  try {
    if (import.meta.env?.DEV) return true;
    return localStorage.getItem('ea_dev') === '1';
  } catch {
    // localStorage can throw in a locked-down browser context. Instrumentation
    // is never important enough to break the screen over.
    return false;
  }
}

// Turn the flag on or off. Only the built-container case is settable — under
// `npm run dev` instrumentation is on regardless, and pretending otherwise would
// give a switch that visibly does nothing.
export function setDevMode(on) {
  try {
    if (on) localStorage.setItem('ea_dev', '1');
    else localStorage.removeItem('ea_dev');
    return true;
  } catch {
    return false;
  }
}
