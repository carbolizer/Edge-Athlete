# systemd

**What it is.** What starts things at boot and restarts them when they die. The
Linux service manager.

**How we use it.** One unit on the base station, two on a rack screen:

| Unit | Where | Job |
|---|---|---|
| `edgeathlete.service` | base station | brings up the AP, then the Docker stack |
| `edgeathlete-rack-agent` | rack screen | the WT901 Bluetooth sensor |
| `edgeathlete-nfc-agent` | rack screen | the USB wristband reader |

**Where it lives.** Units written by the provisioning scripts into
`/etc/systemd/system/`. Config the units read lives in `/etc/edgeathlete/`.

**Worth knowing.** ⚠️ The scripts **rewrite unit files on every run** but leave
`/etc/edgeathlete/*.conf` alone. So hand-edit a unit and the next `ea-update`
silently reverts it; put the setting in the conf file instead.

`journalctl -u <unit> -n 30` is the first thing to run when hardware "does nothing" —
a five-second restart loop reads exactly like a dead device.

**More:** {doc}`../guides/rack-screen` · {doc}`../journal/scripts`
