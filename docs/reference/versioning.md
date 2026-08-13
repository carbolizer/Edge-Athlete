<!--
this page — what our version numbers mean, and when each part moves.

Written because "why 0.2.0 and not 0.1.1?" came up while tagging the retro build,
and the answer is a convention rather than a preference. Short on purpose: the
rules fit on one screen, and a versioning policy nobody can hold in their head is
a policy nobody follows.
-->

# Version numbers

We use **semantic versioning** — `MAJOR.MINOR.PATCH`, as in `v0.2.0`.

## What the three parts are for

Three numbers instead of one because they answer a question a single counter
cannot: **what breaks if I upgrade?**

| Part | Moves when | What it promises |
|---|---|---|
| **PATCH** — `0.2.`**`1`** | bug fixes only | nothing changes except the bug |
| **MINOR** — `0.`**`3`**`.0` | new features, backwards compatible | what you already use still works |
| **MAJOR** — **`1`**`.0.0` | breaking changes | something you depended on is gone or different |

"v47" tells you a build is newer. It does not tell you whether upgrading costs you
an afternoon. That is the whole reason for the extra two numbers.

When a release contains several kinds of change, **the highest one wins**: a
release with new features and bug fixes is a MINOR bump, not both.

:::{admonition} A worked example from this repo
:class: tip
`v0.2.0` covered 30 commits: the WT901 and NFC agents, QoS 1 end to end, the
coach's release and unlink controls, `ea-reset`, `ea-rotate`, and a pile of fixes.

It was tagged MINOR rather than PATCH because it **added** things — new endpoints,
new commands. Nothing was removed or reshaped, so it was not MAJOR either. The
count of commits had nothing to do with it; thirty bug fixes would still have been
a PATCH.
:::

## Why we are still on `0.x`

The leading zero is itself a statement: **the shape may still change under you.**
Under semantic versioning, `0.x` is explicitly the unstable phase — even a
breaking change only moves the MINOR number while the major is zero.

That is an honest description of where this project is:

- the frozen-contract files can still move
- insights and fatigue detection are stubs that return nothing
- the ESP32 firmware is not in this repository
- the broker still allows anonymous connections

## What `1.0.0` would mean

Not "it works" — it already works. `1.0.0` is a **promise of stability**, and the
promise is the expensive part: after it, breaking anything costs a MAJOR bump and
everyone downstream has to care.

The reasonable trigger here is **a gym that is not ours running a full season on
it**. Real users, on hardware we did not set up, depending on an API we are no
longer free to reshape on a whim.

Until then `0.x` is not modesty. It is the accurate label.

## Pre-releases: the `-rc.N` suffix

A suffix marks a version as **not the real thing yet**, and it sorts *below* the
release it precedes:

```
v0.1.0-rc.1  <  v0.1.0-rc.6  <  v0.1.0
```

Useful for "this is what we intend to ship, try it" without claiming it shipped.

:::{admonition} They are invisible to tooling that wants a stable version
:class: warning
Read the Docs builds its `stable` version from the highest **non-pre-release**
tag. With only `v0.1.0-rc.1` … `rc.6` in the repo, it had nothing to build from and
`stable` did not exist — the docs site had no released version at all until a plain
`v0.1.0` was tagged.

That behaviour is correct and not specific to Read the Docs. Package managers do
the same. If a tool seems to be ignoring your newest tag, check whether it is a
pre-release.
:::

## Tagging a release

```bash
git tag -a v0.3.0 -m "what changed, and what is knowingly incomplete"
git push origin v0.3.0
```

Annotated (`-a`), not lightweight, so the tag carries a message, an author and a
date of its own.

Two things worth putting in that message, from experience rather than principle:

**What is knowingly incomplete.** `v0.2.0` records that the WT901 agent publishes
no reps without an opt-in flag, and that clearing a rack discards buffered reps.
Both are deliberate. Written down, they are decisions; left out, they read as bugs
somebody missed.

**Nothing that is only true today.** A tag is read months later, by someone who was
not in the room.

:::{admonition} Tags are not backups
:class: warning
A tag is a label on a commit, not a copy of it. If the commit stops being reachable
from any branch, the tag is the only thing keeping it alive — and deleting the tag
orphans it.

This repo had fifteen `p*-complete` tags in exactly that state: the merge phases
had been rebased, so those commits were on no branch at all. They were safe to
delete only because every one had a byte-identical tree already on `main`. That was
worth checking before deleting rather than after.
:::
