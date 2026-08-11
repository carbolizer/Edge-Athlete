#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'Usage: %s ABSOLUTE_PYTHON_PATH ABSOLUTE_ENTRYPOINT_PATH\n' "$0" >&2
  exit 2
fi

python_path=$1
entrypoint_path=$2
if [[ $python_path != /* || $entrypoint_path != /* || ! -x $python_path || ! -f $entrypoint_path ]]; then
  printf 'Both arguments must be existing absolute paths; Python must be executable.\n' >&2
  exit 2
fi
if [[ $python_path == *[[:cntrl:]%]* || $entrypoint_path == *[[:cntrl:]%]* ]]; then
  printf 'Paths may not contain control or percent characters.\n' >&2
  exit 2
fi

escape_exec() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//\`/\\\`}
  value=${value//\$/\\$}
  printf '%s' "$value"
}

data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
applications_dir="$data_home/applications"
desktop_file="$applications_dir/edgeathlete-rack-helper-development.desktop"
mkdir -p -- "$applications_dir"
python_exec=$(escape_exec "$python_path")
entrypoint_exec=$(escape_exec "$entrypoint_path")
printf '%s\n' \
  '[Desktop Entry]' \
  'Type=Application' \
  'Name=Edge Athlete Rack Helper (Development Only)' \
  'Comment=Unsigned development Rack Helper' \
  "Exec=\"$python_exec\" \"$entrypoint_exec\" %u" \
  'Terminal=false' \
  'NoDisplay=true' \
  'MimeType=x-scheme-handler/edgeathlete-rack;' \
  > "$desktop_file"
chmod 600 "$desktop_file"
update-desktop-database "$applications_dir"
xdg-mime default edgeathlete-rack-helper-development.desktop x-scheme-handler/edgeathlete-rack
printf 'Registered development handler: %s\n' "$desktop_file"
