# scripts/

Provisioning + boot scripts, split by device role. There are two completely
different kinds of device on the gym network:

## `basestation/` — the server + Wi-Fi access point (one per gym)
The Raspberry Pi that runs the whole Docker stack and **broadcasts** the
"EdgeAthlete" Wi-Fi. Reachable by everything else at `http://basestation`.

- **`setup.sh`** — run ONCE on a fresh Pi, from the repo root:
  `sudo scripts/basestation/setup.sh`. Installs tools + Docker, loads the Wi-Fi
  adapter firmware, and installs the boot service.
- **`startup.sh`** — runs on every boot (via the systemd service `setup.sh`
  installs): brings up the access point, then `docker compose up -d`.

## `rack-screen/` — a kiosk client (one per rack; also the wall display)
A Pi + touchscreen that **joins** the base station's Wi-Fi and boots straight into
full-screen Chromium. Runs **no** server.

- **`rack-kiosk-setup.sh`** — run ONCE:
  `sudo scripts/rack-screen/rack-kiosk-setup.sh`. Installs Chromium, joins the
  Wi-Fi as a client, turns on desktop autologin, and installs the kiosk launcher.
- **`kiosk.sh`** — the launcher: waits for the base station, disables screen
  blanking, runs Chromium `--kiosk`, and relaunches it if it exits. Takes a URL:
  `http://basestation/` for a rack, `http://basestation/dashboard` for the wall
  (Phase 12 reuses this same script).

**Notes**
- These target Raspberry Pi OS and can only be truly tested on real hardware.
- The Wi-Fi SSID + password in `rack-screen/rack-kiosk-setup.sh` **must match**
  `basestation/startup.sh` (`AP_NAME` / `AP_PASSWORD`).
- Base-station `startup.sh` uses the **repo root** as its working dir (where
  `docker-compose.yml` lives), not its own folder — so it still works from under
  `scripts/basestation/`.
