#!/usr/bin/env bash
# Ask the Budget AZ — one-shot setup for a fresh clone.
#
# What this does:
#   - Verifies prerequisites (node, uv) are installed
#   - Runs `uv sync` to set up the Python venv from uv.lock
#   - Installs + builds webapp/ (the live SPA — the only Node tree left;
#     mcp-server/ and web/ were deleted in Plan 5 Track 4)
#
# There is no Postgres step and no Docker step. Plan 1 moved retrieval to
# embedded LanceDB and Plan 3 moved ingest off Postgres; Plan 5 Track 4
# deleted db/ outright. Nothing this repo does needs a database server.
#
# What this does NOT do (deliberately):
#   - Restore the corpus (data/insight-data/ + data/cached-pdfs/). Copy
#     both from a working machine or the shared drive. See
#     README.md → "Moving to a new device" for the manual steps.
#   - Configure any API key. None are needed — search, fiscal notes and
#     upload run keyless. The one optional key (OpenRouter, for AI Mode)
#     goes in <data_dir>/settings.json, not an env file.
#   - Start the app. Setup is install-only; see README.md →
#     "Running it locally" for the launch commands.
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

# Docker is NOT a prerequisite and neither is Postgres — Plan 5 Track 4
# deleted the last of that tree. Node is here only to build the SPA; the
# shipped app serves a static bundle.
command -v node   >/dev/null 2>&1 || fail "node is not installed. Install Node 20+: https://nodejs.org"
command -v npm    >/dev/null 2>&1 || fail "npm is not installed."
command -v uv     >/dev/null 2>&1 || fail "uv is not installed. Install with: pip install uv  (https://github.com/astral-sh/uv)"

node_major="$(node --version | sed 's/^v\([0-9]*\).*/\1/')"
if [ "$node_major" -lt 20 ]; then
    fail "Node $(node --version) is too old. Need Node 20+."
fi

# No .env.local check: nothing at runtime needs an env file or any key.
# The only optional key (OpenRouter, for AI Mode) lives in the app's
# <data_dir>/settings.json and is entered through the UI.

echo "  OK: node $(node --version), npm $(npm --version), uv $(uv --version)"

# -----------------------------------------------------------------------------
# Python deps
# -----------------------------------------------------------------------------

step "Installing Python dependencies (uv sync)"
uv sync

# -----------------------------------------------------------------------------
# Webapp (the consolidated app's SPA — Plan 2)
# -----------------------------------------------------------------------------

step "Installing webapp/ dependencies (npm ci)"
( cd webapp && npm ci )

step "Building webapp (vite)"
( cd webapp && npm run build )

# -----------------------------------------------------------------------------
# Tests (optional)
# -----------------------------------------------------------------------------

if [ "$VERIFY" -eq 1 ]; then
    step "Running Python tests (pytest)"
    # No .env.local sourcing: there is no env file on any path any more, and
    # sourcing one used to leak DATABASE_URL into the process, un-skipping the
    # Postgres suites mid-run. Those suites are gone; so is the sourcing.
    uv run pytest -q

    step "Running webapp tests (vitest)"
    ( cd webapp && npx vitest run )
fi

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------

cat <<'NEXT'

==> Setup complete.

Next steps:
  1. The corpus travels as a data directory, NOT via .env.local or Postgres
     (Plan 1 moved retrieval to embedded LanceDB; Plan 3 dropped Postgres and
     Docker from every runtime path). If you have one from a working machine,
     copy it over — both pieces:
        scp -r olduser@oldhost:/path/to/ask-the-budget-az-dev/data/insight-data ./data/insight-data
        scp -r olduser@oldhost:/path/to/ask-the-budget-az-dev/data/cached-pdfs ./data/cached-pdfs

     `data/insight-data/` (the `lancedb/` folder AND `documents.json`) is what
     makes search real; `data/cached-pdfs/` is what the PDF viewer streams
     from. Set JLBC_DATA_DIR to point at a non-default location. Without a
     corpus the app still boots and serves fixture search results, so this
     step is optional for exploring the UI.

  2. Start the app — one process, no sidecar, no MCP server, no YouCoded
     (Plan 4 replaced all three with an in-process OpenRouter tool loop):
        uv run uvicorn app.main:create_app --factory --port 9300

     Then open http://localhost:9300 — the webapp/ SPA it serves covers
     budget search, fiscal notes, and upload with zero API keys.

  3. AI Mode is optional and needs exactly one key. Create
     <data_dir>/settings.json (next to data/insight-data/, or under
     JLBC_DATA_DIR if you set it) with:
        { "provider": { "api_key": "<your-openrouter-key>" } }
     No key, no problem — everything except AI Mode's chat answers works
     without it; that's a hard spec constraint, not a fallback.

  See README.md and STATUS.md for more.

NEXT
