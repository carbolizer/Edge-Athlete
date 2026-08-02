#!/usr/bin/env bash
# Exercises bootstrap.sh — the one-command install — against a REAL git remote
# (a local bare repo holding the working tree), so the clone/update logic is the
# genuine article rather than a stub.
set -uo pipefail

STUBS=/tmp/stubs; mkdir -p "$STUBS"
for c in apt-get systemctl hostnamectl docker; do
  printf '#!/bin/sh\nexit 0\n' > "$STUBS/$c"
done
cat > "$STUBS/nmcli" <<'EOF'
#!/bin/sh
case "$*" in *"-f DEVICE,TYPE device"*) echo "wlp2s0:wifi"; exit 0 ;; esac
exit 0
EOF
printf '#!/bin/sh\nexit 0\n' > "$STUBS/curl"
chmod +x "$STUBS"/*
export PATH="$STUBS:$PATH"
export GIT_CONFIG_GLOBAL=/tmp/gitconfig
git config --global user.email t@t.t; git config --global user.name t
git config --global init.defaultBranch main

pass=0; fail=0
check() {
  if printf '%s' "$3" | grep -qF "$2"; then echo "  ok    $1"; pass=$((pass+1))
  else echo "  FAIL  $1"; echo "        wanted: $2"; echo "        got:    $3"; fail=$((fail+1)); fi
}

# ── a fake origin holding the real working tree ─────────────────────────────
echo "=== building a local remote on branch SprintBranch ==="
mkdir -p /tmp/src && cp -r /src/scripts /tmp/src/ \
  && cp /src/docker-compose.yml /src/.env.example /tmp/src/
cd /tmp/src
git init -q && git checkout -qb SprintBranch && git add -A && git commit -qm "base"
git clone -q --bare /tmp/src /tmp/origin.git
# /tmp/src was init'd, not cloned, so it has no `origin` to push back to. Without
# this the "upstream moved on" step below silently does nothing and the update
# test passes for the wrong reason.
git remote add origin /tmp/origin.git
echo "    origin has: $(git --git-dir=/tmp/origin.git branch --format='%(refname:short)' | tr '\n' ' ')"

export EDGE_REPO_URL=file:///tmp/origin.git
export EDGE_HOME=/srv/edge-athlete

echo
echo "=== run 1: fresh machine, one command ==="
out1=$(bash /tmp/src/scripts/basestation/bootstrap.sh 2>&1); rc1=$?
echo "$out1" | sed 's/^/    /'
echo
echo "--- assertions ---"
check "exits 0" "0" "$rc1"
check "lands at the documented path" "found the repo at /srv/edge-athlete/Edge-Athlete" "$out1"
check "keeps the repo's own name (Edge-Athlete, not edge-athlete)" "Edge-Athlete" \
      "$(ls /srv/edge-athlete)"
check "does NOT create a lowercase twin" "1" "$(ls /srv/edge-athlete | wc -l | tr -d ' ')"
check "checks out the pinned branch, not the default" "SprintBranch" \
      "$(git -C /srv/edge-athlete/Edge-Athlete rev-parse --abbrev-ref HEAD)"
check "hands off to setup, which provisions" "setup complete" "$out1"
check "boot service points into the install" \
      "ExecStart=/srv/edge-athlete/Edge-Athlete/scripts/basestation/startup.sh" \
      "$(cat /etc/systemd/system/edgeathlete.service)"

echo
echo "=== run 2: same command again = update in place ==="
# New commit upstream, and someone has poked a tracked file on the base station.
cd /tmp/src && echo "# upstream change" >> docker-compose.yml \
  && git commit -qam "upstream moves on" \
  && git push -q origin SprintBranch \
  || { echo "    [test setup] PUSH FAILED — the update test would be meaningless"; exit 1; }
echo "LOCAL EDIT" >> /srv/edge-athlete/Edge-Athlete/docker-compose.yml
echo "KEEP=1" >> /srv/edge-athlete/Edge-Athlete/.env

out2=$(bash /tmp/src/scripts/basestation/bootstrap.sh 2>&1); rc2=$?
echo "$out2" | sed 's/^/    /'
echo
echo "--- assertions ---"
check "exits 0" "0" "$rc2"
check "recognises an existing install" "already installed, updating" "$out2"
check "picks up the upstream change" "upstream change" \
      "$(cat /srv/edge-athlete/Edge-Athlete/docker-compose.yml)"
# The reason this is `fetch + reset --hard` and not `git pull`: a stray local
# edit on an unattended box must never turn an update into a merge conflict.
check "discards local edits to TRACKED files rather than conflicting" "0" \
      "$(grep -c 'LOCAL EDIT' /srv/edge-athlete/Edge-Athlete/docker-compose.yml)"
check "leaves .env alone — it is untracked, and it is the machine's own" "KEEP=1" \
      "$(cat /srv/edge-athlete/Edge-Athlete/.env)"
check "leaves the machine config alone" "wlp2s0" "$(cat /etc/edgeathlete/basestation.conf)"

echo
echo "============================================"
echo "  passed: $pass    failed: $fail"
echo "============================================"
[ "$fail" -eq 0 ]
