# `realtime/` — MQTT in, MQTT out

Everything that talks to the broker. **Adopted from Braydon's branch in P2** — this
is the one package where his structure survived the merge largely intact, because
it was already the better shape.

```
realtime/
├── mqtt_ingester/
│   ├── subscriber.py     The ONE inbound listener. Runs as its own container
│   └── parser.py         Validates every payload before it is trusted
├── event_processor/
│   └── process_pulse.py  A node pulse → health state, and invalidate if it matters
└── broadcast/
    └── publisher.py      The one place Django announces anything over MQTT
```

## The rule that matters most

**Django only ever listens for heartbeats.** Reps are *not* streamed in. They are
buffered on the tablet and saved in one batch at `POST /api/sets/{id}/complete/`.

That is why a WiFi blip mid-set costs nothing, and it is why there is no
rep-ingest path here to go looking for. If you add one, you have broken the
guarantee the whole rack design rests on.

## Two kinds of announcement — don't merge them

`publisher.py` says this at length and it is worth repeating: there are two
different things going out, and they are not interchangeable.

| | |
|---|---|
| **Rack topics** | Byte-identical to what the rack screens already expect. **Frozen.** A rack screen in the gym is parsing these today |
| **Room invalidations** | "Something changed, re-read" — durable, written to `MonitoringEvent` first, drained by a worker |

The invalidation path is written down *before* it is published on purpose: a
dropped connection leaves an unpublished row for the next attempt instead of
losing the update outright.

## Known dead channel

`edgeathlete/coach/state` is documented in `MESSAGE_CONTRACT.md` but
`publish_coach_state()` is **defined and never called**, and nothing subscribes.
Dead at both ends — plausibly reserved for Phase 15 fatigue alerts. Wire it or
delete it; don't spend an afternoon debugging a message that was never sent.

## Running it

The listener is a compose service (`mqtt-listener`), not something you start by
hand. The publisher worker is `manage.py publish_monitoring_events`. To generate
traffic without hardware, use `manage.py simulate_node` — see
[`../management/commands/_README.md`](../management/commands/_README.md).

> ⚠️ The broker is `allow_anonymous true` on both listeners. Anything on the gym
> network can publish to any topic, including fake rep data. Phase 16.
