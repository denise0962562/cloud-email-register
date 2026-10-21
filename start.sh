#!/bin/sh
set -eu
cd "$(dirname "$0")"
umask 077
# Use macOS's certificate bundle, including locally trusted roots.
if [ "$(uname -s)" = Darwin ] && [ -f /etc/ssl/cert.pem ]; then
    export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-/etc/ssl/cert.pem}"
fi
exec .venv/bin/python -u web_ui.py --host 127.0.0.1 --port 5050 --no-sync "$@"
