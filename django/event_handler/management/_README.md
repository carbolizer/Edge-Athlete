# `management/commands/` — the things you run by hand

Five commands. Two are services that run themselves in Docker; three you type.

Everything below assumes the stack is up (`docker compose up -d`).

```
management/
└── commands/                       Django requires this exact nesting
    ├── seed_active_session.py      Build a realistic fake gym. The one you'll use most
    ├── simulate_node.py            Fake a rack sensor — pulses + reps over MQTT
    ├── ensure_demo_coach.py        Create the coach / coachpass login if missing
    ├── run_mqtt_subscriber.py      The inbound listener (the mqtt-listener service)
    └── publish_monitoring_events.py  The outbound worker draining room invalidations
```

> The `commands/` nesting is Django's, not a choice — `manage.py` only discovers
> commands inside `<app>/management/commands/`. Nothing else goes in either folder.

## Seed a demo gym

```bash
docker compose exec django python manage.py seed_active_session --reset
```

Creates an open training day with a roster, groups, plans, reference maxes, and a
few completed sets. **`--reset` wipes the demo data first** — use it whenever the
gym looks wrong, because without it the command converges onto what is already
there rather than starting clean.

This is what you want after `docker compose down -v`.

## Fake a sensor

```bash
docker compose exec django python manage.py simulate_node --node-id rack_1
```

Publishes pulses and reps as if a real ESP32 were clamped to a bar, so you can
watch a rack screen light up with no hardware on the desk.

| Flag | Default | |
|---|---|---|
| `--node-id` | **required** | e.g. `rack_1` |
| `--rack` | none | Rack number, informational only |
| `--interval` | `3.0` | Seconds between reps |
| `--reps-per-set` | `5` | Reps before it rests |

Rows it creates are stamped `is_simulated`, so demo data stays easy to tell apart
from real lifting.

## The demo login

```bash
docker compose exec django python manage.py ensure_demo_coach
```

Idempotent — creates `coach` / `coachpass` only if it is missing. Runs on boot, so
you rarely need it by hand.

## The two you don't run

`run_mqtt_subscriber` is the `mqtt-listener` compose service, and
`publish_monitoring_events` drains the outbound queue. Both are long-running.
Starting a second copy of either by hand means **two processes consuming the same
stream** — the duplicate-listener bug this project inherited and deliberately
fixed. Check `docker compose ps` before starting one.
