#!/usr/bin/env bash
# setup.sh — one-time Edge Athlete base-station provisioner.
#
# Installs everything the base station needs (NetworkManager, Docker), writes
# the machine's own config file, and installs the systemd service that runs
# startup.sh on every boot. After this the box comes up as its own Wi-Fi access
# point with the whole stack running.
#
# Normally you never call this directly — bootstrap.sh does, right after it
# clones the repo. Run it by hand only to re-provision an existing install:
#
#   sudo /srv/edge-athlete/Edge-Athlete/scripts/basestation/setup.sh
#
# IT WORKS FROM WHEREVER THE REPO IS. Nothing below hardcodes a path; the script
# finds the repo root from its own location. Clone to /srv, /opt, or a home
# directory while testing — it provisions whatever it is sitting in. The old Pi
# version hardcoded /home/pi/edge-athlete, so the base station depended on which
# user was logged in and on the repo being renamed after cloning.
#
# HARDWARE: this targets an ordinary x86 mini PC (a Dell OptiPlex) running
# Debian or Ubuntu. The Raspberry Pi's MT7601U USB Wi-Fi firmware step is gone —
# it only ever existed for the dongle on the Pi, and copying firmware for a
# chipset that isn't present did nothing but confuse the log.

set -euo pipefail

# ── where am I? ─────────────────────────────────────────────────────────────
# Resolve the repo root from this script's own path (scripts/basestation/ -> up
# two). `pwd -P` resolves symlinks, so a symlinked install still lands on the
# real directory rather than one that vanishes on the next boot.
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../.." >/dev/null 2>&1 && pwd -P)"

CONFIG_DIR="/etc/edgeathlete"
CONFIG_FILE="$CONFIG_DIR/basestation.conf"
STATE_DIR="/var/lib/edgeathlete"
SERVICE_FILE="/etc/systemd/system/edgeathlete.service"

if [ "$(id -u)" -ne 0 ]; then
    echo "[!] please run as root: sudo $0"
    exit 1
fi

# Prove we actually found the repo before touching the machine. A wrong
# PROJECT_DIR would otherwise surface much later, as a boot service that fails
# every reboot for no visible reason.
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
    echo "[!] no docker-compose.yml at $PROJECT_DIR"
    echo "[!] this script must stay inside the repo, at scripts/basestation/setup.sh"
    exit 1
fi

echo "[1] found the repo at $PROJECT_DIR"
cd "$PROJECT_DIR"

echo "[2] installing required tools..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# Only what the scripts actually use: NetworkManager (nmcli runs the AP), iw (the
# AP-mode capability check), git/curl/certs. The old wireless-tools (iwconfig)
# and net-tools (ifconfig) were carried over from the Pi port and used nowhere —
# and Ubuntu 26.04 dropped wireless-tools entirely, so asking for it aborted the
# whole install with "no installation candidate". nmcli + iw cover everything.
apt-get install -y -qq \
  ca-certificates \
  curl \
  git \
  network-manager \
  iw

echo "[3] installing Docker..."
# Docker's own installer, not the distro's docker.io. The distro packages split
# Docker and Compose across releases and lag badly — on some Ubuntu versions
# `docker compose` simply isn't there — and this stack is nothing without
# Compose v2. Skipped entirely when Docker is already present, so re-running
# setup never reinstalls it.
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "    already present, skipping"
else
    curl -fsSL https://get.docker.com | sh
fi

echo "[3b] installing Chromium (on the host, not in a container)..."
# WHY IT IS NOT IN A CONTAINER, since everything else here is.
# Chromium is not a service — it is a program that has to draw on THIS machine's
# physical screen and take input from its keyboard. Containerising it means handing
# a container the X/Wayland socket, the GPU device nodes, and audio, which is more
# host access than the whole rest of the stack has combined, in exchange for nothing.
# The browser is a desktop application. It belongs on the desktop.
#
# WHY THE BASE STATION NEEDS ONE AT ALL. Two jobs: driving a wall display off this
# machine's own HDMI output, and demoing all three screens on one box without three
# tablets. Both go through scripts/basestation/basestation-kiosk.sh.
#
# Package name differs by image: chromium-browser on older Debian/Ubuntu, chromium
# on newer. Try both, and do NOT fail setup if neither exists — a base station with
# no monitor attached does not need a browser, and a headless install should not
# die at this step. The kiosk scripts report the absence clearly if you later try
# to use one.
#
# ⚠️ ON UBUNTU BOTH PACKAGE NAMES INSTALL A SNAP, and a snap cannot read the kiosk
# profile directory under /var/lib — it is confined to home directories. kiosk.sh
# detects this and falls back with an explanation, so nothing breaks silently, but
# the real fix on Ubuntu is Google Chrome's .deb. Debian and Raspberry Pi OS ship a
# normal package and are unaffected.
if command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1; then
    echo "    already present, skipping"
else
    apt-get install -y -qq chromium 2>/dev/null \
      || apt-get install -y -qq chromium-browser 2>/dev/null \
      || echo "    [!] no chromium package found — the base station cannot drive a" \
              "screen itself. Harmless if it is headless."
fi

# unclutter hides the mouse pointer on a kiosk screen; x11-xserver-utils provides
# xset, which is how kiosk.sh stops the display blanking mid-set. Both are tiny and
# both are useless without a screen, so they ride along with Chromium.
apt-get install -y -qq unclutter x11-xserver-utils 2>/dev/null || true

echo "[4] enabling services..."
systemctl enable --now NetworkManager
systemctl enable --now docker

echo "[4b] making sure NetworkManager owns the network..."
# ⚠️ UBUNTU SERVER TRAP. Its default renderer is systemd-networkd, which holds
# onto the Wi-Fi adapter so nmcli never sees it — and then step [6] below fails
# with "no Wi-Fi adapter detected", or the AP can't be created on an unmanaged
# device at boot. Our whole access point is built through NetworkManager, so NM
# has to own the devices. netplan is Ubuntu's switch for that.
#
# Debian has no netplan and lets NM manage unconfigured devices directly, so this
# is skipped there — hence the `command -v netplan` guard.
#
# NOTE: if you are provisioning over SSH on the WIRED link, `netplan apply` can
# blip that link for a moment as NM takes it over. Provisioning at the console
# (keyboard + monitor) sidesteps that.
NM_NETPLAN="/etc/netplan/99-edgeathlete-nm.yaml"
if command -v netplan >/dev/null 2>&1; then
    if [ -f "$NM_NETPLAN" ]; then
        echo "    already handed to NetworkManager, left alone"
    else
        mkdir -p /etc/netplan
        cat > "$NM_NETPLAN" <<'EOF'
# Hand networking to NetworkManager so the Wi-Fi adapter is visible to nmcli and
# can run the access point. Written by Edge Athlete setup.sh.
network:
  version: 2
  renderer: NetworkManager
EOF
        chmod 600 "$NM_NETPLAN"    # netplan warns loudly about world-readable files
        netplan generate
        netplan apply
        sleep 3                     # give NM a moment to claim the devices
        echo "    netplan renderer set to NetworkManager"
    fi
else
    echo "    no netplan (not Ubuntu) — NetworkManager manages devices directly"
fi

echo "[4c] unblocking boot, and keeping the radio awake..."

# ── the boot gate that waits for something that cannot happen ───────────────────
# systemd-networkd-wait-online holds network-online.target until systemd-networkd
# reports an interface up and routable. But [4b] just handed EVERY device to
# NetworkManager, so networkd manages nothing at all and this unit waits for an
# interface it will never be given. That is roughly two minutes added to every
# boot, and it looks like this on the console:
#
#     Job systemd-networkd-wait-online.service/start running (56s / no limit)
#
# NetworkManager-wait-online is the unit actually doing this job here, and it
# finishes normally — you can watch both in the boot log, two lines apart, one
# done and one waiting. So enable that one FIRST, then mask the dead one:
# edgeathlete.service still waits on network-online.target and still gets a real
# guarantee, from the manager that actually owns the devices.
#
# ⚠️ THIS IS SAFE BECAUSE OF [4b], not on its own. Hand networking back to
# systemd-networkd (delete $NM_NETPLAN) and this mask silently drops the ordering
# guarantee instead of fixing anything. The two decisions travel together.
if systemctl cat NetworkManager-wait-online.service >/dev/null 2>&1; then
    systemctl enable NetworkManager-wait-online.service >/dev/null 2>&1 || true
    systemctl mask --now systemd-networkd-wait-online.service >/dev/null 2>&1 || true
    echo "    masked systemd-networkd-wait-online (NetworkManager-wait-online covers it)"
else
    echo "    [!] NetworkManager-wait-online missing — leaving the boot gate alone"
fi

# ── neither must the machine ────────────────────────────────────────────────────
# A base station is a server. It runs the database, the broker and the gym's Wi-Fi,
# and every device in the room depends on it. Suspending is never the right answer
# for it — but desktop installs enable sleep-on-idle by default, so a box that
# looks idle (nobody typing on it) puts the whole gym offline.
#
# Masked rather than configured, because these are targets nothing should ever
# reach here. Undo with: sudo systemctl unmask sleep.target suspend.target ...
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target \
    >/dev/null 2>&1 || true
echo "    suspend/hibernate masked (this machine is a server)"

# ── the radio must not nap ──────────────────────────────────────────────────────
# A Wi-Fi adapter that power-saves adds latency to exactly the traffic that cannot
# afford it: live reps during a set. The obvious command is
#
#     iw dev <iface> set power_save off
#
# and on this machine it FAILS with "Operation not supported" — power saving is a
# client-mode concept and this adapter is running as an access point. So it has to
# be set at the two layers that do apply, both of which survive a reboot, which is
# more than the `iw` command would have done anyway.
POWERSAVE_CONF="/etc/NetworkManager/conf.d/wifi-powersave-off.conf"
if [ -f "$POWERSAVE_CONF" ]; then
    echo "    NetworkManager powersave setting already present, left alone"
else
    mkdir -p /etc/NetworkManager/conf.d
    # 2 means "disable". (0 = use the global default, 1 = don't touch it,
    # 2 = disable, 3 = enable.) 0 and 1 both look like they might mean off.
    printf '[connection]\nwifi.powersave = 2\n' > "$POWERSAVE_CONF"
    echo "    NetworkManager powersave disabled"
fi

# Intel adapters ignore the generic setting in some modes and want module options
# instead. power_scheme=1 is "CAM" — continuously active mode — and is the one that
# actually matters on these cards. Only written when the driver is really loaded,
# so a non-Intel base station does not carry a config for hardware it lacks.
if lsmod 2>/dev/null | grep -q '^iwlwifi'; then
    IWL_CONF="/etc/modprobe.d/iwlwifi-powersave.conf"
    if [ -f "$IWL_CONF" ]; then
        echo "    iwlwifi options already present, left alone"
    else
        # mkdir because this script runs under `set -e`: a redirect into a missing
        # directory would abort the WHOLE provisioning run here — after the network
        # was handed to NetworkManager but before the boot service exists, which is
        # about the worst place to stop.
        mkdir -p /etc/modprobe.d
        printf 'options iwlwifi power_save=0\noptions iwlmvm power_scheme=1\n' > "$IWL_CONF"
        echo "    iwlwifi set to stay awake (applies on reboot)"
    fi
fi

echo "[5] preparing env file..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "    created .env from .env.example"
else
    echo "    .env already exists, left alone"
fi

echo "[5b] ensuring a real SECRET_KEY..."
# ⚠️ THE KEY .env SHIPS WITH IS PUBLIC. It comes from .env.example, which is
# committed, and it SIGNS THE JWTs a coach logs in with (symmetric HS256 — the
# same key signs and verifies), so anyone holding it can forge a coach session.
# Every real base station gets its own.
#
# Generate-once, like the config file and the AP password: if a real key is
# already here we leave it, so re-running setup or updating the code never
# invalidates every outstanding login by rotating the key underneath it.
#
# The whole SECRET_KEY line is stripped and re-appended rather than sed-replaced
# in place — a random key can contain characters sed treats specially, and this
# sidesteps all of them. The alphabet is plain alphanumeric for the same reason:
# no #, $ or quotes to confuse .env parsing. 50 chars is ~297 bits, ample.
CURRENT_KEY="$(grep '^SECRET_KEY=' "$PROJECT_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2-)"
case "$CURRENT_KEY" in
    ""|django-insecure-*)
        # Read a FIXED chunk of randomness, then filter and slice it in bash —
        # deliberately not `tr ... < /dev/urandom | head -c 50`. That pipeline
        # SIGPIPEs tr when head closes early, and under `set -o pipefail` that is
        # exit 141, which kills the whole script. A bounded read ends cleanly.
        # 512 random bytes yields ~300 alphanumerics, ample for a 50-char key.
        RANDOM_CHARS="$(head -c 512 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9')"
        NEW_KEY="${RANDOM_CHARS:0:50}"
        grep -v '^SECRET_KEY=' "$PROJECT_DIR/.env" > "$PROJECT_DIR/.env.tmp"
        echo "SECRET_KEY=$NEW_KEY" >> "$PROJECT_DIR/.env.tmp"
        mv "$PROJECT_DIR/.env.tmp" "$PROJECT_DIR/.env"
        echo "    generated a unique SECRET_KEY (the shipped one is public)"
        ;;
    *)
        echo "    SECRET_KEY already customised, left alone"
        ;;
esac

echo "[6] detecting the Wi-Fi adapter..."
# The base station BROADCASTS its own network, so it needs a Wi-Fi device that
# can run in AP mode. A wired-only OptiPlex will fail here, which is the correct
# outcome: better a clear error now than a box that boots with no gym network.
WIFI_IFACE="$(nmcli -t -f DEVICE,TYPE device 2>/dev/null | grep ':wifi$' | cut -d: -f1 | head -n 1 || true)"

if [ -z "$WIFI_IFACE" ]; then
    echo "[!] NetworkManager sees no Wi-Fi adapter."
    echo "[!] The base station has to broadcast the gym's network, so it needs one."
    echo "[!] Check:  nmcli device status   /   lsusb   /   lspci | grep -i net"
    echo "[!] If this box is wired-only, add a USB Wi-Fi adapter that supports AP mode."
    exit 1
fi
echo "    found: $WIFI_IFACE"

echo "[7] writing $CONFIG_FILE..."
# THE MACHINE'S SETTINGS LIVE OUTSIDE THE REPO, and that is the point.
#
# The old setup.sh ran `sed -i` on startup.sh to bake the interface name into a
# TRACKED FILE. That left the repo permanently dirty, so the next `git pull` on
# the base station hit a conflict on a machine with nobody around to resolve it
# — and the Wi-Fi password sat in git besides.
#
# Written once and never overwritten: change the AP name or password here and
# re-running setup (or updating the code) will not stamp on it.
mkdir -p "$CONFIG_DIR"
if [ -f "$CONFIG_FILE" ]; then
    echo "    already exists, left alone (delete it to regenerate)"
else
    cat > "$CONFIG_FILE" <<EOF
# Edge Athlete base station — this machine's settings.
# Not in git. Edit freely; setup.sh will not overwrite it.
# Applied on the next boot, or: sudo systemctl restart edgeathlete.service

AP_NAME="EdgeAthlete"              # the Wi-Fi name people see
AP_PASSWORD="ChangeMe123!"         # ⚠️ CHANGE THIS before the gym uses it
WIFI_IFACE="$WIFI_IFACE"           # detected by setup.sh
CONNECTION_NAME="EdgeAthlete-AP"   # NetworkManager profile name
AP_IP_CIDR="192.168.4.1/24"        # the base station's address + the range it hands out
EOF
    chmod 600 "$CONFIG_FILE"       # it holds the Wi-Fi password
    echo "    written (Wi-Fi password is in here — chmod 600)"
fi

echo "[8] creating state directory..."
mkdir -p "$STATE_DIR"

echo "[9] installing the boot service..."
chmod +x "$PROJECT_DIR/scripts/basestation/startup.sh"
# ExecStart is written with the RESOLVED path, so the unit always points at
# wherever this install actually is. Regenerated on every run, which is what
# makes moving the install a matter of re-running setup from its new home.
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Edge Athlete Base Station
After=network-online.target docker.service NetworkManager.service
Wants=network-online.target docker.service NetworkManager.service

[Service]
Type=oneshot
ExecStart=$PROJECT_DIR/scripts/basestation/startup.sh
RemainAfterExit=yes
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable edgeathlete.service

echo "[9b] installing the Wi-Fi-change agent..."
# THE "WORK-ORDER SLIP" HANDSHAKE (see apply-wifi.sh for the full picture).
# The coach app (a front-desk clerk in a container) leaves a work-order slip when
# it wants the Wi-Fi password changed; a maintenance worker on the host does the
# actual job. THIS STEP PUTS THE WORKER ON WATCH: the .path unit keeps an eye on
# the inbox tray (the request file), and the .service is the worker it calls when
# a slip appears. Both run as root — the worker needs the keys nmcli requires.
chmod +x "$PROJECT_DIR/scripts/basestation/apply-wifi.sh"
cat > /etc/systemd/system/edgeathlete-wifi-apply.service <<EOF
[Unit]
Description=Apply an Edge Athlete Wi-Fi password change

[Service]
Type=oneshot
ExecStart=$PROJECT_DIR/scripts/basestation/apply-wifi.sh
User=root
EOF
cat > /etc/systemd/system/edgeathlete-wifi-apply.path <<EOF
[Unit]
Description=Watch for an Edge Athlete Wi-Fi password change request

[Path]
# Fires the service whenever the coach app drops a request file here. The service
# consumes (deletes) the file, so this re-arms cleanly for the next change.
PathExists=$STATE_DIR/wifi-apply.request
Unit=edgeathlete-wifi-apply.service

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now edgeathlete-wifi-apply.path

echo "[10] capping docker log growth..."
# Without this the JSON logs grow until the disk fills. A gym runs this box for
# months without anyone looking at it.
mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ]; then
    cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
    systemctl restart docker
else
    echo "    /etc/docker/daemon.json already exists, left alone"
fi

echo "[11] installing the shell shortcuts..."
# A SYMLINK, not a copy. /etc/profile.d is sourced by every login shell, so the
# short commands (ea-update, ea-seed, ea-sim) are there the moment you SSH in.
# Pointing at the repo instead of copying means an update refreshes the commands
# too — otherwise a stale copy would sit here forever, quietly out of date with
# the script it claims to wrap.
ln -sfn "$PROJECT_DIR/scripts/basestation/aliases.sh" /etc/profile.d/edge-athlete.sh

echo "[11b] installing the screen launchers..."
# The base station defaults to being the WALL DISPLAY, and carries a clickable
# launcher for every role so any screen can be opened for debugging without
# reprovisioning anything.
#
# WHY ALL THREE, ON THE SERVER. This is the one machine that is always powered, has
# a monitor within reach, and can reach the app at `localhost` — which browsers treat
# as a trusted origin, so every role opens here with the offline cache, install, and
# Bluetooth all working, with no flags and no certificate. That makes it the natural
# place to answer "is this the rack screen or the server?" without walking to a rack.
#
# WHY THE AUTOSTART IS NOT OVERWRITTEN ON RE-RUN. setup.sh runs again on every
# update. Clobbering the autostart each time would silently undo a deliberate change
# — someone who pointed this machine at the coach screen for a week would find it
# back on the wall display after any update, for no visible reason. Same rule as
# /etc/docker/daemon.json above: write it if absent, otherwise leave it alone.
KIOSK_SH="$PROJECT_DIR/scripts/rack-screen/kiosk.sh"
chmod +x "$KIOSK_SH" "$PROJECT_DIR/scripts/basestation/basestation-kiosk.sh"

mkdir -p /var/lib/edge-athlete/kiosk && chmod 1777 /var/lib/edge-athlete/kiosk
mkdir -p /usr/share/applications /etc/xdg/autostart

# One clickable launcher per role. The wall display and rack open full-screen; the
# coach opens windowed, because a coach needs the browser menu (it is where "install
# this app" lives) and needs to be able to close the thing.
for role in dashboard rack coach; do
    case "$role" in
        coach) mode=windowed; label="Coach" ;;
        rack)  mode=kiosk;    label="Rack Screen" ;;
        *)     mode=kiosk;    label="Wall Display" ;;
    esac
    cat > "/usr/share/applications/edgeathlete-$role.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Edge Athlete — $label
Comment=Open the $role screen on this machine (localhost)
Exec=$KIOSK_SH $role localhost $mode
Terminal=false
Categories=Utility;
EOF
done

if [ -f /etc/xdg/autostart/edgeathlete-kiosk.desktop ]; then
    echo "    autostart already set, left alone"
else
    cat > /etc/xdg/autostart/edgeathlete-kiosk.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Edge Athlete Kiosk (dashboard)
Exec=$KIOSK_SH dashboard localhost
X-GNOME-Autostart-enabled=true
EOF
    echo "    defaults to the wall display on boot"
fi

echo "[11c] setting up the unattended kiosk login..."
# GOAL: plug in a monitor, see the wall display. No password, no keyboard.
# CONSTRAINT: doing anything ELSE on this machine must still cost a password.
#
# Those two pull against each other, and the resolution is WHO logs in — not
# whether a password is required. Turning on autologin for a real admin account
# would satisfy the first and destroy the second: an unattended machine sitting in
# a gym with a logged-in session that can sudo. Anyone who walks past inherits it.
#
# So a dedicated account exists purely to look at a web page. It has no sudo, and
# its password is LOCKED — it cannot be logged into deliberately at all, only
# auto-started by the display manager. Physical access gets you a wall display and
# nothing more; ssh and sudo still prompt exactly as before, for real accounts.
#
# Set EDGE_KIOSK_AUTOLOGIN=0 to skip all of this (headless boxes, or a gym that
# would rather type a password).
KIOSK_USER="${EDGE_KIOSK_USER:-edgekiosk}"

if [ "${EDGE_KIOSK_AUTOLOGIN:-1}" != "1" ]; then
    echo "    skipped (EDGE_KIOSK_AUTOLOGIN=0)"
elif ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
    # No browser means no desktop means nothing to autologin into. Saying so beats
    # creating an account that never does anything.
    echo "    no browser installed — skipping (this box has no screen)"
else
    if id "$KIOSK_USER" >/dev/null 2>&1; then
        echo "    user '$KIOSK_USER' already exists"
    else
        useradd -m -s /bin/bash -c "Edge Athlete kiosk" "$KIOSK_USER"
        # Locked, not blank. A blank password is a login anybody can use; a locked
        # one cannot be authenticated against at all, while autologin — which does
        # not authenticate — still works.
        passwd -l "$KIOSK_USER" >/dev/null 2>&1 || true
        echo "    created '$KIOSK_USER' (no sudo, password locked)"
    fi

    # ⚠️ A LOCKED PASSWORD AND A LOCK SCREEN ARE A TRAP TOGETHER, and this is the
    # fix for having shipped them together once. Locking the password is right: it
    # means nobody can log in AS this account. But the moment anything locks the
    # screen, that same locked password is the one being demanded — and no string on
    # earth satisfies it. The wall display becomes an unopenable prompt, and the way
    # out is a text console or ssh, which is not where anyone looks.
    #
    # Belt: the kiosk launcher turns the screen lock off inside the session.
    # Braces: this group, which Debian and Ubuntu ship precisely for kiosk accounts —
    # PAM lets its members through the greeter and the unlock prompt without a
    # password. It grants nothing new, because autologin ALREADY means physical
    # access opens this session. It only removes the dead end.
    if getent group nopasswdlogin >/dev/null 2>&1; then
        usermod -aG nopasswdlogin "$KIOSK_USER" || true
        echo "    added to 'nopasswdlogin' so a lock screen can never strand it"
    fi
    # Groups a graphical session may want. Absent groups are skipped rather than
    # failing the run — they differ by distro and none of them are required.
    for grp in video audio input render; do
        getent group "$grp" >/dev/null 2>&1 && usermod -aG "$grp" "$KIOSK_USER" || true
    done

    # Autologin, written for whichever display manager is actually installed. The
    # first two take drop-in files, which is why they are preferred: nothing of the
    # system's own config is edited, so removing our file fully reverts it.
    AUTOLOGIN_SET=""
    if [ -d /etc/lightdm ]; then
        mkdir -p /etc/lightdm/lightdm.conf.d
        cat > /etc/lightdm/lightdm.conf.d/50-edgeathlete.conf <<EOF
[Seat:*]
autologin-user=$KIOSK_USER
autologin-user-timeout=0
EOF
        AUTOLOGIN_SET="LightDM"
    elif [ -d /etc/sddm.conf.d ] || command -v sddm >/dev/null 2>&1; then
        mkdir -p /etc/sddm.conf.d
        cat > /etc/sddm.conf.d/50-edgeathlete.conf <<EOF
[Autologin]
User=$KIOSK_USER
Session=plasma
EOF
        AUTOLOGIN_SET="SDDM"
    elif [ -f /etc/gdm3/custom.conf ]; then
        # GDM has no drop-in directory, so this is the one place we edit a file the
        # system owns. Backed up once, and skipped entirely if autologin is already
        # configured — an update must never quietly repoint someone else's setting.
        if grep -qE '^\s*AutomaticLogin\s*=' /etc/gdm3/custom.conf; then
            echo "    GDM already has an autologin set, left alone"
            AUTOLOGIN_SET="GDM (pre-existing)"
        else
            cp -n /etc/gdm3/custom.conf /etc/gdm3/custom.conf.edgeathlete-backup
            sed -i "/^\[daemon\]/a AutomaticLoginEnable=true\nAutomaticLogin=$KIOSK_USER" \
                /etc/gdm3/custom.conf
            AUTOLOGIN_SET="GDM"
        fi
    fi

    if [ -n "$AUTOLOGIN_SET" ]; then
        echo "    autologin configured via $AUTOLOGIN_SET"
    else
        echo "    [!] no display manager found (LightDM/SDDM/GDM)."
        echo "        The account exists, but nothing will log it in. Install a desktop"
        echo "        environment, then re-run this script."
    fi
fi

echo "[12] building the stack (this takes a while the first time)..."
docker compose build

cat <<EOF

[✔] setup complete

  install     $PROJECT_DIR
  config      $CONFIG_FILE
  Wi-Fi       $WIFI_IFACE
  service     edgeathlete.service (starts on every boot)

NEXT:
  1. change AP_PASSWORD in $CONFIG_FILE  — it is still the default
  2. reboot, or: sudo systemctl start edgeathlete.service
  3. join the "EdgeAthlete" Wi-Fi and open http://basestation

SHORT COMMANDS (log out and back in, or: source /etc/profile.d/edge-athlete.sh)
  ea-update    pull latest code and rebuild
  ea-seed      fill it with demo data
  ea-sim       start the fake rack sensor
  ea-help      the full list

ON A MONITOR
  Plug one in and it boots to the wall display as '$KIOSK_USER' — no password.
  That account has no sudo and its password is locked, so ssh and sudo still
  prompt as normal for real accounts. The app list also has launchers for the
  rack and coach screens, for debugging.
  Not wanted? Re-run with: sudo EDGE_KIOSK_AUTOLOGIN=0 ./scripts/basestation/setup.sh
EOF
