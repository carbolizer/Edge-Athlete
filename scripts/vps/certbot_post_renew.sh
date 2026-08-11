#!/bin/sh
set -eu

deploy_dir=/opt/edgeathlete
compose_file=$deploy_dir/docker-compose.vps.yml
env_file=$deploy_dir/.env.vps

require_root_owned() {
    path=$1
    if [ ! -e "$path" ] || [ -L "$path" ]; then
        echo "Certbot hook requires a regular root-owned path: $path" >&2
        exit 1
    fi
    owner=$(stat -c %U "$path")
    mode=$(stat -c %a "$path")
    if [ "$owner" != root ] || [ $((0$mode & 0022)) -ne 0 ]; then
        echo "Certbot hook rejects non-root or group/world-writable path: $path" >&2
        exit 1
    fi
}

require_root_owned "$deploy_dir"
require_root_owned "$compose_file"
require_root_owned "$env_file"

domain=
while IFS='=' read -r name value; do
    if [ "$name" = VPS_DOMAIN ]; then
        domain=$value
    fi
done < "$env_file"
case "$domain" in
    ""|.*|*.|*[!a-z0-9.-]*)
        echo "Certbot hook found an invalid VPS_DOMAIN" >&2
        exit 1
        ;;
esac

docker compose \
    --env-file "$env_file" \
    -f "$compose_file" \
    up -d --no-deps vps-nginx
docker compose \
    --env-file "$env_file" \
    -f "$compose_file" \
    exec -T vps-nginx nginx -t
curl --fail --silent --show-error --max-time 15 "https://$domain/api/health/" >/dev/null
