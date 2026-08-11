# VPS Deployment Runbook

This profile hosts gateway diagnostics and the hosted Rack control plane. The Rack
Helper slice covers endpoint identity, pairing, launch intent, and status only; it
does not upload BLE reps. The profile does not enable hosted workouts, MQTT, a
simulator, hardware sockets, demo data, or a gym-host listener. Deploy only a
reviewed release that has passed independent QA and security review.

## Prerequisites

- A Linux VPS with Docker Engine, the Compose plugin, Git, Certbot, `age`, `curl`, a host
  firewall, and an externally managed SSH service.
- DNS `A`/`AAAA` records for `VPS_DOMAIN` and `BLE_LAB_DOMAIN` whose only
  addresses are this VPS. Remove stale records before certificate issuance.
- Cloud-provider firewall rules allowing inbound TCP 22 from operator addresses and
  TCP 80/443 from the internet. Do not allow PostgreSQL, Django, MQTT, or Docker API
  ports.
- A reviewed release tag checked out in a dedicated deployment directory.

The deployment directory is `/opt/edgeathlete`. Certbot's root-run renewal hooks
reject a different path, symlinks, non-root ownership, or group/world-writable
deployment inputs.

The Compose backend network gives `vps-postgres` the private alias `postgres` because
the current settings module fixes that hostname. PostgreSQL is not published.

VPS settings fail closed if required values are missing, contain template
placeholders, reuse repository development defaults, or do not define the exact
HTTPS origin and proxy/cookie protections. After migrations, startup also requires
exactly one hosted gym, exactly one active gateway, and no active staff account
that still accepts `coachpass`. Nginx exposes health, gateway ingestion, staff
authentication/diagnostics, and the exact hosted Rack, Rack Helper, endpoint-pairing,
and minimal coach TrainingGroup routes listed in `nginx/vps.conf.template`. Its
fallback denies every other `/api/` route; local rack, athlete, workout, report,
hardware, system, and admin routes return `404`.

The VPS React image is built with `VITE_DEPLOYMENT_PROFILE=hosted`. That profile
contains only `/rack` and `/coach/rack-pairing`; legacy local routes redirect to
those surfaces or the role picker. The default `local` profile retains the Pi
dashboard, MQTT listeners, offline service worker, and local Rack routes. Builds
reject any other profile value. On first hosted load, the app unregisters a
previously installed local service worker and deletes `edgeathlete-shell-*` caches.

## DNS And Certificates

Set `DOMAIN` in the shell only for these host commands:

```bash
export DOMAIN=vps.example.com
export BLE_DOMAIN=ble.vps.example.com
dig +short A "$DOMAIN"
dig +short AAAA "$DOMAIN"
dig +short A "$BLE_DOMAIN"
dig +short AAAA "$BLE_DOMAIN"
sudo certbot certonly --standalone -d "$DOMAIN"
sudo certbot certonly --standalone -d "$BLE_DOMAIN"
```

Certificate issuance needs port 80 free. This deployment uses Certbot's standalone
authenticator, so install the reviewed hooks that stop only VPS Nginx before a
renewal attempt and start/test it afterward:

```bash
sudo install -m 755 scripts/vps/certbot_pre_renew.sh \
  /etc/letsencrypt/renewal-hooks/pre/edgeathlete-nginx
sudo install -m 755 scripts/vps/certbot_post_renew.sh \
  /etc/letsencrypt/renewal-hooks/post/edgeathlete-nginx
sudo install -d -m 755 /etc/systemd/system/certbot.service.d
sudo install -m 644 scripts/vps/certbot.service.d.conf \
  /etc/systemd/system/certbot.service.d/edgeathlete.conf
sudo systemctl daemon-reload
sudo certbot renew --dry-run --no-random-sleep-on-renew
```

The post hook starts only `vps-nginx`, validates its configuration, and requests the
public health endpoint. The systemd `ExecStopPost` repeats that recovery/check after
both successful and failed Certbot service exits. The dry-run must renew both names and
leave `vps-nginx` running with `nginx -t` successful. Monitor failed `certbot.service`
units outside the application. The Compose profile mounts the Certbot state directory read-only and expects
`live/<VPS_DOMAIN>/{fullchain.pem,privkey.pem}` beneath it.

## Secrets

Create the ignored environment file and restrict it before entering secrets:

```bash
install -m 600 .env.vps.example .env.vps
python -c 'import secrets; print(secrets.token_urlsafe(64))'
python -c 'import secrets; print(secrets.token_urlsafe(48))'
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Use the outputs, in order, for `SECRET_KEY`, `RACK_CONTROL_PLANE_KEY`, and
`POSTGRES_PASSWORD`. Replace all angle-bracket placeholders, set
`VPS_CERTBOT_DIR=/etc/letsencrypt`, and never commit `.env.vps`. Confirm no
placeholder remains:

```bash
grep -n '<\|>' .env.vps
```

The command must return no output. Gateway bearer credentials do not belong in this
file; provision and install them according to the gateway ADR.

## Bootstrap

The normal service will not start before its one gym and gateway exist. Initialize
the database, create an active staff sponsor, provision the coach organization and
initial TrainingGroup, and provision the gateway with one-off Compose commands:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm vps-django python manage.py migrate
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm vps-django python manage.py createsuperuser
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm vps-django \
  python manage.py provision_organization --organization-id <new-organization-UUID> \
  --organization <organization-name> \
  --group <initial-training-group> --staff <staff-username>
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm vps-django \
  python manage.py provision_edge_gateway --gym <gym-slug> --label <gateway-label> --staff <staff-username>
```

`provision_edge_gateway` prints the bearer credential once. Install it immediately
using the gateway systemd credential procedure; it cannot be recovered from the
database. Node grant creation and live gateway upload remain release blocks until
their operator procedure is implemented and validated. Those blocks apply to the
diagnostics gateway feature, not to this hosted Rack control-plane release. Do not
create node grants or start a gateway uploader when deploying Rack control plane only.

## Deploy

Run the configuration check before every deployment:

```bash
python3 scripts/vps/check_api_allowlist.py
python3 -m unittest scripts/vps/test_check_api_allowlist.py
python3 -m unittest scripts/vps/test_smoke_test.py
python3 -m unittest scripts/vps/test_certbot_hooks.py
```

This check fails if `nginx/vps.conf.template` adds, removes, or widens an API
location without updating the reviewed allowlist. The unit test proves that
replacing the `/api/` denial with `proxy_pass` fails validation.

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml config --quiet
docker compose --env-file .env.vps -f docker-compose.vps.yml build
docker compose --env-file .env.vps -f docker-compose.vps.yml up -d
docker compose --env-file .env.vps -f docker-compose.vps.yml ps
docker compose --env-file .env.vps -f docker-compose.vps.yml exec -T vps-nginx nginx -t
curl --fail --show-error --silent "https://${DOMAIN}/api/health/"
python3 scripts/vps/smoke_test.py "https://${DOMAIN}"
```

The smoke test verifies health, the `/rack` application shell, Rack CSRF cookie
flags, generic unauthenticated Rack status, security headers, HTTP redirect/POST
handling, and denial of a private API and Django admin. Inspect migration and startup output with
`docker compose --env-file .env.vps -f docker-compose.vps.yml logs vps-django`.
The VPS command runs migrations, the deployment preflight, and Gunicorn. It never
runs `ensure_demo_coach`.

## Firewall And External Verification

Configure the provider firewall first. If UFW is the host policy, preserve the
current SSH path before enabling it:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

Docker-published ports can bypass some UFW forwarding policies, so the provider
firewall and an external scan are mandatory. From a machine outside the VPS:

```bash
nmap -Pn -p 22,80,443,8000,1883,9001,5432 "$DOMAIN"
curl -I "http://${DOMAIN}/"
curl -i -X POST "http://${DOMAIN}/api/gateway/v1/events/"
curl -I "https://${DOMAIN}/"
```

Expected results: only approved SSH, HTTP, and HTTPS ports are reachable; HTTP
`GET`/`HEAD` returns `308`; HTTP gateway `POST` returns `405`; ports 8000, 1883,
9001, and 5432 are closed; HTTPS responses include HSTS and the configured security
headers. Port 80 remains open only for redirect and certificate operations.

## Backup And Restore Test

Take a logical backup before every update or migration and store it encrypted in an
access-controlled location outside the VPS. Set `BACKUP_RECIPIENT` to the reviewed
`age` public recipient and stream directly into encrypted output:

```bash
mkdir -p backups
docker compose --env-file .env.vps -f docker-compose.vps.yml exec -T vps-postgres \
  sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  | age --recipient "$BACKUP_RECIPIENT" \
      --output "backups/edgeathlete-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
```

Transfer the encrypted file off the VPS, verify its checksum at the destination,
then remove the VPS copy. Never write a plaintext dump to persistent VPS storage.

Do not claim a backup is usable until a restore test succeeds. Restore into an
empty, isolated PostgreSQL instance running the same major version, never over the
live database:

```bash
createdb -h <restore-host> -U <restore-user> edgeathlete_restore_test
age --decrypt <backup.dump.age> | pg_restore -h <restore-host> -U <restore-user> -d edgeathlete_restore_test --exit-on-error
psql -h <restore-host> -U <restore-user> -d edgeathlete_restore_test -c 'SELECT COUNT(*) FROM django_migrations;'
```

Record the backup checksum, restore date, PostgreSQL version, migration count, and
operator. Delete the isolated restore database after evidence is retained.

## Update And Rollback

Do not update during a training session. Before updating, record the current release
tag and image IDs, take and test a backup, then deploy a reviewed tag:

```bash
git describe --tags --always
docker compose --env-file .env.vps -f docker-compose.vps.yml images
git fetch --tags
git checkout <reviewed-release-tag>
docker compose --env-file .env.vps -f docker-compose.vps.yml build
docker compose --env-file .env.vps -f docker-compose.vps.yml up -d
```

For application rollback, stop the gym gateway first so its durable queue remains
untouched, check out the recorded prior release tag, rebuild, and start the profile.
Do not reverse a Django migration unless its reviewed rollback note permits it and a
verified backup exists. Never replay the hosted gateway queue into the local profile.
If schema rollback is unsafe, restore the verified pre-update backup to a replacement
database volume and preserve the failed volume for investigation.

Before removing control-plane routes or reversing migrations `0025` through `0029`,
export endpoint ownership and revocation state directly into encrypted output:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml exec -T vps-postgres \
  sh -c 'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "COPY (SELECT endpoint.id AS endpoint_id, endpoint.organization_id, \
      endpoint.training_group_id, endpoint.state AS endpoint_state, endpoint.revoked_at, \
      credential.id AS credential_id, credential.state AS credential_state, \
      credential.revoked_at AS credential_revoked_at \
      FROM event_handler_browserendpoint AS endpoint \
      LEFT JOIN event_handler_endpointcredential AS credential \
      ON credential.endpoint_id = endpoint.id ORDER BY endpoint.id, credential.id) \
      TO STDOUT WITH CSV HEADER"' \
  | age --recipient "$BACKUP_RECIPIENT" \
      --output "backups/control-plane-ownership-$(date -u +%Y%m%dT%H%M%SZ).csv.age"
```

Transfer the encrypted export off the VPS and decrypt-test it beside the full backup.
It contains private tenant and endpoint identifiers: never print it, store it
unencrypted, or attach it to a ticket. Do not reverse the schema unless the export
contains the expected endpoint and credential row counts. Silently dropping this
mapping is not an acceptable rollback.

After update or rollback, repeat Compose validation, Nginx syntax checking, HTTPS
health, gateway HTTP rejection, external scanning, and staff diagnostics checks.
