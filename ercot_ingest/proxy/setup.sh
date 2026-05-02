#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
set -a; source .env; set +a

case "${1:-}" in
    secret)
        echo -n "$WRANGLER_PROXY_SECRET" | docker compose run --rm -T ercot-proxy secret put WRANGLER_PROXY_SECRET
        ;;
    deploy)
        docker compose run --rm ercot-proxy deploy
        ;;
    *)
        echo "Usage: $0 {secret|deploy}" >&2
        exit 1
        ;;
esac
