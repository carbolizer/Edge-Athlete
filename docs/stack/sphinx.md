# Sphinx and Read the Docs

**What it is.** What turns this folder of Markdown into the site you are reading.
Sphinx builds it; Read the Docs hosts it.

**How we use it.** Two versions, deliberately saying different things:

```
/en/latest/   builds from main       — the current docs
/en/stable/   builds from the newest release tag — what the gym is running
```

**Where it lives.** `docs/`. Settings in `docs/conf.py`, dependencies in
`docs/requirements.txt`, RTD's build config in `.readthedocs.yaml`.

**Worth knowing.** ⚠️ `conf.py` and `requirements.txt` must stay in step. An
extension listed in one and missing from the other kills the build — and Read the
Docs keeps serving the **last build that worked**, so the site stays up and silently
goes stale. That is exactly how it froze for weeks.

`fail_on_warning` is on, so one bad cross-reference fails the whole build.

Preview locally with `./docs/serve.sh`.

**More:** {doc}`../reference/versioning` for what the version numbers mean
