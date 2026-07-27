"""TEMPORARY DEV-ONLY ENDPOINT — delete this whole file when you're done with it.

WHY IT EXISTS
Setting up a demo currently means SSHing in and running a management command.
That's fine for us and terrible in front of anyone else, so this exposes the
demo-data seeder as a button the coach page can press.

THIS IS SCAFFOLDING, NOT A FEATURE. It is expected to be deleted.

HOW TO REMOVE IT (about 15 seconds, in this order):
  1. delete this file
  2. delete the one `dev/` line in urls.py (it's flagged with the same DEV-ONLY note)
  3. delete react/src/coach/DevPanel.jsx and its two lines in CoachTablet.jsx
Nothing else imports any of it, so nothing else breaks.

WHY IT REFUSES TO RUN IN PRODUCTION
The seeder DELETES and recreates the demo athletes and their session. That is
exactly what you want on a laptop and a catastrophe on a real base station with
a gym's actual history in it, so this endpoint hard-refuses unless DEBUG is on.
The guard is deliberately not overridable.
"""

from django.conf import settings
from django.core.management import call_command
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .permissions import IsCoach


@api_view(["POST"])
@permission_classes([IsCoach])
def dev_seed_session(request):
    """Rebuild the demo gym: a live session, four athletes, plans, and some
    completed sets. Same thing the `seed_active_session` command does, because
    it literally calls it — there is no second copy of that logic to drift.

    Safe to press repeatedly: the seeder clears its own demo rows first, so you
    get a clean gym rather than four more athletes each time.
    """
    if not settings.DEBUG:
        return Response(
            {"error": "dev seeding is disabled outside DEBUG — this endpoint wipes and "
                      "recreates demo data and must never run against real training history"},
            status=403,
        )

    call_command("seed_active_session")
    call_command("ensure_demo_coach")
    return Response({"status": "seeded", "detail": "demo session, athletes, plans and sets recreated"})
