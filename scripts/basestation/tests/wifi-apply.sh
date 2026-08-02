#!/usr/bin/env bash
# Exercises apply-wifi.sh — the privileged host agent that applies a Wi-Fi
# password change — with nmcli stubbed. Proves the script LOGIC: it reads the
# request, validates it, updates the config, calls nmcli with the right psk, and
# consumes the request. It cannot prove nmcli actually re-keys a real radio;
# nothing but hardware can. Same deal as the startup.sh tests.
set -uo pipefail

SRC=/src/scripts/basestation/apply-wifi.sh

STUBS=/tmp/stubs
mkdir -p "$STUBS"
# Stub nmcli: log every call so we can assert what the applier asked for.
cat > "$STUBS/nmcli" <<'EOF'
#!/bin/sh
echo "nmcli $*" >> /tmp/nmcli.log
exit 0
EOF
chmod +x "$STUBS"/*
export PATH="$STUBS:$PATH"

pass=0; fail=0
check() {
  if printf '%s' "$3" | grep -qF "$2"; then echo "  ok    $1"; pass=$((pass+1))
  else echo "  FAIL  $1"; echo "        wanted: $2"; echo "        got:    $3"; fail=$((fail+1)); fi
}

# Fresh sandbox for each scenario: a config file + a state dir with a request.
setup_case() {
  rm -rf /tmp/etc /tmp/state /tmp/nmcli.log
  mkdir -p /tmp/etc /tmp/state
  cat > /tmp/etc/basestation.conf <<EOF
AP_NAME="EdgeAthlete"
AP_PASSWORD="ChangeMe123!"
WIFI_IFACE="wlp2s0"
CONNECTION_NAME="EdgeAthlete-AP"
AP_IP_CIDR="192.168.4.1/24"
EOF
  printf '%s\n' "$1" > /tmp/state/wifi-apply.request
}
run() { EDGE_CONFIG=/tmp/etc/basestation.conf EDGE_STATE=/tmp/state bash "$SRC" 2>&1; }

echo "=== a valid change is applied live and persisted ==="
setup_case "GymFloor2026!"
out=$(run); rc=$?
echo "$out" | sed 's/^/    /'
check "exits 0" "0" "$rc"
check "tells nmcli the NEW psk" 'psk GymFloor2026!' "$(cat /tmp/nmcli.log)"
check "modifies the right connection profile" 'modify EdgeAthlete-AP' "$(cat /tmp/nmcli.log)"
check "brings the AP back up" 'connection up EdgeAthlete-AP' "$(cat /tmp/nmcli.log)"
check "writes the new password into the config" 'AP_PASSWORD="GymFloor2026!"' "$(cat /tmp/etc/basestation.conf)"
check "left no old default password behind" "0" "$(grep -c 'ChangeMe123' /tmp/etc/basestation.conf)"
check "consumes the request (no re-trigger loop)" "gone" \
      "$([ -f /tmp/state/wifi-apply.request ] && echo present || echo gone)"
check "config stays chmod 600" "600" "$(stat -c '%a' /tmp/etc/basestation.conf)"

echo
echo "=== a too-short password is refused and the AP is left ALONE ==="
setup_case "short"
out=$(run); rc=$?
echo "$out" | sed 's/^/    /'
check "exits non-zero" "1" "$rc"
check "never calls nmcli" "0" "$([ -f /tmp/nmcli.log ] && wc -l < /tmp/nmcli.log | tr -d ' ' || echo 0)"
check "leaves the old password in the config" 'AP_PASSWORD="ChangeMe123!"' "$(cat /tmp/etc/basestation.conf)"
# ⚠️ still consumed, so a bad request cannot re-fire the path-unit forever.
check "still consumes the bad request" "gone" \
      "$([ -f /tmp/state/wifi-apply.request ] && echo present || echo gone)"

echo
echo "=== a non-ASCII password is refused ==="
setup_case "café-wifi-pass"
out=$(run); rc=$?
check "exits non-zero" "1" "$rc"
check "never calls nmcli" "0" "$([ -f /tmp/nmcli.log ] && wc -l < /tmp/nmcli.log | tr -d ' ' || echo 0)"

echo
echo "=== no request file is a no-op, not an error ==="
rm -rf /tmp/etc /tmp/state /tmp/nmcli.log
mkdir -p /tmp/etc /tmp/state
out=$(EDGE_CONFIG=/tmp/etc/basestation.conf EDGE_STATE=/tmp/state bash "$SRC" 2>&1); rc=$?
check "exits 0 with nothing to do" "0" "$rc"
check "does not call nmcli" "0" "$([ -f /tmp/nmcli.log ] && wc -l < /tmp/nmcli.log | tr -d ' ' || echo 0)"

echo
echo "=== a password with a shell-special character survives intact ==="
# The reason the config write strips + re-appends instead of sed: a password can
# contain &, /, $ etc. Prove one lands byte-for-byte.
setup_case 'a$b&c/d=e_f'
run >/dev/null 2>&1
check "special-char password written verbatim to config" 'AP_PASSWORD="a$b&c/d=e_f"' \
      "$(cat /tmp/etc/basestation.conf)"
check "special-char password passed verbatim to nmcli" 'psk a$b&c/d=e_f' "$(cat /tmp/nmcli.log)"

echo
echo "============================================"
echo "  passed: $pass    failed: $fail"
echo "============================================"
[ "$fail" -eq 0 ]
