#!/bin/sh
# Run the backend test suite in a container pinned to the supported HA version.
set -e
cd "$(dirname "$0")/.."
docker build -q -t garmin-dashboard-test -f scripts/test.Dockerfile . >/dev/null
exec docker run --rm -v "$PWD:/repo" garmin-dashboard-test python -m pytest "$@"
