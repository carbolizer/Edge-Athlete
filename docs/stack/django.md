# Django

**What it is.** The web server and the only thing that writes to the database. A
Python framework; we use it with Django REST Framework for the API.

**How we use it.** Three processes from one image, because they have different jobs:

| Process | Job |
|---|---|
| `django` | serves `/api/…` — everything the screens read and write |
| `mqtt-listener` | subscribes to node heartbeats and records them |
| `monitoring-publisher` | drains change events and broadcasts them to screens |

It is deliberately **not** in the live rep path. Reps go node → broker → tablet, and
Django only sees a set when the tablet posts the whole thing at once.

**Where it lives.** `django/`, built locally from `django/Dockerfile`. Models in
`django/event_handler/models.py`, routes in `urls.py`, handlers in `views.py`.

**Worth knowing.** ⚠️ The image **bakes the source in** — there is no volume mount.
Editing a file changes nothing until you rebuild. Every "my change did nothing"
report so far has been this.

**More:** {doc}`../journal/apis` for the endpoints and the reasoning ·
{doc}`../guides/migrations` for changing the schema
