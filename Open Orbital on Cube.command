#!/bin/sh
# Connect this Mac to the Cube-hosted Open Orbital. Local workflow: Start Open Orbital.command.
set -eu
cd "$(dirname "$0")"
exec sh outputs/observatory/cube-connect.sh "$@"
