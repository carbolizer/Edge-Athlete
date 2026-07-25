"""Derived read logic — the one home for "computed, never stored" answers.

Anything the coach or wall screens need that can be WORKED OUT from the tables we
already have lives here instead of becoming a new table. That is a deliberate
rule of this codebase (merge canon D3): stored copies of derivable facts drift
from the truth and need a second write path to keep in sync, so we derive per
request instead.

views.py stays thin — it handles HTTP (auth, status codes, response headers) and
calls in here for the actual thinking.
"""
