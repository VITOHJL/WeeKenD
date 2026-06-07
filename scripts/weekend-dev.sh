#!/usr/bin/env bash
#
# weekend-dev.sh — Launch DeerFlow (WeekenD instance) on a dedicated port set
# that does NOT clash with any other services already running on the machine.
#
# Default ports (overridable via env before invoking):
#   Gateway  : 18001  (default 8001)
#   Frontend : 13000  (default 3000)
#   Nginx    : 12026  (default 2026)  ← this is the URL you open in the browser
#
# Usage:
#   ./scripts/weekend-dev.sh            # foreground dev mode (Ctrl+C to stop)
#   ./scripts/weekend-dev.sh --daemon   # background
#   ./scripts/weekend-dev.sh --stop     # stop the WeekenD instance
#   ./scripts/weekend-dev.sh --restart  # restart
#
# All extra args are passed straight through to serve.sh.

set -e

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
cd "$REPO_ROOT"

export DEERFLOW_GATEWAY_PORT="${DEERFLOW_GATEWAY_PORT:-18001}"
export DEERFLOW_FRONTEND_PORT="${DEERFLOW_FRONTEND_PORT:-13000}"
export DEERFLOW_NGINX_PORT="${DEERFLOW_NGINX_PORT:-12026}"

echo "=========================================="
echo "  WeekenD on dedicated ports"
echo "    Gateway  : $DEERFLOW_GATEWAY_PORT"
echo "    Frontend : $DEERFLOW_FRONTEND_PORT"
echo "    Nginx    : $DEERFLOW_NGINX_PORT  (open http://localhost:$DEERFLOW_NGINX_PORT)"
echo "=========================================="

# Default to --dev when no action/mode flag is supplied.
HAS_MODE=false
for arg in "$@"; do
    case "$arg" in
        --dev|--prod|--stop|--restart) HAS_MODE=true ;;
    esac
done

if $HAS_MODE; then
    exec ./scripts/serve.sh "$@"
else
    exec ./scripts/serve.sh --dev "$@"
fi
