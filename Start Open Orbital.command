#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec sh outputs/observatory/start.sh
