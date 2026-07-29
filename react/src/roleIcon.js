// roleIcon.js — which app icon this screen shows IN THE PAGE.
//
// Not the same job as device.js, and deliberately not in it. That file points
// the browser's INSTALL tags (manifest, apple-touch-icon) at the right per-role
// files, is part of the frozen set, and exports nothing an in-page <img> can
// use. This is the on-screen counterpart, kept small and separate rather than
// reaching into a frozen file.
//
// Each device shows its OWN icon: a wall display should not wear the coach app's
// mark. Before this, every screen showed a green "EA" lettermark that belonged
// to no particular app.

// The 192px variants, not the 180px apple-touch-icon ones device.js uses — those
// exist for iOS home-screen installs, and borrowing them here would tie an
// on-screen decision to an install-time constraint.
const ROLE_ICONS = {
  rack: "/icon-rack-192.png",
  dashboard: "/icon-dashboard-192.png",
  coach: "/icon-coach-192.png",
};

// The role this tablet was set up as, or null before setup. `mode` is what the
// current screen is rendering — a device set up as a rack can still be showing
// the coach view — so it wins when given.
//
// `wall` is the Dashboard component's word for the same thing device.js calls
// `dashboard`; both are accepted so a caller never has to remember which is
// which. Falls back to the coach icon rather than to nothing: an unset role
// means setup has not run, and the shipped default landing screen is the coach
// workspace.
export function roleIconSrc(mode) {
  const normalized = mode === "wall" ? "dashboard" : mode;
  if (ROLE_ICONS[normalized]) return ROLE_ICONS[normalized];

  let stored = null;
  try {
    stored = localStorage.getItem("device_role");
  } catch {
    // Private-mode Safari can throw on localStorage. An icon is not worth
    // taking a screen down for.
    stored = null;
  }
  return ROLE_ICONS[stored] || ROLE_ICONS.coach;
}
