<!--
this guide — changing the database, on one screen.

It used to be a 155-line playbook that opened with a wall of caveats about type
changes and index cascades. All still true, all still here, but folded into
dropdowns: 90% of migrations are "add a field", and that person should not have to
scroll past the 10% case to find the two commands they need. Same rule as the base
station guide — if you add to this file, add inside a dropdown.
-->

# Changing the database

:::{note}
The commands. For what the schema means and the rules behind it, see
{doc}`../journal/database`.
:::

**Django owns the schema.** You edit `django/event_handler/models.py`, Django works
out what changed, and writes a numbered migration file. You never write SQL, and
you never edit the database by hand — if the models and the migrations disagree,
the models are the intent and the migrations are the record.

## The commands

Everything runs inside the `django` container, so every command is prefixed
`docker exec edgeathlete-django python manage.py`. Shortened to `manage.py` below.

| To do this | Run |
|---|---|
| **Generate** a migration after editing models | `manage.py makemigrations event_handler` |
| **Apply** it | `manage.py migrate event_handler` |
| **See** what is applied | `manage.py showmigrations event_handler` |
| **Rewind** to a migration (undoes everything after it) | `manage.py migrate event_handler 0004_tag_exercise` |
| **Check** models and migrations agree | `manage.py makemigrations event_handler --check --dry-run` |
| **Wipe and rebuild** the dev database | `docker compose down -v && docker compose up -d --build django` |
| **Same, on a base station** | `ea-reset-hard` |

`--check --dry-run` printing **"No changes detected"** is the one to remember. It
means the models and the migration files agree, which is the whole contract.

There are no separate "down" files. Each migration reverses itself, so you rewind
by naming the migration you want to *land on*.

:::{danger}
**A migration you generate is written INSIDE the container, and the container bakes
the code.** The `django` service copies the source in at build time — there is no
volume mount — so a new migration file does not exist on your machine until you
copy it out, and it vanishes on the next rebuild. Any later migration that depends
on it then breaks the whole graph. This has already happened once.

```bash
docker cp edgeathlete-django:/backend_container/event_handler/migrations/<NNNN_name>.py \
          django/event_handler/migrations/<NNNN_name>.py
```

Commit it **with** the model change, never after.
:::

## The everyday case

:::{dropdown} Add a model, or add a field — 90% of migrations

1. Edit `django/event_handler/models.py`. Give any new model a WHY comment.
2. Copy it in, generate, apply:
   ```bash
   docker cp django/event_handler/models.py edgeathlete-django:/backend_container/event_handler/models.py
   docker exec edgeathlete-django python manage.py makemigrations event_handler
   docker exec edgeathlete-django python manage.py migrate event_handler
   ```
3. Copy the migration back out (see the warning above) and commit both together.
4. Confirm `makemigrations --check --dry-run` says "No changes detected".

**Adding a non-null field to a table that already has rows?** Django will ask for a
default. Give one, or add it as `null=True` and backfill — otherwise there is
nothing to put in the existing rows.
:::

:::{dropdown} Rewinding, and when a migration will not reverse

*Schema* changes reverse automatically — adding or dropping a table or column is
mechanical.

A *data* migration only reverses if you wrote the reverse yourself. Always pass
both directions: `migrations.RunPython(forward, reverse)`. If a step genuinely
cannot be undone, pass `migrations.RunPython.noop` and say why in a comment, so the
next person knows it was a decision rather than an oversight.
:::

## The hard cases

:::{dropdown} Changing a column's type (text → foreign key)

You cannot flip a `CharField` to a `ForeignKey` — the old text cannot be cast to a
link, so the data would be dropped. `0005_link_models_to_exercise_catalog.py` is
the worked example; read it alongside this.

1. Make the old column nullable, so the reverse can re-add it cleanly.
2. Add the new FK column, nullable.
3. `RunPython` to backfill — copy each old value across, `get_or_create` the target
   rows. Write the reverse too.
4. Drop the old column.
5. `RenameField` the temp column into the real name.
6. `AlterField` it to non-null, now that every row is filled.

**Watch the indexes.** If the column is part of an index, dropping it
cascade-drops the index out from under Django's migration state, and a later
auto-generated "rename index" migration fails because the index is already gone.
`RemoveIndex` before the drop, `AddIndex` after the column is in final form, and
give the index an explicit `name=` in `Meta` so Django never tries to rename it
again.

**Hand-write this kind of migration.** `makemigrations` guesses, and a guess at a
multi-step data-preserving conversion is not something to find out about later.
:::

:::{dropdown} Testing a non-trivial migration both ways

On a database with real (seeded) rows, not an empty one:

```bash
docker exec edgeathlete-django python manage.py migrate event_handler <previous>   # reverse
docker exec edgeathlete-django python manage.py migrate event_handler              # forward again
```

Check the data came back correctly after the reverse, and that the new shape is
restored after the second forward. If reverse errors or loses rows, the migration
is not finished.
:::

:::{dropdown} Before you merge

- [ ] Migration file(s) copied into `django/event_handler/migrations/` and committed **with** the model change
- [ ] `makemigrations --check --dry-run` prints "No changes detected"
- [ ] `migrate` applies cleanly **from scratch** on a wiped database
- [ ] Data migrations have a working reverse, or an explicit noop and a comment
- [ ] A type change was tested forward → reverse → forward on seeded data, with no loss
- [ ] `manage.py check` is clean and the test suite passes
:::
