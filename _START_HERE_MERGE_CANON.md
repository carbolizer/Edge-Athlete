# 🧭 Merge Canon — FOLDED INTO `SPEC.md` (2026-07-30)

> **Do not read this file for decisions. Read [`SPEC.md`](SPEC.md).**

The merge is **complete**. All fifteen phases shipped and are tagged
`p1-complete` … `p15-complete`. This document was the authority while that work
was happening; everything in it that still matters now lives in `SPEC.md`, and
keeping a second copy here would guarantee the two drift apart.

## Where each part went

| Was here | Now |
|---|---|
| §2 Hard constraints — frozen files and frozen API contracts | `SPEC.md` § "2. Hard constraints" |
| §3 Governing principles | `SPEC.md` § "3. Governing principles" |
| §4 The `Training*` hierarchy | `SPEC.md` § "4. The `Training*` hierarchy" |
| §5.3, §5.4, §5.6 Schema rules, seed data, the two "colors" | `SPEC.md` § "5. Schema rules that are easy to get wrong" |
| **§6 The derivation rules** ⭐ | `SPEC.md` § "6. The derivation rules" |
| §9 Decision log (D1–D21) | `SPEC.md` § "9. Decision log" |
| §10 Explicitly deferred / out of scope | `SPEC.md` § "10. Explicitly deferred" |
| §0 Branch mechanics, `git show` recipes | **Dropped.** The merge is done; git history has it |
| §5.1 Model disposition, §5.5 migration plan | **Dropped.** The migrations themselves are the record |
| §7 Endpoint reconciliation (which of his routes survived) | **Dropped.** [`MESSAGE_CONTRACT.md`](MESSAGE_CONTRACT.md) holds the real shapes |
| §8 The P0–P15 phase plan and its gates | [`docs/PATCH_NOTES.md`](docs/PATCH_NOTES.md) — each phase with a click path |
| §8.1 P7 working notes, §11 Escalation | **Dropped.** Process notes for work that is finished |

**Section numbers were preserved in `SPEC.md` on purpose.** The text
cross-references them constantly (`see §6.3`, `per §4.1`), so renumbering would
have broken every reference for no benefit.

## What the merge was

Braydon's coach frontend merged onto the base station's API, without touching the
rack experience. The two things that could not be lost:

1. **The rack screen** — athlete-facing, frozen, ships today and works.
2. **The percentage-of-max idea** — a prescription is a percent of each athlete's
   own tested max, never a number of pounds.

Both survived. The frozen-file check ran at every one of the fifteen gates and was
clean every time.

## If you are looking for something specific

| Question | Read |
|---|---|
| How does a percentage become a weight on the bar? | `SPEC.md` §6.1 |
| What does an athlete in two groups train? | `SPEC.md` §6.2 |
| What can I not change about the rack contract? | `SPEC.md` §2.2 and §6.3 |
| Why is it built this way? | `SPEC.md` §9 — the decision log, D1–D21 |
| What changed on the branch, and how do I see it? | `docs/PATCH_NOTES.md` |
| What shape does this endpoint return? | `MESSAGE_CONTRACT.md` |

The older v1 canon, `_DEPRECATED_MERGE_CANON.md`, was already history before this
and remains so.
