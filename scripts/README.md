# scripts/

Provisioning + boot scripts, split by device role. There are two completely
different kinds of device on the gym network.

## `basestation/` — the server + Wi-Fi access point (one per gym)

The mini PC that runs the whole Docker stack and **broadcasts** the "EdgeAthlete"
Wi-Fi. Everything else on the network reaches it at `http://basestation`.

### Installing one — the whole thing, one command

```bash
curl -fsSL https://raw.githubusercontent.com/carbolizer/Edge-Athlete/main/scripts/basestation/bootstrap.sh | sudo bash
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
- **`ea.sh`** — the short commands (`ea-update`, `ea-seed`, `ea-sim`, …). One file,
  symlinked into `/usr/local/bin` once per command name; it reads which name it was
  invoked as. Real executables, **not** shell functions — so they work in a desktop
  terminal, over `ssh host 'ea-update'`, and under `sudo`, none of which read
  `/etc/profile.d`. Run `ea-help` for the list.
- **`basestation-kiosk.sh`** — runs the app **on the base station itself**. `setup.sh`
  already installs a clickable launcher for all three roles plus a wall-display
  autostart, so reach for this only to change the boot default
  (`sudo basestation-kiosk.sh autostart coach`) or to open a role from a shell
  (`basestation-kiosk.sh open coach`). Everything here points at `localhost`, not
  `basestation`, and that word does real work — see "Secure contexts" below.

> The base station **boots into the wall display** and carries a launcher for every
> role, so opening a rack screen to compare against a real one is a double-click.
> The autostart is written only if absent, so an update never undoes a deliberate
> change to it.

### Secure contexts, or why `localhost` and `basestation` are not the same

Service workers, PWA install, and Web Bluetooth only run in a **secure context**:
https or `localhost`, nothing else. `http://basestation` is not one — and it is
still not one *on the base station*, even though the name resolves to a loopback
address, because the browser judges the origin text and never looks at where it
resolves. Consequences:

- On the base station, use `localhost`. Everything works, no flags, no cert.
- From a rack tablet, `localhost` isn't available, so `kiosk.sh` passes Chromium
  `--unsafely-treat-insecure-origin-as-secure` (which is ignored unless a
  `--user-data-dir` is also set — one more reason the per-role profile matters).
- Real HTTPS is the wrong fix here: a self-signed cert warns on every phone, and
  an https page refuses the plain `ws://` MQTT socket as mixed content. See
  `react/src/polyfills.js`, which lost this same argument on purpose.

### Where things live

| | Path | In git? |
|---|---|---|
| The install | `/srv/edge-athlete/Edge-Athlete` | the repo itself |
| This machine's settings | `/etc/edgeathlete/basestation.conf` | **no** |
| App environment | `<install>/.env` | **no** (gitignored) |
| Boot service | `/etc/systemd/system/edgeathlete.service` | generated |
| First-boot flags | `/var/lib/edgeathlete/` | — |
| Short commands | `/usr/local/bin/ea*` | symlinks into the repo |
| Kiosk browser profiles | `/var/lib/edge-athlete/kiosk/<user>-<role>` | **no** |
| Kiosk autostart | `/etc/xdg/autostart/edgeathlete-kiosk.desktop` | generated |
| Kiosk login account | `edgekiosk` — no sudo, password locked | — |
| Autologin config | LightDM/SDDM drop-in, or `/etc/gdm3/custom.conf` | generated |
| Wi-Fi powersave off | `/etc/NetworkManager/conf.d/wifi-powersave-off.conf` | generated |
| Intel radio options | `/etc/modprobe.d/iwlwifi-powersave.conf` (Intel only) | generated |

Turning the kiosk login **off** removes it rather than skipping it:

```bash
sudo EDGE_KIOSK_AUTOLOGIN=0 /srv/edge-athlete/Edge-Athlete/scripts/basestation/setup.sh
```

The `edgekiosk` account is kept — it owns the browser profile and any app installed on the wall display, and without autologin nothing logs it in. `sudo userdel -r edgekiosk` if you want it gone too.

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

> **Installs from `main`.** It used to be pinned to `SprintBranch` because main
> was a generation behind; SprintBranch has since been merged into main and is
> zero commits ahead of it, so the pin now points at the older tree. Override
> with `EDGE_BRANCH=...` — **after** `sudo`, not before `curl`.

### Not a Raspberry Pi any more

The base station is a Dell OptiPlex mini PC. The Pi's MT7601U USB Wi-Fi firmware
step is gone — it only ever existed for that dongle. Everything else ports
unchanged, because the access point is NetworkManager's job on any Linux box.

**Ubuntu Server is handled automatically.** It defaults to `systemd-networkd`,
which hides the Wi-Fi adapter from `nmcli`; `setup.sh` detects netplan and hands
the network to NetworkManager so the adapter is visible and can run the AP. On
Debian there's no netplan and NM manages devices directly, so nothing special
happens. (If you provision Ubuntu Server over SSH on the wired link, that step
can blip the link for a moment — provisioning at the console avoids it.)

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

- **`rack-bootstrap.sh`** — the whole install, in one command. Same shape as the
  base station's `bootstrap.sh`, and re-running it is how you update a screen:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/carbolizer/Edge-Athlete/main/scripts/rack-screen/rack-bootstrap.sh | sudo bash
  ```

  It takes **no role argument** — a rack screen is a rack screen. This is the path
  you run on a dozen identical devices, and an argument there is how a wall display
  ends up bolted to a squat rack.
- **`rack-kiosk-setup.sh`** — what the bootstrap hands off to. Installs Chromium,
  joins the Wi-Fi as a client, turns on desktop autologin, and installs the kiosk
  launcher into `/etc/xdg/autostart` so it fires for **whoever** logs in. Run it
  directly only for a **coach tablet** (`sudo … rack-kiosk-setup.sh coach`), which
  gets a tappable icon instead of an autostart entry.
- **`ea.sh`** — `ea-update`, `ea-restart`, `ea-kiosk-log`. Symlinked into
  `/usr/local/bin`, same as the base station's.

> ⚠️ **There are two `ea.sh` files and they are not interchangeable.** Both
> define `ea-update`, meaning "update this device" — but a screen's resolves to
> `rack-bootstrap.sh` (a browser and a launcher, seconds) and the base station's to
> `bootstrap.sh` (Docker, the server stack, the access point, minutes). Sourcing the
> base station's on a rack tablet would install a server it has no use for **and**
> stand up a second Wi-Fi access point competing with the real one.
- **`kiosk.sh`** — the launcher: waits for the base station, disables screen
  blanking, runs Chromium `--kiosk`, and relaunches it if it exits. Takes a
  **role**, not a URL — `kiosk.sh rack`, `kiosk.sh coach`, `kiosk.sh dashboard` —
  because the role decides three things that have to agree: the URL, the browser
  profile, and which app installs.
  A third argument picks the mode, which is **two independent questions** —
  full-screen or windowed, and does it reopen itself:

  | mode | | on close | used by |
  |---|---|---|---|
  | `kiosk` | full-screen | reopens in 3s | rack screens in a gym |
  | `once` | full-screen | stays closed | the base station at boot |
  | `windowed` | a window | stays closed | coach tablets, demoing |

  Reopening is right for a screen nobody is standing at — one that closed itself
  and stayed closed is a dead screen with no one to notice. It is wrong anywhere a
  person is at the keyboard, where closing has to mean closing.

Two things about it are load-bearing and easy to undo by accident:

- **Each role gets its own browser profile** under `/var/lib/edge-athlete/kiosk/`.
  The app's identity (`device_id`, `device_role`, `rack_number`) lives in
  localStorage, which is one bucket per profile per origin — so two roles sharing
  a profile are one device as far as the server is concerned.
- **No `--incognito`.** It used to pass it, which discarded that same localStorage
  on every launch (so a screen lost its rack assignment on any crash) and made
  `repBuffer`'s IndexedDB memory-only, voiding the promise that reps survive a
  Wi-Fi drop. A kiosk wants the opposite of incognito.

> ⚠️ **`AP_SSID` / `AP_PASSWORD` in `rack-kiosk-setup.sh` must match the base
> station's** — which now means matching `/etc/edgeathlete/basestation.conf` on
> the base station, **not** `startup.sh`. If you change the gym's Wi-Fi password,
> change it in both places.

**Note:** these target real Linux hardware and can only be truly tested there.
The base-station scripts' logic — where the install lives, what goes into the
systemd unit and the config file, and whether re-running is safe — is covered by
a stubbed harness that runs them for real inside Debian.
