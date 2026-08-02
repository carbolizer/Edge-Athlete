#!/usr/bin/env bash
# Runs the REAL setup.sh + startup.sh inside Debian, with the hardware-touching
# commands stubbed. Proves the parts that are actually script logic: where it
# decides the repo lives, what it writes into the systemd unit and the config
# file, and whether it is safe to run twice.
set -uo pipefail

STUBS=/tmp/stubs
mkdir -p "$STUBS"

# ── stubs ───────────────────────────────────────────────────────────────────
cat > "$STUBS/apt-get" <<'EOF'
#!/bin/sh
exit 0
EOF

cat > "$STUBS/systemctl" <<'EOF'
#!/bin/sh
echo "    [stub systemctl] $*" >> /tmp/calls.log
exit 0
EOF

cat > "$STUBS/hostnamectl" <<'EOF'
#!/bin/sh
echo "    [stub hostnamectl] $*" >> /tmp/calls.log
exit 0
EOF

# A machine WITH a wifi card, named something other than wlan0 so we can tell a
# detected value apart from the built-in default. Stateful on purpose: bringing
# a profile "up" fails until one has been added, which is what a real first boot
# does and what makes the create-then-raise branch worth testing.
cat > "$STUBS/nmcli" <<'EOF'
#!/bin/sh
echo "    [stub nmcli] $*" >> /tmp/calls.log
case "$*" in
  *"-f DEVICE,TYPE device"*) echo "enp0s31f6:ethernet"; echo "wlp2s0:wifi"; exit 0 ;;
  *"connection add"*) touch /tmp/ap_profile; exit 0 ;;
  *"connection up"*) [ -f /tmp/ap_profile ] && exit 0 || exit 1 ;;
esac
exit 0
EOF

cat > "$STUBS/docker" <<'EOF'
#!/bin/sh
echo "    [stub docker] $*" >> /tmp/calls.log
exit 0
EOF

cat > "$STUBS/curl" <<'EOF'
#!/bin/sh
echo "    [stub curl] $*" >> /tmp/calls.log
exit 0
EOF

chmod +x "$STUBS"/*
export PATH="$STUBS:$PATH"

pass=0; fail=0
check() {  # check <description> <expected-substring> <actual>
  if printf '%s' "$3" | grep -qF "$2"; then
    echo "  ok    $1"; pass=$((pass+1))
  else
    echo "  FAIL  $1"; echo "        wanted: $2"; echo "        got:    $3"; fail=$((fail+1))
  fi
}

# ── build a fake install, deliberately NOT at /srv ──────────────────────────
# The whole promise is "works from wherever it is cloned", so testing it at the
# documented path would prove nothing.
INSTALL=/opt/somewhere-else/Edge-Athlete
mkdir -p "$INSTALL"
cp -r /src/scripts "$INSTALL/"
cp /src/docker-compose.yml /src/.env.example "$INSTALL/"

echo
echo "=== run 1: fresh provision from $INSTALL ==="
: > /tmp/calls.log
out1=$("$INSTALL/scripts/basestation/setup.sh" 2>&1)
rc1=$?
echo "$out1" | sed 's/^/    /'

echo
echo "--- assertions ---"
check "exits 0" "0" "$rc1"
check "finds the repo where it actually is" "found the repo at $INSTALL" "$out1"
check "detects the real wifi name, not the default" "found: wlp2s0" "$out1"
check "creates .env" "created .env from .env.example" "$out1"

# The shipped SECRET_KEY is public (it is committed in .env.example) and it signs
# coach logins, so provisioning must replace it with a unique one.
env_key=$(grep '^SECRET_KEY=' "$INSTALL/.env" | cut -d= -f2-)
check "generates a SECRET_KEY on first provision" "generated a unique SECRET_KEY" "$out1"
check "the shipped public key is gone from .env" "0" \
      "$(grep -c 'django-insecure' "$INSTALL/.env")"
check "the new key is a real length (not blank)" "yes" \
      "$([ "${#env_key}" -ge 40 ] && echo yes || echo "no:${#env_key}")"

unit=$(cat /etc/systemd/system/edgeathlete.service 2>&1)
check "systemd ExecStart uses the resolved path" \
      "ExecStart=$INSTALL/scripts/basestation/startup.sh" "$unit"
check "systemd unit has no /home/pi left in it" "" "$(echo "$unit" | grep -c '/home/pi' | grep '^0$')"

# The Wi-Fi-change agent's units must be installed and point at the resolved repo.
apply_unit=$(cat /etc/systemd/system/edgeathlete-wifi-apply.service 2>&1)
check "installs the wifi-apply service at the resolved path" \
      "ExecStart=$INSTALL/scripts/basestation/apply-wifi.sh" "$apply_unit"
apply_path=$(cat /etc/systemd/system/edgeathlete-wifi-apply.path 2>&1)
check "installs the wifi-apply path-watcher on the spool file" \
      "PathExists=/var/lib/edgeathlete/wifi-apply.request" "$apply_path"

conf=$(cat /etc/edgeathlete/basestation.conf 2>&1)
check "config records the detected interface" 'WIFI_IFACE="wlp2s0"' "$conf"
check "config is outside the repo" "AP_PASSWORD" "$conf"
perms=$(stat -c '%a' /etc/edgeathlete/basestation.conf)
check "config is chmod 600 (holds the wifi password)" "600" "$perms"

# The old script rewrote startup.sh in place; this must not.
dirty=$(grep -c 'wlp2s0' "$INSTALL/scripts/basestation/startup.sh" || true)
check "startup.sh was NOT rewritten (repo stays clean)" "0" "$dirty"

echo
echo "=== run 2: re-running setup must be safe ==="
# Someone has changed the password by now. Re-provisioning must not stamp on it.
sed -i 's/ChangeMe123!/RealGymPassword/' /etc/edgeathlete/basestation.conf
echo "CUSTOM=1" >> "$INSTALL/.env"
key_after_run1=$(grep '^SECRET_KEY=' "$INSTALL/.env" | cut -d= -f2-)
out2=$("$INSTALL/scripts/basestation/setup.sh" 2>&1)
rc2=$?
echo "$out2" | sed 's/^/    /'

echo
echo "--- assertions ---"
check "exits 0 the second time" "0" "$rc2"
check "does not clobber an existing config" "left alone (delete it to regenerate)" "$out2"
check "kept the changed password" "RealGymPassword" "$(cat /etc/edgeathlete/basestation.conf)"
check "does not clobber an existing .env" ".env already exists, left alone" "$out2"
check "kept local .env edits" "CUSTOM=1" "$(cat "$INSTALL/.env")"
# ⚠️ The key must NOT be rotated on re-provision — doing so would log every coach
# out on every update. Once it is real, it is left exactly as-is.
check "does not regenerate an already-real SECRET_KEY" "already customised" "$out2"
check "the key is byte-identical to run 1" "$key_after_run1" \
      "$(grep '^SECRET_KEY=' "$INSTALL/.env" | cut -d= -f2-)"

echo
echo "=== run 3: startup.sh ==="
: > /tmp/calls.log
out3=$("$INSTALL/scripts/basestation/startup.sh" 2>&1)
rc3=$?
echo "$out3" | sed 's/^/    /'

echo
echo "--- assertions ---"
check "exits 0" "0" "$rc3"
check "reads the config file, not its own defaults" "settings from /etc/edgeathlete/basestation.conf" "$out3"
check "starts the stack from the resolved dir" "Docker stack from $INSTALL" "$out3"
check "creates the AP profile on the DETECTED interface" "ifname wlp2s0" "$(cat /tmp/calls.log)"
check "uses the changed password, not the default" "RealGymPassword" "$(cat /tmp/calls.log)"
check "no default-password warning once it is changed" "" \
      "$(echo "$out3" | grep -c 'STILL THE DEFAULT' | grep '^0$')"

echo
echo "=== run 3b: the AP fails — the app must come up anyway ==="
# The regression this guards: under `set -e` a failing nmcli killed the boot
# script before `docker compose up`, leaving a box with no gym Wi-Fi AND no
# application — unreachable even over a cable, with nothing in the log.
rm -f /tmp/ap_profile
cat > "$STUBS/nmcli" <<'EOF'
#!/bin/sh
echo "    [stub nmcli] $*" >> /tmp/calls.log
case "$*" in
  *"-f DEVICE,TYPE device"*) echo "wlp2s0:wifi"; exit 0 ;;
esac
exit 1                      # this adapter cannot do AP mode
EOF
chmod +x "$STUBS/nmcli"
: > /tmp/calls.log
out3b=$("$INSTALL/scripts/basestation/startup.sh" 2>&1); rc3b=$?
echo "$out3b" | sed 's/^/    /'
echo
echo "--- assertions ---"
check "does not die when the AP cannot start" "0" "$rc3b"
# `up -d` (not the contiguous "compose up -d") because the real call now carries
# -f overlay args between "compose" and "up".
check "STILL starts the docker stack" "up -d" "$(cat /tmp/calls.log)"
check "shouts about the missing gym network" "COULD NOT START THE ACCESS POINT" "$out3b"
check "tells you how to check the adapter" "Supported interface modes" "$out3b"
check "final line does not claim everything is fine" "NO GYM WI-FI" "$out3b"

echo
echo "=== run 4: a machine with NO wifi card must fail loudly ==="
cat > "$STUBS/nmcli" <<'EOF'
#!/bin/sh
case "$*" in
  *"-f DEVICE,TYPE device"*) echo "enp0s31f6:ethernet" ;;
esac
exit 0
EOF
chmod +x "$STUBS/nmcli"
rm -f /etc/edgeathlete/basestation.conf
out4=$("$INSTALL/scripts/basestation/setup.sh" 2>&1); rc4=$?
check "refuses rather than provisioning a station with no gym network" "1" "$rc4"
check "says what to check" "lspci" "$out4"

echo
echo "=== run 5: script moved out of the repo must refuse ==="
mkdir -p /tmp/loose/scripts/basestation
cp "$INSTALL/scripts/basestation/setup.sh" /tmp/loose/scripts/basestation/
out5=$(/tmp/loose/scripts/basestation/setup.sh 2>&1); rc5=$?
check "refuses when there is no docker-compose.yml above it" "1" "$rc5"
check "explains why" "must stay inside the repo" "$out5"

echo
echo "============================================"
echo "  passed: $pass    failed: $fail"
echo "============================================"
[ "$fail" -eq 0 ]
