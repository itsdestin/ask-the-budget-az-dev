#!/usr/bin/env bash
# Ask the Budget AZ — one-shot setup for a fresh clone.
#
# What this does:
#   - Verifies prerequisites (docker, node, uv) are installed
#   - Runs `uv sync` to set up the Python venv from uv.lock
#   - Runs `npm ci` in mcp-server/ and web/
#   - Builds the MCP server (tsc)
#   - Brings up the Postgres container (Docker Compose)
#   - Validates the DB is reachable
#
# What this does NOT do (deliberately):
#   - Restore database data (db/data/). You either copy that directory
#     from a working machine OR re-run the ingest pipeline. See
#     README.md → "Moving to a new device" for the manual steps.
#   - Create .env.local. Copy it from a working machine OR populate
#     by hand (Voyage API key required).
#   - Start the three runtime processes. Setup is install-only; see
#     README.md → "Running it" for the launch commands.
#
# Flags:
#   --verify    Also run all test suites after setup.

set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
VERIFY=0
for arg in "$@"; do
    case "$arg" in
        --verify) VERIFY=1 ;;
        *)
            echo "Unknown flag: $arg" >&2
            echo "Usage: $0 [--verify]" >&2
            exit 2
            ;;
    esac
done

step() {
    echo
    echo "==> $*"
}

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

# -----------------------------------------------------------------------------
# Prerequisites
# -----------------------------------------------------------------------------

step "Checking prerequisites"

command -v docker >/dev/null 2>&1 || fail "docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop"
command -v node   >/dev/null 2>&1 || fail "node is not installed. Install Node 20+: https://nodejs.org"
command -v npm    >/dev/null 2>&1 || fail "npm is not installed."
command -v uv     >/dev/null 2>&1 || fail "uv is not installed. Install with: pip install uv  (https://github.com/astral-sh/uv)"

node_major="$(node --version | sed 's/^v\([0-9]*\).*/\1/')"
if [ "$node_major" -lt 20 ]; then
    fail "Node $(node --version) is too old. Need Node 20+."
fi

if [ ! -f .env.local ]; then
    echo "  WARNING: .env.local is missing."
    echo "  You'll need to create it before the sidecar can call Voyage."
    echo "  Template:"
    echo "    POSTGRES_PASSWORD=askbudget-dev"
    echo "    DATABASE_URL=postgresql://askbudget:askbudget-dev@127.0.0.1:5432/askbudget"
    echo "    VOYAGE_API_KEY=<your-key>"
fi

echo "  OK: docker, node $(node --version), npm $(npm --version), uv $(uv --version)"

# -----------------------------------------------------------------------------
# Python deps
# -----------------------------------------------------------------------------

step "Installing Python dependencies (uv sync)"
uv sync

# -----------------------------------------------------------------------------
# MCP server
# -----------------------------------------------------------------------------

step "Installing mcp-server/ dependencies (npm ci)"
( cd mcp-server && npm ci )

step "Building mcp-server (tsc)"
( cd mcp-server && npm run build )

# -----------------------------------------------------------------------------
# Web app
# -----------------------------------------------------------------------------

step "Installing web/ dependencies (npm ci)"
( cd web && npm ci )

# -----------------------------------------------------------------------------
# Webapp (the consolidated app's SPA — Plan 2)
# -----------------------------------------------------------------------------

step "Installing webapp/ dependencies (npm ci)"
( cd webapp && npm ci )

step "Building webapp (vite)"
( cd webapp && npm run build )

# -----------------------------------------------------------------------------
# Postgres
# -----------------------------------------------------------------------------

step "Starting Postgres (docker compose up -d)"
( cd db && docker compose up -d )

# Give Postgres a moment to accept connections before validating.
echo "  Waiting for Postgres to become healthy..."
deadline=$(( $(date +%s) + 60 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    if ( cd db && docker compose ps --format json 2>/dev/null | grep -q '"Health":"healthy"' ); then
        break
    fi
    sleep 2
done

# -----------------------------------------------------------------------------
# DB reachability check
# -----------------------------------------------------------------------------

step "Validating DB reachability"
if [ -f .env.local ]; then
    set -a
    # shellcheck disable=SC1091
    source .env.local
    set +a
    if uv run python -m db.validate 2>&1 | tee /tmp/budget-validate.log | tail -5; then
        echo "  OK: DB reachable"
    else
        echo
        echo "  DB validate failed. This is expected on a fresh machine with no data."
        echo "  See README.md → 'Moving to a new device' to populate the DB."
    fi
else
    echo "  Skipped (no .env.local)"
fi

# -----------------------------------------------------------------------------
# Tests (optional)
# -----------------------------------------------------------------------------

if [ "$VERIFY" -eq 1 ]; then
    step "Running Python tests (pytest)"
    if [ -f .env.local ]; then
        set -a
        # shellcheck disable=SC1091
        source .env.local
        set +a
    fi
    uv run pytest -q

    step "Running MCP server tests (vitest)"
    ( cd mcp-server && npm test -- --run )

    step "Running web tests (vitest)"
    ( cd web && npm test -- --run )

    step "Running webapp tests (vitest)"
    ( cd webapp && npx vitest run )
fi

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------

cat <<'NEXT'

==> Setup complete.

Next steps:
  1. If you haven't yet, create .env.local at the repo root with at minimum
     POSTGRES_PASSWORD, DATABASE_URL, and VOYAGE_API_KEY.

  2. If the DB is empty, populate it from a working machine:
        scp -r olduser@oldhost:/path/to/ask-the-budget-az-dev/db/data ./db/data
        ( cd db && docker compose restart )

     Or re-run the ingest pipeline (slow, costs API calls) — see PROMPT-volume-ingest.md.

  3. Start the three runtime processes in separate terminals:
        # Sidecar
        set -a; source .env.local; set +a
        uv run uvicorn retrieval.api:app --host 127.0.0.1 --port 9200

        # MCP server (register, then restart YouCoded so it picks up the registration)
        node mcp-server/scripts/register.mjs

        # Web UI
        ( cd web && npm run dev )

     Then open http://localhost:3000 with YouCoded running.

  See README.md and STATUS.md for more.

NEXT
