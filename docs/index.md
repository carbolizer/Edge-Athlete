# Edge Athlete — Developer Journal

A record of how this system was built and **why it is the way it is** — written by the
developers who built it, for whoever picks it up next.

Most documentation tells you what the code does. You can get that from the code. This
site exists for the part you cannot: the decisions, the alternatives that were tried
and rejected, and the reasons that are no longer obvious a month later.

:::{note}
**What is still thin.** Everything here is written; two things are knowingly
incomplete. Most tables in {doc}`journal/database` show their columns but not the
reasoning behind them, and {doc}`reference/spec` is the original build specification
kept verbatim rather than rewritten — it describes the plan, and several phases of
that plan were later rebuilt. {doc}`history` says which ones.
:::

## Get productive in an hour

A guided path, in order. You do not need anything else to start being useful.

1. **{doc}`orientation` — 20 minutes.** What the system is, the four kinds of device,
   how a single rep travels from the barbell to a screen, and the vocabulary. Read
   this one properly; everything else assumes it.
2. **One journal page — 20 minutes.** Whichever part you are about to touch. Not all
   seven. Each opens with what that piece is and why it exists.
3. **{doc}`guides/base-station` — 20 minutes.** Get it running. Reading about a
   distributed system is no substitute for watching a rep land on a screen.

If you are joining to *maintain* rather than to add something specific, read
{doc}`history` after step 1 — it is the narrative of how the project actually
went, including the parts that changed course.

## How this site is organised

Three kinds of question, deliberately kept apart:

**{doc}`The journal <journal/index>` — "why is it like this?"**
: The decisions. What forced each one, what was chosen, **what was rejected and why**,
  and what it cost. This is the heart of the site.

**Reference — "what exactly is it?"**
: Precise shapes: message formats, database tables, API endpoints. Look things up
  here; do not read it front to back.

**Guides — "how do I do a thing?"**
: Install a base station, run a demo without hardware, change the database safely.

## A note on how the decisions are written

Every journal entry follows the same four beats:

1. **What forced it** — the constraint, the bug, or the thing that broke
2. **What we chose**
3. **What we rejected, and why**
4. **What it cost** — the trade accepted, and what to watch for

The third beat is the one that matters. A decision recorded without its rejected
alternatives is just a description of the code, and it will not stop the next person
from re-opening a settled question.

```{toctree}
:maxdepth: 2

orientation
journal/index
reference/index
guides/index
history
```
