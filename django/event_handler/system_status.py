"""system_status.py — "is this base station still shipping default credentials?"

Two secrets ship with the repo as placeholders: the Wi-Fi password
(`ChangeMe123!`) and Django's `SECRET_KEY`. Both are fine on a laptop and both
are a real hole in a gym — the SECRET_KEY especially, because it signs the
tokens a coach logs in with, so anyone holding it can forge a coach session
(canon: it is a symmetric HS256 key, sign == verify).

The old `startup.sh` set a flag file meaning "default password still in use" and
NOTHING ever read it. This is that idea finished: a coach-only endpoint the admin
page can poll, so the warning reaches a person instead of a dead file on disk.

WHY A ROUTE AND NOT THE FLAG FILE. The flag lived on the host, in
/var/lib/edgeathlete. Django runs in a container with its own filesystem and no
mount to the host, so it could not read the flag without new plumbing that
crosses the boundary we keep clean elsewhere. The values are already IN the
container's environment (env_file: .env), so a route just reads them directly —
no file, no mount, no host dependency.

WHAT IT CANNOT DO. It compares against the KNOWN shipped defaults. It can tell
"unchanged" from "changed"; it cannot judge whether a changed value is any good.
That is enough for a nudge, which is all this is.
"""

from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .permissions import IsCoach

# The exact strings the repo ships with. Kept here, next to the check, so there
# is one obvious place to update if a default ever changes in .env.example or the
# startup script.
DEFAULT_WIFI_PASSWORD = "ChangeMe123!"
DEFAULT_SECRET_KEYS = {
    # .env.example's committed key, and the fallback settings.py uses when DEBUG
    # is on and nothing is set. Either one live on a real gym is the problem.
    "django-insecure-edgeathlete-dev-key-replace-for-prod",
    "django-insecure-fallback-for-local-development-only",
}


@api_view(["GET"])
@permission_classes([IsCoach])
def system_status(request):
    """Coach-only. What still needs changing before this box faces a real gym.

    Coach-only on purpose: this is an operator's checklist, not something the
    whole gym network should be able to read the security posture from.
    """
    secret_key = settings.SECRET_KEY or ""
    secret_key_is_default = secret_key in DEFAULT_SECRET_KEYS

    # The Wi-Fi password is not a Django setting — it lives in the base station's
    # config file. startup.sh sources that file and passes AP_PASSWORD into this
    # container (see docker-compose.yml). On a laptop, or any box without an AP,
    # it arrives unset or empty — which means "cannot tell from here", and that
    # is NOT the same as "it is the default". Empty and missing both read as
    # unknown so the banner never cries wolf on a machine that has no AP at all.
    import os
    wifi_password = os.environ.get("AP_PASSWORD") or None
    if wifi_password is None:
        wifi_password_is_default = None      # unknown from inside the container
    else:
        wifi_password_is_default = wifi_password == DEFAULT_WIFI_PASSWORD

    # A single roll-up so the banner has one boolean to switch on, without having
    # to know the rules. `None` (unknown) is deliberately NOT counted as a
    # problem — better a missed nudge than crying wolf on every dev machine.
    needs_attention = bool(secret_key_is_default) or wifi_password_is_default is True

    return Response({
        "debug": settings.DEBUG,
        "secret_key_is_default": secret_key_is_default,
        "wifi_password_is_default": wifi_password_is_default,
        "needs_attention": needs_attention,
    })
