# RainyModel

Intelligent LLM routing proxy for the [Orcest AI](https://orcest.ai) ecosystem.

## Architecture

```
Clients (Lamino, Maestrist, Orcide, orcest.ai)
              |
              v
    +-------------------+
    |   RainyModel      |  rm.orcest.ai
    |   Proxy           |  OpenAI-compatible API
    +-----+-----+------+
          |     |     |
    +-----+  +--+  +--+----+
    v        v         v
 FREE     INTERNAL   PREMIUM
 (HF/     (Ollama    (OpenRouter)
  ollamafree) DO)
```

## Model Aliases

| Alias | Use Case | Routing Priority |
|-------|----------|-----------------|
| `rainymodel/auto` | General purpose | FREE -> INTERNAL -> PREMIUM |
| `rainymodel/chat` | Conversation/Persian | FREE -> INTERNAL -> PREMIUM |
| `rainymodel/code` | Coding tasks | FREE -> INTERNAL -> PREMIUM |
| `rainymodel/agent` | Agent/complex tasks | FREE -> PREMIUM -> INTERNAL |

## API Endpoints

- `GET /v1/models` - List available models
- `POST /v1/chat/completions` - Chat completions (OpenAI-compatible)
- `GET /health` - Health check

## Response Headers

Every response includes routing observability headers:

- `x-rainymodel-route`: `free` | `internal` | `premium`
- `x-rainymodel-upstream`: `ollamafreeapi` | `hf` | `ollama` | `openrouter`
- `x-rainymodel-model`: actual model used
- `x-rainymodel-latency-ms`: request latency

## Routing Policies

Set via `X-RainyModel-Policy` header:

- `auto` (default): cheapest/free first
- `uncensored`: prefer internal Ollama (abliterated models)
- `premium`: prefer OpenRouter
- `free`: only use free tiers

## Quick Start

```bash
cp .env.example .env
# Edit .env with your keys

pip install .
uvicorn app.main:app --host 0.0.0.0 --port 8080

# Or with Docker
docker build -t rainymodel .
docker run -p 8080:8080 --env-file .env rainymodel
```

## Deployment

Deployed on Render via `render.yaml`. Auto-deploys from `main` branch.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `RAINYMODEL_MASTER_KEY` | Yes | API authentication key |
| `HF_TOKEN` | Yes | Hugging Face token for HF Router |
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key |
| `OLLAMA_BASE_URL` | No | Ollama server URL |
| `OLLAMA_API_KEY` | No | Ollama auth token |
| `OLLAMAFREE_API_BASE` | No | Free Ollama API proxy URL |

## License

MIT
