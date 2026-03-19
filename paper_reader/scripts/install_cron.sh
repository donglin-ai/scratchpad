#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CRON_FILE="$ROOT/deploy/paper_reader.cron"

if [[ ! -f "$CRON_FILE" ]]; then
  echo "Missing $CRON_FILE" >&2
  exit 1
fi

crontab "$CRON_FILE"
echo "Installed cron from $CRON_FILE"
