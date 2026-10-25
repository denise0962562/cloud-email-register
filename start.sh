#!/bin/sh
set -eu
cd "$(dirname "$0")"
umask 077
export AUTH_COOKIE_SECURE="${AUTH_COOKIE_SECURE:-0}"
# Use macOS's certificate bundle, including locally trusted roots.
if [ "$(uname -s)" = Darwin ] && [ -f /etc/ssl/cert.pem ]; then
    export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-/etc/ssl/cert.pem}"
fi
exec .venv/bin/python -u web_ui.py --host 127.0.0.1 --port 2224 --no-sync "$@"
