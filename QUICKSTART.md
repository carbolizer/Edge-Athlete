<!--
QUICKSTART.md — clean Linux box to a running base station, start to finish.
The short path. Deeper detail lives in _RUNBOOK.md and scripts/README.md.
-->

# Edge Athlete — Base Station Quickstart

Clean Linux install → running base station.

## Before you start

- **Debian or Ubuntu** on the mini PC (x86).
- A **Wi-Fi adapter that supports AP mode** — the base station broadcasts its own
  network, so setup refuses without one. Check: `iw list | grep -A5 "Supported interface modes"` (look for `AP`).
- **Internet for the install only** (to pull Docker + build images). It runs fully offline after that.
- **sudo/root** access.

## 1. Install — one command

```bash
curl -fsSL https://raw.githubusercontent.com/carbolizer/Edge-Athlete/SprintBranch/scripts/basestation/bootstrap.sh | sudo bash
```

Installs git + Docker + NetworkManager, clones the repo to
`/srv/edge-athlete/Edge-Athlete`, generates a unique `SECRET_KEY`, detects the
Wi-Fi adapter, installs the boot service, and builds the stack. Slow the first
time — it's building images.

## 2. Set the Wi-Fi password

Ships as `ChangeMe123!` — change it before anything real:

```bash
sudo nano /etc/edgeathlete/basestation.conf
```

Edit the `AP_PASSWORD` line, save, exit. (Can also be done later from the coach page.)

## 3. Start it

```bash
sudo systemctl start edgeathlete.service
```

Brings up the "EdgeAthlete" Wi-Fi and all the containers. Comes up on its own after every reboot from here on.

## 4. Connect and open

Join the **EdgeAthlete** Wi-Fi (password from step 2), then open:

```
http://basestation
```

Coach login: **`coach` / `coachpass`**.

## 5. Fill it with demo data (optional)

Empty database otherwise. From the repo folder:

```bash
cd /srv/edge-athlete/Edge-Athlete && docker compose run --rm seed
```

A live session, the team, plans, and some finished sets.

## 6. Fake a rack sensor for a demo (optional)

No hardware needed — publishes reps only while a set is open at rack 1:

```bash
cd /srv/edge-athlete/Edge-Athlete && docker compose --profile demo up -d simulator
```

## Quick checks if something's off

All seven containers up:

```bash
cd /srv/edge-athlete/Edge-Athlete && docker compose ps
```

App healthy:

```bash
curl -s http://localhost/api/health/
```

Boot script output (AP + stack startup):

```bash
sudo journalctl -u edgeathlete.service -e
```

> **The one thing that can't be scripted around:** steps 1 and 3 need that Wi-Fi
> adapter to do AP mode. If it can't, the app still comes up (reachable over a
> cable), but there's no gym Wi-Fi — the startup log says so plainly. Everything
> else is hands-off.
