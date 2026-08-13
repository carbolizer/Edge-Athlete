"""health.py — is this container actually able to do its job?

Docker restarts a container that CRASHES. It cannot see one that is still
running but useless: a Django worker that came up before Postgres was ready and
is now failing every query, a wedged process holding the port open and
answering nothing. From the outside both of those look identical to healthy —
the container is up, the port is bound, and every tablet in the gym is timing
out.

So this answers the only question a health check should: can it serve a request
AND reach the database. It deliberately does a real query rather than returning
a constant, because "the web server is alive" was never the part in doubt.

Kept as cheap as a query can be — SELECT 1, no models, no serializers — since
this runs every few seconds forever.
"""

from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """200 when the app can serve and the database answers, 503 when it cannot.

    Open on purpose. A health check that needs a login cannot be used by the
    thing whose job is to notice that logins are broken.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        # The reason is returned rather than logged and swallowed: when this
        # trips, the person reading it is looking at `docker ps` output at an
        # unsociable hour and every extra guess costs them.
        return Response({"status": "unhealthy", "database": "unreachable",
                         "detail": str(exc)}, status=503)

    return Response({"status": "ok", "database": "ok"})
