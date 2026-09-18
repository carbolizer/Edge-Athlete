# Docker and Compose

**What it is.** How the server side runs. Each service is a container; Compose
starts them together with one file.

**How we use it.** One stack on the base station, started at boot by systemd:

```
docker compose up -d   ──►  postgres · mosquitto · django · mqtt-listener
                            monitoring-publisher · react · nginx
```

Two services are profile-gated and only run when asked — `seed` (demo data) and
`simulator` (a fake sensor).

**Where it lives.** `docker-compose.yml` at the repo root. Rack screens run **no
Docker at all** — they are browsers.

**Worth knowing.** ⚠️ `docker compose build` **skips profile-gated services**. The
simulator image sat months out of date behind a "successful" rebuild because of it.
`ea-seed` and `ea-sim` now build their own image first.

⚠️ A rebuilt image does not restart a running container. That is what `ea-reset` is
for; `ea-update` alone leaves the old container serving.

**More:** {doc}`../guides/base-station`
