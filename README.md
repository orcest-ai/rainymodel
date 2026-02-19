<a name="readme-top"></a>

<div align="center">
  <h1 align="center" style="border-bottom: none">RainyModel: LLM Routing Proxy</h1>
  <p align="center"><b>Part of the Orcest AI Ecosystem</b></p>
</div>

<div align="center">
  <a href="https://github.com/orcest-ai/rainymodel/blob/main/LICENSE"><img src="https://img.shields.io/badge/LICENSE-MIT-20B2AA?style=for-the-badge" alt="MIT License"></a>
</div>

<hr>

RainyModel is an intelligent LLM routing proxy that provides OpenAI-compatible API endpoints with automatic routing across free, internal, and premium providers. It is the central LLM orchestration layer of the **Orcest AI** ecosystem.

### Orcest AI Ecosystem

| Service | Domain | Role |
|---------|--------|------|
| **Lamino** | llm.orcest.ai | LLM Workspace |
| **RainyModel** | rm.orcest.ai | LLM Routing Proxy |
| **Maestrist** | agent.orcest.ai | AI Agent Platform |
| **Orcide** | ide.orcest.ai | Cloud IDE |
| **Login** | login.orcest.ai | SSO Authentication |

## Features

- **Smart Routing**: Automatic routing chain: FREE (HF) -> INTERNAL (Ollama) -> PREMIUM (OpenRouter)
- **OpenAI-Compatible API**: Drop-in replacement for any OpenAI-compatible client
- **Model Aliases**: `rainymodel/auto`, `rainymodel/chat`, `rainymodel/code`, `rainymodel/agent`
- **Dual Ollama Backends**: 16GB primary (qwen2.5:14b) + 8GB secondary (qwen2.5:7b)
- **Policy Headers**: `X-RainyModel-Policy` for routing control (default/uncensored/premium)
- **Observability**: Response headers with route, upstream, model, latency info
- **Circuit Breaker**: Automatic failover on upstream errors
- **Rate Limiting**: Per-user API key rate limits

## API Endpoints

```
POST /v1/chat/completions  - Chat completions (OpenAI-compatible)
GET  /v1/models            - List available model aliases
GET  /health               - Health check
```

## Model Aliases

| Alias | Use Case | Routing Priority |
|-------|----------|-----------------|
| `rainymodel/auto` | General purpose | HF -> Ollama -> OpenRouter |
| `rainymodel/chat` | Conversational | HF -> Ollama -> OpenRouter |
| `rainymodel/code` | Code generation | HF Coder -> Ollama Coder -> OpenRouter |
| `rainymodel/agent` | Agent tasks | HF -> Ollama -> OpenRouter |

## Response Headers

| Header | Description |
|--------|-------------|
| `x-rainymodel-route` | free / internal / premium |
| `x-rainymodel-upstream` | hf / ollama / openrouter |
| `x-rainymodel-model` | Actual model used |
| `x-rainymodel-latency-ms` | Request latency |

## Deployment

Deployed on Render with auto-deploy from `main` branch. See `render.yaml` for configuration.

## License

This project is licensed under the [MIT License](LICENSE).

Part of the [Orcest AI](https://orcest.ai) ecosystem.
