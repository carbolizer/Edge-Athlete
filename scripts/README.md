# scripts/

Provisioning + boot scripts, split by device role. There are two completely
different kinds of device on the gym network.

## `basestation/` — the server + Wi-Fi access point (one per gym)

The mini PC that runs the whole Docker stack and **broadcasts** the "EdgeAthlete"
Wi-Fi. Everything else on the network reaches it at `http://basestation`.

### Installing one — the whole thing, one command

```bash
curl -fsSL https://raw.githubusercontent.com/carbolizer/Edge-Athlete/SprintBranch/scripts/basestation/bootstrap.sh | sudo bash
```

Run the **same command again** any time you want to update the base station. It
is not one-shot: it pulls the latest code and re-provisions.

- **`bootstrap.sh`** — pulls the repo to `/srv/edge-athlete/Edge-Athlete` and
  hands off to `setup.sh`.
- **`setup.sh`** — installs Docker + NetworkManager, writes this machine's
  config, installs the boot service, builds the stack.
- **`startup.sh`** — runs on every boot: brings up the access point, then
  `docker compose up -d` (with the base-station overlay, below).
- **`apply-wifi.sh`** — the privileged Wi-Fi-password-change agent. Not run by
  hand: a systemd path-unit fires it when the coach app requests a change. It
  does the `nmcli` work as root, on the host, so the web container never needs
  network privileges. See "Changing the Wi-Fi password" below.

### Where things live

| | Path | In git? |
|---|---|---|
| The install | `/srv/edge-athlete/Edge-Athlete` | the repo itself |
| This machine's settings | `/etc/edgeathlete/basestation.conf` | **no** |
| App environment | `<install>/.env` | **no** (gitignored) |
| Boot service | `/etc/systemd/system/edgeathlete.service` | generated |
| First-boot flags | `/var/lib/edgeathlete/` | — |

### Three things worth knowing

**Nothing depends on who is logged in.** The old Pi version hardcoded
`/home/pi/edge-athlete`, so renaming the account or logging in as anyone else
left the boot service pointing at a directory that no longer existed. `/srv`
belongs to the machine, not to a person.

**The scripts work from wherever the repo is.** They resolve the repo root from
their own location, so you can clone to `/opt` or a home directory while testing
and it provisions whatever it is sitting in. The install also keeps the repo's
own name — `Edge-Athlete`, not a renamed `edge-athlete`.

**The Wi-Fi name, password and interface are NOT in git.** They live in
`/etc/edgeathlete/basestation.conf`, written once by `setup.sh` and never
overwritten. The old script `sed -i`'d the interface name into `startup.sh`
itself, which left the repo permanently dirty — so the next update hit a merge
conflict on a machine with nobody around to resolve it — and put the gym's Wi-Fi
password in version control.

```bash
sudo nano /etc/edgeathlete/basestation.conf   # change AP_PASSWORD before real use
sudo systemctl restart edgeathlete.service    # apply without rebooting
```

### Changing the Wi-Fi password (from the app or by hand)

A coach can change the gym Wi-Fi password from the coach admin page (banner link,
or the "Wi-Fi password" button). How it works, and why it is built this way:

- The coach app runs in a container and is **never** allowed to run `nmcli` — it
  is the most exposed service, so it must not be able to reconfigure the host
  network. Instead it writes the new password to a spool file
  (`/var/lib/edgeathlete/wifi-apply.request`, via the base-station overlay mount).
- A systemd path-unit (`edgeathlete-wifi-apply.path`) notices that file and runs
  `apply-wifi.sh` as root on the host, which updates `basestation.conf` and does
  the `nmcli` re-key. `nmcli` stays on the host, where the privilege already is.
- The request returns to the coach **before** the AP bounces, so the coach tablet
  can show the new password (with copy-to-clipboard) before it drops.

> ⚠️ **A Wi-Fi password change disconnects EVERY device** — every tablet, the
> wall display, and every rack Pi — the instant it applies. A web app cannot
> change a device's OS Wi-Fi credentials, so each one must rejoin by hand in its
> Settings. **The rack screens are Pis** with the password baked into their
> NetworkManager client profile (`rack-kiosk-setup.sh`), so each rack Pi needs
> its client profile updated too (SSH or keyboard) — not just a tablet tap.
> Rotating the Wi-Fi password is a walk-around, by design of Wi-Fi, not of this
> app. Do it between sessions.

By hand instead of the app: edit `AP_PASSWORD` in `basestation.conf` and
`sudo systemctl restart edgeathlete.service`.

> ⚠️ **The install is pinned to `SprintBranch`, deliberately.** GitHub's default
> branch for this repo is `main`, and main is a whole generation behind —
> different models, no monitoring publisher, no seed or simulator services. A
> base station built from main would come up looking fine and be running last
> season's app. Override with `EDGE_BRANCH=...` only if you mean it.

### Not a Raspberry Pi any more

The base station is a Dell OptiPlex mini PC. The Pi's MT7601U USB Wi-Fi firmware
step is gone — it only ever existed for that dongle. Everything else ports
unchanged, because the access point is NetworkManager's job on any Linux box.

**It still needs a Wi-Fi adapter that supports AP mode**, since it broadcasts the
gym's network. `setup.sh` refuses to provision a machine with no Wi-Fi device
rather than leaving you with a base station nothing can join. Check with:

```bash
iw list | grep -A5 "Supported interface modes"
```

If the access point fails at boot, the Docker stack still comes up — a box with
no gym Wi-Fi *and* no application cannot even be reached over a cable to find out
why. The failure is shouted about in the log instead.

## `rack-screen/` — a kiosk client (one per rack; also the wall display)

A Pi + touchscreen that **joins** the base station's Wi-Fi and boots straight
into full-screen Chromium. Runs **no** server.

- **`rack-kiosk-setup.sh`** — run ONCE:
  `sudo scripts/rack-screen/rack-kiosk-setup.sh`. Installs Chromium, joins the
  Wi-Fi as a client, turns on desktop autologin, and installs the kiosk launcher.
- **`kiosk.sh`** — the launcher: waits for the base station, disables screen
  blanking, runs Chromium `--kiosk`, and relaunches it if it exits. Takes a URL:
  `http://basestation/` for a rack, `http://basestation/dashboard` for the wall.

> ⚠️ **`AP_SSID` / `AP_PASSWORD` in `rack-kiosk-setup.sh` must match the base
> station's** — which now means matching `/etc/edgeathlete/basestation.conf` on
> the base station, **not** `startup.sh`. If you change the gym's Wi-Fi password,
> change it in both places.

**Note:** these target real Linux hardware and can only be truly tested there.
The base-station scripts' logic — where the install lives, what goes into the
systemd unit and the config file, and whether re-running is safe — is covered by
a stubbed harness that runs them for real inside Debian.
