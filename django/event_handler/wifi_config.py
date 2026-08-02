"""wifi_config.py — change the base station's Wi-Fi (AP) password from the app.

⚠️ THE WEB APP IS NOT ALLOWED TO TOUCH THE HOST NETWORK, on purpose. Django runs
in a container; the Wi-Fi AP is the host's, driven by `nmcli` through
NetworkManager. Handing this container the privileges to run nmcli (host network,
NET_ADMIN, D-Bus) would make the most exposed service in the building able to
reconfigure the building — a bad trade on a lean, closed box.

So this endpoint only writes INTENT: it drops the requested password into a spool
file. A privileged HOST agent — a systemd path-unit that watches that file and
does the actual nmcli work as root, on the host — is the other half of this
feature and is NOT built yet (next checkpoint). Until it lands, the request is
written and nothing consumes it, so this endpoint does not yet change any real
AP. That is why it ships on a branch, not to a gym.

That split also fixes a problem live-apply would otherwise have: applying the new
password disconnects every device INCLUDING the coach's own tablet, so a
synchronous "change it and reply" would drop the network before the reply landed.
Writing intent returns immediately; the host agent applies it a beat later, after
the response is already on its way.

Coach-only, and re-authenticated: changing the gym Wi-Fi is exactly the kind of
standing-config change that should cost a password even from an already-logged-in
coach (canon: side-effectful config asks for confirmation).
"""

import os

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .permissions import IsCoach

# WPA2-PSK accepts 8..63 printable ASCII characters. Anything outside that the AP
# would reject at apply time, so it is caught here where the coach can see why.
WPA2_MIN_LEN = 8
WPA2_MAX_LEN = 63


def spool_path():
    """Where the request is dropped for the host agent to pick up. Overridable so
    tests can point it at a temp file instead of the real /var/lib path."""
    return os.environ.get(
        "WIFI_APPLY_SPOOL", "/var/lib/edgeathlete/wifi-apply.request")


@api_view(["POST"])
@permission_classes([IsCoach])
def change_wifi_password(request):
    """Queue a Wi-Fi password change for the host agent to apply.

    Body: { "coach_password": "...", "new_password": "..." }
    """
    coach_password = request.data.get("coach_password") or ""
    new_password = request.data.get("new_password") or ""

    # Re-auth. request.user is the coach the JWT belongs to; check_password
    # compares against the stored hash. A blank password is never valid.
    if not coach_password or not request.user.check_password(coach_password):
        return Response(
            {"error": "coach_password_incorrect",
             "detail": "That is not your coach password."},
            status=403)

    # Validate before writing anything — a rejected password should never reach
    # the spool file and never disturb a working AP.
    if not (WPA2_MIN_LEN <= len(new_password) <= WPA2_MAX_LEN):
        return Response(
            {"error": "invalid_password",
             "detail": f"Wi-Fi password must be {WPA2_MIN_LEN}–{WPA2_MAX_LEN} characters."},
            status=400)
    if any(ord(char) < 32 or ord(char) > 126 for char in new_password):
        return Response(
            {"error": "invalid_password",
             "detail": "Wi-Fi password must be plain printable characters (no tabs or accents)."},
            status=400)

    spool = spool_path()
    spool_dir = os.path.dirname(spool)

    # No spool directory means there is no base station here to change — a dev
    # machine, or any box without the base-station mount. Say so plainly rather
    # than 500-ing on a missing path; the form is reachable on a laptop too.
    if not os.path.isdir(spool_dir):
        return Response(
            {"applied": False,
             "detail": "No base station Wi-Fi to change from this environment."},
            status=200)

    # Write the request 0600 — it holds the new password in the clear (as does
    # basestation.conf itself). The host agent consumes and deletes it.
    try:
        fd = os.open(spool, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(new_password + "\n")
    except OSError as exc:
        return Response(
            {"error": "spool_write_failed", "detail": str(exc)}, status=503)

    return Response({
        "applied": True,
        "detail": "Wi-Fi password saved. Applying now — every device, including "
                  "this one, must reconnect with the new password in a few seconds.",
    })
