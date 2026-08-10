# VPS Deployment Runbook

This profile hosts diagnostics only. It does not enable hosted workouts, MQTT, a
simulator, hardware sockets, demo data, or a gym-host listener. Deploy only a
reviewed release that has passed independent QA and security review.

## Prerequisites

- A Linux VPS with Docker Engine, the Compose plugin, Git, Certbot, `age`, a host
  firewall, and an externally managed SSH service.
- A DNS `A`/`AAAA` record whose only addresses are this VPS. Remove stale records
  before certificate issuance.
- Cloud-provider firewall rules allowing inbound TCP 22 from operator addresses and
  TCP 80/443 from the internet. Do not allow PostgreSQL, Django, MQTT, or Docker API
  ports.
- A reviewed release tag checked out in a dedicated deployment directory.

The Compose backend network gives `vps-postgres` the private alias `postgres` because
the current settings module fixes that hostname. PostgreSQL is not published.

VPS settings fail closed if required values are missing, contain template
placeholders, reuse repository development defaults, or do not define the exact
HTTPS origin and proxy/cookie protections. After migrations, startup also requires
exactly one hosted gym, exactly one active gateway, and no active staff account
that still accepts `coachpass`. Nginx exposes only health, gateway ingestion,
staff authentication, and staff gateway diagnostics under `/api/`; local rack,
athlete, workout, report, hardware, system, and admin routes return `404`.

## DNS And Certificates

Set `DOMAIN` in the shell only for these host commands:

```bash
export DOMAIN=vps.example.com
dig +short A "$DOMAIN"
dig +short AAAA "$DOMAIN"
sudo certbot certonly --standalone -d "$DOMAIN"
sudo certbot renew --dry-run
```

Certificate issuance needs port 80 free. Stop only the VPS Nginx service if renewing
with the standalone plugin. Prefer a Certbot deploy hook that runs:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml exec -T vps-nginx nginx -s reload
```

Monitor renewal failures outside the application. The Compose profile mounts the
Certbot state directory read-only and expects
`live/<VPS_DOMAIN>/{fullchain.pem,privkey.pem}` beneath it.

## Secrets

Create the ignored environment file and restrict it before entering secrets:

```bash
install -m 600 .env.vps.example .env.vps
python -c 'import secrets; print(secrets.token_urlsafe(64))'
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Use the first output for `SECRET_KEY` and the second for `POSTGRES_PASSWORD`. Replace
all angle-bracket placeholders, set `VPS_CERTBOT_DIR=/etc/letsencrypt`, and never
commit `.env.vps`. Confirm no placeholder remains:

```bash
grep -n '<\|>' .env.vps
```

The command must return no output. Gateway bearer credentials do not belong in this
file; provision and install them according to the gateway ADR.

## Bootstrap

The normal service will not start before its one gym and gateway exist. Initialize
the database, create an active staff sponsor, and provision the gateway with one-off
Compose commands:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm vps-django python manage.py migrate
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm vps-django python manage.py createsuperuser
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm vps-django \
  python manage.py provision_edge_gateway --gym <gym-slug> --label <gateway-label> --staff <staff-username>
```

The provisioning command prints the bearer credential once. Install it immediately
using the gateway systemd credential procedure; it cannot be recovered from the
database. Node grant creation and live gateway upload remain release blocks until
their operator procedure is implemented and validated.

## Deploy

Run the configuration check before every deployment:

```bash
python3 scripts/vps/check_api_allowlist.py
python3 -m unittest scripts/vps/test_check_api_allowlist.py
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
```

Inspect migration and startup output with
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

After update or rollback, repeat Compose validation, Nginx syntax checking, HTTPS
health, gateway HTTP rejection, external scanning, and staff diagnostics checks.
