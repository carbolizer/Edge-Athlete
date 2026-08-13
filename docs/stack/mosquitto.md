# Mosquitto

**What it is.** The message broker — a post office. Programs publish to a named
channel (a *topic*), and anything subscribed to that channel gets a copy. Nobody
addresses anybody directly.

**How we use it.** Every live message in the system. A rep never touches the server:

```
node ──rep──► mosquitto ──► rack screen ──► browser storage
                                              │  (one write per SET, not per rep)
                                              ▼
                                        POST /api/sets/complete ──► django ──► postgres
```

Heartbeats are the exception — those Django *does* listen to:

```
node ──pulse──► mosquitto ──► mqtt-listener ──► postgres (battery, signal, last_seen)
```

And Django announces changes back out, so screens refetch:

```
django ──► mosquitto ──► wall display + coach tablet
```

**Where it lives.** Container `edgeathlete-mosquitto`, image `eclipse-mosquitto`.
Two doors into the same broker: **1883** for hardware and Django, **9001** for
browsers (the same MQTT wrapped in WebSockets). Config in
`mosquitto/mosquitto.conf`.

**Worth knowing.** It allows anonymous connections — anything on the gym Wi-Fi can
publish. That is a known, accepted gap.

**More:** {doc}`../journal/real-time` for why there is no WebSocket layer in Django ·
{doc}`../reference/message-contract` for exact topics and payloads
