# The journal

One page per part of the system, ordered so the groundwork comes first.

**Read the backend pages before the screens.** Every screen is a view onto the same
database, the same endpoints, and the same message broker — and most of the decisions
that shape a screen were actually made underneath it. Reading a screen page first
means reading about consequences before causes.

## The groundwork

**{doc}`database`**
: The training hierarchy, the three different weights, and the rules that turn a
  percentage into a number on a bar.

**{doc}`apis`**
: The endpoints, who is allowed to call them, and where authentication lives.

**{doc}`real-time`**
: The message broker, what publishes to it, and why the server deliberately ignores
  most of it.

**{doc}`scripts`**
: The base station itself — provisioning, the Wi-Fi network it broadcasts, and how a
  gym gets from a blank machine to a running system.

## The screens

**{doc}`rack-tablet`**
: What the athlete uses. Also where the system's durability actually lives.

**{doc}`coach-tablet`**
: Login, wiring the room together, planning training, and spreadsheet upload.

**{doc}`dashboard`**
: The wall display.

## How each decision is written

Every entry follows the same four beats:

1. **What forced it** — the constraint, the bug, or the thing that broke
2. **What we chose**
3. **What we rejected, and why** — so nobody re-litigates a settled question
4. **What it cost** — the trade accepted, and what to watch for

The third beat is the one that matters most. A decision without its rejected
alternatives is just a description of the code.

```{toctree}
:maxdepth: 2
:caption: The groundwork

database
apis
real-time
scripts
```

```{toctree}
:maxdepth: 2
:caption: The screens

rack-tablet
coach-tablet
dashboard
```
