# CLAUDE.md

## Project Overview

RainyModel is an intelligent LLM routing proxy for the Orcest AI ecosystem (orcest.ai). It provides OpenAI-compatible API endpoints and automatically routes requests across multiple LLM providers using a tiered strategy:

- **FREE**: HuggingFace Router (free credits)
- **INTERNAL**: Self-hosted Ollama backends (16GB primary, 8GB secondary)
- **PREMIUM**: OpenRouter (paid fallback)

Other Orcest services (Lamino, Maestrist, Orcide) use RainyModel as their unified LLM access layer.

## Repository Structure

```
app/
  main.py          # FastAPI app, endpoints, auth, lifespan, request handling
  routing.py       # RainyModelRouter: tier classification and policy-based routing
config/
  litellm_config.yaml  # Model alias definitions and backend deployments
docs/
  architecture.md      # Ecosystem architecture and network diagrams
  runbook.md           # Operations, troubleshooting, key rotation
  team-onboarding.md   # Integration guides for team members
  omail-dns-checklist.md
```

## Tech Stack

- **Language**: Python 3.11+ (runtime uses 3.12-slim Docker image)
- **Framework**: FastAPI + Uvicorn
- **LLM Abstraction**: LiteLLM (routing, retries, circuit breaker)
- **HTTP Client**: httpx
- **Validation**: Pydantic v2
- **Config**: YAML + environment variable expansion

## Key Commands

```bash
# Install dependencies
pip install -e .

# Install with dev dependencies (ruff, pytest)
pip install -e ".[dev]"

# Run the server locally
uvicorn app.main:app --host 0.0.0.0 --port 8080

# Lint
ruff check .

# Format
ruff format .

# Run tests
pytest
```

## Environment Variables

Copy `.env.example` to `.env` and fill in values. Required variables:

| Variable | Purpose |
|---|---|
| `RAINYMODEL_MASTER_KEY` | Bearer token for API auth (empty = no auth) |
| `HF_TOKEN` | HuggingFace API token |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `OLLAMA_BASE_URL` | Primary Ollama server URL |
| `OLLAMA_API_KEY` | Ollama API key (typically `ollama`) |
| `OLLAMAFREE_API_BASE` | Free Ollama proxy base URL |
| `OLLAMAFREE_API_KEY` | Free Ollama proxy key |
| `LITELLM_CONFIG_PATH` | Path to `litellm_config.yaml` (defaults to `config/litellm_config.yaml`) |
| `RAINYMODEL_DEBUG` | Set `true` for verbose LiteLLM logging |

## Architecture

### Model Aliases

Four model aliases route to different backend deployments:

| Alias | Use Case | Primary Model |
|---|---|---|
| `rainymodel/auto` | General purpose | Qwen2.5-72B |
| `rainymodel/chat` | Conversation | Qwen2.5-72B |
| `rainymodel/code` | Code generation | Qwen2.5-Coder-32B/7B |
| `rainymodel/agent` | Agent/complex tasks | Claude Sonnet 4 (OpenRouter) |

### Routing Tiers

Each alias has multiple backend deployments classified into tiers. The `RainyModelRouter` (`app/routing.py`) orders deployments based on the `X-RainyModel-Policy` header:

| Policy | Tier Order |
|---|---|
| `auto` (default) | FREE -> INTERNAL -> PREMIUM |
| `uncensored` | INTERNAL -> FREE -> PREMIUM |
| `premium` | PREMIUM -> FREE -> INTERNAL |
| `free` | FREE -> INTERNAL -> PREMIUM (free only preferred) |

Requests fall through tiers sequentially on failure (circuit breaker pattern).

### API Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/` | No | Service info |
| `GET` | `/health` | No | Health check |
| `GET` | `/v1/models` | Yes | List model aliases |
| `POST` | `/v1/chat/completions` | Yes | Chat completions (OpenAI-compatible) |

Swagger/OpenAPI docs are disabled in production (`docs_url=None`, `redoc_url=None`, `openapi_url=None`).

### Response Headers

Successful responses include routing metadata:
- `x-rainymodel-route`: Tier used (`free`, `internal`, `premium`)
- `x-rainymodel-upstream`: Provider (`hf`, `ollama`, `openrouter`, `ollamafreeapi`)
- `x-rainymodel-model`: Actual model used
- `x-rainymodel-latency-ms`: End-to-end latency
- `x-rainymodel-fallback-reason`: Present if a fallback occurred

## Code Conventions

- **Module docstrings**: Every Python file starts with a module-level docstring describing purpose and routing context.
- **Type hints**: Uses Python 3.10+ union syntax (`X | None` instead of `Optional[X]`).
- **Naming**: Private functions/variables prefixed with `_` (e.g., `_router`, `_check_auth`, `_expand_env`).
- **Constants**: Tier identifiers are class-level string constants on `RainyModelRouter`.
- **Config expansion**: Environment variables in YAML use `${VAR}` or `${VAR:-default}` syntax, expanded by `_expand_env()` in `app/main.py`.
- **Error handling**: Sequential fallthrough with last-error tracking; 502 returned when all upstreams fail.
- **Linter**: ruff (configured via pyproject.toml dev deps, no custom ruff config — uses defaults).
- **No Swagger exposure**: API docs endpoints are explicitly disabled for security.

## Deployment

- **Platform**: Render.com (auto-deploy from `main` branch)
- **Domain**: `rm.orcest.ai`
- **Container**: Docker (Python 3.12-slim, non-root `appuser`)
- **Port**: 8080 (configurable via `PORT` env var)
- **Health check**: `GET /health`

## Testing

pytest is configured as a dev dependency. No test suite exists yet. When adding tests:
- Place test files in a `tests/` directory
- Name files `test_*.py`
- Run with `pytest`

## Adding a New Model Alias

1. Add deployment entries in `config/litellm_config.yaml` under a new `model_name` (e.g., `rainymodel/newname`)
2. Add the alias to `KNOWN_MODELS` list in `app/main.py`
3. The `RainyModelRouter` auto-classifies tiers from `api_base`/`description` fields — no routing code changes needed

## Adding a New Backend Provider

1. Add deployment entries in `config/litellm_config.yaml` with appropriate `litellm_params`
2. Ensure `_classify_tier()` in `app/routing.py` can correctly classify the new provider's tier
3. Add any new env vars to `.env.example`

## Code Ownership

All files owned by @danialsamiei (see `.github/CODEOWNERS`).
