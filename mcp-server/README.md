# Budget MCP server

A small Node process that registers the Ask the Budget AZ retrieval
tools with a running YouCoded instance, so any Claude session under
that YouCoded can call:

- `retrieve(query, filters?, top_k?)` — hybrid BM25+dense+rerank over
  the Arizona budget corpus
- `cite(chunk_id, span_start, span_end, confidence, claim_span)` —
  per-claim citation with server-side validation

Schema lock:
[`docs/superpowers/decisions/2026-05-06-citation-tool-schema.md`](../docs/superpowers/decisions/2026-05-06-citation-tool-schema.md).

System prompt that constrains how Claude uses these tools:
[`mcp-server/system-prompt.md`](./system-prompt.md). The web server
(Phase 1c WS2) materializes that file into the budget conversation's
working-directory `CLAUDE.md`.

---

## How it fits

```
┌──────────────────┐       stdio          ┌──────────────────────┐
│ YouCoded         │ ◄──── MCP ─────►    │ Budget MCP server    │
│ (Claude Code)    │                      │ (this package)       │
└──────────────────┘                      └─────────┬────────────┘
                                                    │ HTTP
                                                    ▼
                                          ┌──────────────────────┐
                                          │ FastAPI sidecar      │
                                          │ retrieval/api.py     │
                                          │ (localhost:9200)     │
                                          └─────────┬────────────┘
                                                    │ psycopg / Voyage
                                                    ▼
                                          ┌──────────────────────┐
                                          │ Postgres + Voyage    │
                                          └──────────────────────┘
```

YouCoded launches the MCP server as a subprocess (stdio JSON-RPC) when
it sees the entry in `~/.claude.json`. The server forwards every
`retrieve` / `cite` call to the FastAPI sidecar, which owns the
Postgres connection pool and the Voyage SDK client.

---

## Quick start

### 1. Install + build

```bash
cd mcp-server
npm install
npm run build
```

### 2. Run the FastAPI sidecar

The MCP server is a thin shim — it has no value without the sidecar
running. From the project root:

```bash
# No API key or database needed: retrieval reads the LanceDB corpus under
# JLBC_DATA_DIR (unset = data/insight-data in the repo).
uv run uvicorn retrieval.api:app --host 127.0.0.1 --port 9200
```

Health check:

```bash
curl http://127.0.0.1:9200/health
# { "status": "ok", "version": "0.1.0", "corpus_chunks": 7755,
#   "documents_metadata": 382, "data_dir": "…/data/insight-data" }
# (503 + { "status": "degraded", "error": … } if the corpus is unreachable)
```

### 3. Register with YouCoded

```bash
node scripts/register.mjs
```

This writes an entry into `~/.claude.json` (or `$CLAUDE_CONFIG_PATH`
if you want to point elsewhere for testing). The script is idempotent
and creates a timestamped `.bak-…` backup of the config before
modifying it.

```bash
# Preview the change without writing:
node scripts/register.mjs --dry-run

# Remove the entry:
node scripts/register.mjs --remove
```

### 4. Restart YouCoded

YouCoded's MCP host loads `~/.claude.json` at startup. Existing
sessions don't pick up new servers — quit and re-open YouCoded.

### 5. Verify in YouCoded

Open a new Claude session in YouCoded. Type `/mcp` (or run a probe
query like "What's the balance of the Aviation Fund?"). You should
see `ask-the-budget-az` listed with two tools — `retrieve` and
`cite`. Claude should call `retrieve()` automatically when the system
prompt is in place (see Phase 1c WS2 for the prompt-loading
mechanism).

---

## Development

### Running tests

```bash
npm test            # vitest run, no watch
npm run test:watch  # watch mode for iteration
```

Unit tests stub the FastAPI bridge with a fake `fetch`, so no
Postgres / Voyage / live sidecar is required for the test suite.

### Type checking

```bash
npm run typecheck
```

`tsc -p . --noEmit` with `strict: true` and `noUncheckedIndexedAccess: true`.

### Local dev (no built artifact yet)

```bash
npm run dev
# tsx src/index.ts — runs against TypeScript source via tsx
```

Useful when iterating on the tool schemas. To register dev mode in
YouCoded, edit `~/.claude.json` by hand and point `command` at `npx
tsx <repo>/mcp-server/src/index.ts`.

---

## Configuration

Set via environment variables read at startup (the MCP host inherits
the env from YouCoded's process; you can override per-server in
`~/.claude.json`'s `env` block):

| Var | Default | Purpose |
|---|---|---|
| `RETRIEVAL_BRIDGE_URL` | `http://127.0.0.1:9200` | Where the FastAPI sidecar is listening. |
| `RETRIEVAL_BRIDGE_TIMEOUT_MS` | `15000` | Per-call HTTP timeout. Voyage rerank can take ~1s on a cold cache; this leaves headroom for the slowest synchronous case. |
| `CLAUDE_CONFIG_PATH` | `~/.claude.json` | Override the registration target (used in tests). |

---

## Troubleshooting

### YouCoded shows the server but tool calls all fail

Check the FastAPI sidecar:

```bash
curl http://127.0.0.1:9200/health
```

If it errors:
1. Is uvicorn running? `tasklist | findstr uvicorn` (Windows) /
   `ps -ef | grep uvicorn` (Unix).
2. Does `/health` report `corpus_chunks: 0`? The sidecar is pointed at a
   data folder with no corpus in it — check `JLBC_DATA_DIR` and that its
   `lancedb` directory was copied over. The sidecar also fails fast at
   startup for this, so check its stderr.

### `claude mcp list` shows the server but `/mcp` says "Failed"

Per the workspace PITFALLS entry "MCP Plugin Authoring": `claude mcp
list` only validates the `initialize` JSON-RPC step. The in-session
`/mcp` host runs the full handshake including `tools/list`. If the
two diverge, the server's tool registration is rejecting on schema
validation — run `npm run typecheck && npm test` to surface the
mismatch.

### Hot-reload during development

The MCP host doesn't watch its server processes. After editing
`src/`, run `npm run build` and restart the YouCoded session (not the
whole app — closing the chat is enough).

---

## Files

| Path | Purpose |
|---|---|
| `src/index.ts` | Entry point: constructs `McpServer`, registers tools, connects stdio transport |
| `src/config.ts` | Env-driven config (bridge URL, timeout) |
| `src/lib/bridge.ts` | HTTP client + error shape for sidecar calls |
| `src/tools/retrieve.ts` | `retrieve` tool — schema, handler, registration |
| `src/tools/cite.ts` | `cite` tool — schema, handler, registration |
| `system-prompt.md` | Constrained-agent system prompt for Claude sessions using these tools |
| `scripts/register.mjs` | Idempotent `~/.claude.json` registration helper |
| `scripts/smoke.mjs` | End-to-end smoke test against a running FastAPI sidecar (dev-only, not in the test suite) |
| `tests/retrieve.test.ts`, `tests/cite.test.ts` | vitest unit tests |
