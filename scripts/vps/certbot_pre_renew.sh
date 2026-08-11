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
docker compose \
    --env-file "$env_file" \
    -f "$compose_file" \
    stop vps-nginx
