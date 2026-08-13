#!/usr/bin/env bash
#
# install-hooks.sh — turn on this repo's git hooks.
#
# Git hooks live in .git/hooks, which is NOT part of the repository — cloning does not
# bring them along. So the hooks themselves are kept in scripts/hooks (tracked, and
# reviewable like any other code) and this points git at that folder.
#
# Run once after cloning:
#     ./scripts/install-hooks.sh
#
# What you get: committing a change to the database models refreshes the schema tables
# in the docs and includes them in the same commit. See scripts/hooks/pre-commit.
#
# To turn it off again:
#     git config --unset core.hooksPath
#
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"

chmod +x scripts/hooks/* 2>/dev/null || true

# One setting, rather than copying files into .git/hooks — so an update to a hook
# reaches everyone on the next pull instead of needing a re-install.
git config core.hooksPath scripts/hooks

echo "[✓] hooks enabled (core.hooksPath = scripts/hooks)"
echo
echo "    active:"
for h in scripts/hooks/*; do
    [ -f "$h" ] && echo "      $(basename "$h")"
done
echo
echo "    skip them for one commit with:  git commit --no-verify"
