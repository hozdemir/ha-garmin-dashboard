#!/bin/sh
# Run the backend test suite in a container pinned to one supported HA series.
# Usage: HA_SERIES=2026.9 scripts/test.sh [pytest args]   (default: newest series)
set -e
cd "$(dirname "$0")/.."
series="${HA_SERIES:-2026.10}"
image="garmin-dashboard-test:${series}"
docker build -q --build-arg "HA_SERIES=${series}" -t "$image" -f scripts/test.Dockerfile . >/dev/null
# A hung test must not block forever.
exec docker run --rm -v "$PWD:/repo" "$image" timeout 600 python -m pytest "$@"
