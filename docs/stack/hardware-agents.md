# The hardware agents

**What it is.** Two small Python programs on a rack laptop that talk to hardware a
browser cannot reach.

**How we use it.** Both run beside the browser, not inside it:

```
WT901 sensor ──BLE──► wt901_rack_agent ──MQTT──► base station broker
NFC reader   ──USB──► ccid_rack_agent  ──HTTP──► the rack screen (localhost:8766)
```

The browser cannot do either job: Web Bluetooth needs a secure context we do not
have, and browsers have no access to USB card readers at all.

**Where it lives.** `scripts/hardware/`. Dependencies split on purpose —
`requirements-ble.txt` (bleak, needs Python 3.10+) and `requirements-nfc.txt`
(pyusb, any Python), so a machine that cannot run one still gets the other.

**Worth knowing.** ⚠️ The WT901 agent publishes **no reps** unless started with
`--enable-provisional-reps`. The detector is unqualified and the broker has no ACLs,
so it is off by default.

**More:** {doc}`../guides/rack-screen` · {doc}`../journal/rack-tablet`
