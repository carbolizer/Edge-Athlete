#!/usr/bin/env bash
#
# serve.sh — see the docs site update as you type.
#
# Starts a local copy of the documentation website that rebuilds itself every time
# you save a file, and refreshes the browser for you. Write in whatever editor you
# like (Obsidian, Typora, VS Code) on one side, watch the real published page update
# on the other. Nothing here touches the live site.
#
# Run it:   ./docs/serve.sh          then open the URL it prints
# Stop it:  Ctrl-C
#
# WHY A VENV AND NOT HOMEBREW
# `brew install sphinx-doc` gives you Sphinx on its own, and these docs need three
# more packages it does not include: myst-parser (so Sphinx can read Markdown at
# all), furo (the theme), and sphinxcontrib-mermaid (the database diagram). Homebrew's
# Python also refuses `pip install` because it manages its own packages — that is the
# "externally-managed-environment" error, not something you did wrong.
#
# So the toolchain lives in `docs/venv/`, which is gitignored. It installs from the
# same requirements.txt that Read the Docs uses, which means a build that works here
# works there.
#
set -euo pipefail

DOCS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DOCS_DIR/venv"

# First run, or someone deleted the venv: build it.
if [ ! -x "$VENV/bin/sphinx-autobuild" ]; then
    echo "[*] setting up the docs toolchain in docs/venv (one time)..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip3" install -q --upgrade pip
    "$VENV/bin/pip3" install -q -r "$DOCS_DIR/requirements.txt" sphinx-autobuild
    echo "[*] done"
fi

echo "[*] building — the page will open at http://127.0.0.1:8000"
echo "[*] save any .md file and the browser refreshes itself. Ctrl-C to stop."
echo

# --watch picks up conf.py and custom.css too, not just the pages.
# Warnings are NOT fatal here on purpose: while you are mid-sentence a half-finished
# cross-reference is normal, and a hard failure would just be noise. Read the Docs
# still enforces them on publish, so a genuine mistake cannot reach the live site.
exec "$VENV/bin/sphinx-autobuild" \
    --watch "$DOCS_DIR/_static" \
    --ignore "$DOCS_DIR/venv/*" \
    --ignore "*.tmp" \
    --open-browser \
    "$DOCS_DIR" "$DOCS_DIR/_build/html"
