<!--
MIGRATION_PLAYBOOK.md — how to change the database safely in this repo.
Written as a handoff so schema changes aren't blocked on any one person. If you
are about to touch django/event_handler/models.py, read this first.
-->

# Migration Playbook

Django migrations are how every schema change (new table, new column, changed
column) gets applied to the database. This repo runs Django in Docker, which adds
one non-obvious step. Read the **first section** before your first migration — it's
the thing most likely to trip you up.

---

## ⚠️ The one gotcha: the container bakes the code

The `django` service has **no source-code volume mount** — its Dockerfile *copies*
the code in at build time. Two consequences:

1. **Editing a file on your machine does not change the running container** until
   you either rebuild the image or copy the file in. (During dev you can copy a
   file in fast: `docker cp <hostpath> edgeathlete-django:/backend_container/<same path>`.)
2. **A migration file that `makemigrations` generates is written *inside the
   container*, not on your machine.** If you don't copy it back to the repo, it
   vanishes the next time the image rebuilds — and any later migration that
   depends on it breaks the whole migration graph. This has already bitten us once.

**So every time you generate a migration, copy it back to the repo and commit it.**

```bash
# after makemigrations, find the new file name inside the container, then:
docker cp edgeathlete-django:/backend_container/event_handler/migrations/<NNNN_name>.py \
          django/event_handler/migrations/<NNNN_name>.py
git add django/event_handler/migrations/<NNNN_name>.py
```

---

## The everyday case: add a model, or add a field

This is 90% of migrations and it's easy.

1. Edit `django/event_handler/models.py`. Give any new model/file a WHY comment.
2. Sync + generate + apply:
   ```bash
   docker cp django/event_handler/models.py edgeathlete-django:/backend_container/event_handler/models.py
   docker exec edgeathlete-django python manage.py makemigrations event_handler
   docker exec edgeathlete-django python manage.py migrate event_handler
   ```
3. **Copy the new migration file back to the repo** (see the gotcha above) and commit it with the model change.
4. Sanity check — this must print "No changes detected":
   ```bash
   docker exec edgeathlete-django python manage.py makemigrations event_handler --check --dry-run
   ```

**Adding a non-null field to a table that already has rows?** Django will ask for a
default. Give one (`default=...`), or add the field as `null=True` first and
backfill — otherwise the migration can't fill existing rows.

---

## Rolling back

There are **no separate "down" files** — each migration reverses itself. Roll back
by migrating to the migration you want to *land on*; Django undoes everything after
it.

```bash
# undo everything after 0004 (i.e. unapply 0005):
docker exec edgeathlete-django python manage.py migrate event_handler 0004_tag_exercise
# see what's applied
docker exec edgeathlete-django python manage.py showmigrations event_handler
```

**Reversibility rule:** *schema* changes (add/drop table or column) reverse
automatically. A *data* migration (`RunPython`, e.g. backfilling rows) only
reverses if you wrote its reverse function. Always pass both directions:
`migrations.RunPython(forward, reverse)`. If a data step truly can't be reversed,
pass `migrations.RunPython.noop` for the reverse and say so in a comment.

---

## The hard case: changing a column's type (e.g. text → foreign key)

You can't just flip a `CharField` to a `ForeignKey` — the old text can't be cast to
a link, so data would be lost. The safe recipe (this is exactly what
`0005_link_models_to_exercise_catalog.py` does — read it as the worked example):

1. **Make the old column nullable** first (`AlterField ... null=True`) so the reverse
   can re-add it cleanly later.
2. **Add a temporary new column** (the FK), nullable.
3. **`RunPython` to backfill** — copy each old value into the new column, creating
   the target rows as needed (`get_or_create`). Write the reverse too (copy the
   name back).
4. **Drop the old column.**
5. **Rename the temp column** into the real name (`RenameField`).
6. **Make the new column non-null** (`AlterField`) now that every row is filled.

**Watch the indexes.** If the changed column is part of a DB index, dropping the
column *cascade-drops the index* out from under Django's migration state, and a
later auto-generated "rename index" migration will fail because the index no longer
exists. Handle it explicitly in the same migration: `RemoveIndex` the old one
*before* dropping the column, and `AddIndex` the new one *after* the column is in
final form. Give the index an **explicit `name=`** in the model's `Meta` so Django
never tries to auto-rename it again.

**Hand-write this kind of migration** rather than trusting `makemigrations` to
guess a multi-step, data-preserving conversion — then test it both ways (below).

---

## Always test a non-trivial migration both directions

On a database that has real (seeded) rows:

```bash
# forward is implicit on boot; to test the round trip:
docker exec edgeathlete-django python manage.py migrate event_handler <previous>   # reverse
#   -> verify the data came back the way it should (raw SQL is fine here)
docker exec edgeathlete-django python manage.py migrate event_handler              # forward again
#   -> verify the new shape is restored
```

If reverse errors or loses data, the migration isn't done yet.

---

## Before you merge — checklist

- [ ] Migration file(s) copied back into `django/event_handler/migrations/` and committed *with* the model change.
- [ ] `makemigrations --check --dry-run` prints "No changes detected" (model and migrations agree).
- [ ] `migrate` applies cleanly **from scratch** (test with a wiped DB: `docker compose down -v && docker compose up -d --build django`).
- [ ] Data migrations have a working reverse (or an explicit noop + comment).
- [ ] For a type change: tested forward → reverse → forward on seeded data with no loss.
- [ ] `manage.py check` is clean; the test suite passes.

---

## Nuking and rebuilding the dev database

When the dev DB gets into a weird state, the fastest clean reset (destroys all dev
data — you'll re-seed):

```bash
docker compose down -v                       # wipe the postgres volume
docker compose up -d --build django          # fresh DB, migrations run on boot
docker exec edgeathlete-django python manage.py seed_active_session --reset
```
