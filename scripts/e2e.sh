#!/usr/bin/env bash
# Runs the Playwright UI suite end-to-end:
#   1. starts the FastAPI backend with the dev-bypass single-user gate,
#   2. starts the Next.js dev server pointed at it,
#   3. waits for both to be reachable,
#   4. runs `playwright test`,
#   5. tears the servers back down.
#
# Browsers are expected at /opt/pw-browsers (matching @playwright/test 1.56.x).
# Override with PLAYWRIGHT_BROWSERS_PATH if you've installed them elsewhere.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${POSTMORTEM_BACKEND_PORT:-8100}"
FRONTEND_PORT="${POSTMORTEM_FRONTEND_PORT:-3000}"
DB_FILE="$REPO_ROOT/backend/_e2e.db"
LOG_DIR="$(mktemp -d)"

cleanup() {
  set +e
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null
  [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null
  rm -f "$DB_FILE"
}
trap cleanup EXIT

rm -f "$DB_FILE"

(
  cd "$REPO_ROOT/backend"
  PYTHONPATH=. \
  POSTMORTEM_DEV_BYPASS=1 \
  POSTMORTEM_DATABASE_URL="sqlite:///./_e2e.db" \
  POSTMORTEM_CORS_ORIGINS="http://localhost:$FRONTEND_PORT,http://127.0.0.1:$FRONTEND_PORT" \
  python3 -m uvicorn postmortem.app:app \
    --host 127.0.0.1 --port "$BACKEND_PORT" --log-level warning \
    >"$LOG_DIR/backend.log" 2>&1
) &
BACKEND_PID=$!

(
  cd "$REPO_ROOT/frontend"
  NEXT_PUBLIC_POSTMORTEM_API_BASE="http://localhost:$BACKEND_PORT" \
  NEXT_PUBLIC_POSTMORTEM_API_TOKEN="" \
  npx next dev -p "$FRONTEND_PORT" -H 0.0.0.0 \
    >"$LOG_DIR/frontend.log" 2>&1
) &
FRONTEND_PID=$!

echo "Waiting for backend on :$BACKEND_PORT ..."
until curl -sf "http://127.0.0.1:$BACKEND_PORT/healthz" >/dev/null; do sleep 1; done
echo "Waiting for frontend on :$FRONTEND_PORT ..."
until curl -sf -o /dev/null "http://localhost:$FRONTEND_PORT/incidents"; do sleep 2; done

cd "$REPO_ROOT/frontend"
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}" \
UI_BASE="http://localhost:$FRONTEND_PORT" \
npx playwright test "$@"
