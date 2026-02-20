# Orcest AI — API Architecture & Connection Map

## 1. High-Level Ecosystem

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                          USERS / CLIENTS                               │
 │   Browser  ·  Orcide Desktop  ·  curl/SDK  ·  Maestrist CLI           │
 └─────┬──────────────┬──────────────┬──────────────┬─────────────────────┘
       │              │              │              │
       │   HTTPS      │   HTTPS      │   HTTPS      │   HTTPS
       ▼              ▼              ▼              ▼
 ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────────┐
 │  Lamino   │ │  Orcide   │ │ Maestrist │ │ orcest.ai │ │    Login      │
 │  (Chat)   │ │  (IDE)    │ │  (Agent)  │ │ (Landing) │ │    (SSO)      │
 │  llm.     │ │  ide.     │ │  agent.   │ │           │ │  login.       │
 │ orcest.ai │ │ orcest.ai │ │ orcest.ai │ │ orcest.ai │ │  orcest.ai   │
 └─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └───────────┘ └──────┬────────┘
       │              │              │                             │
       │   OpenAI     │  OpenAI      │  OpenAI                    │ OIDC
       │   compat.    │  compat.     │  compat.                   │ OAuth2
       │              │              │                             │
       └──────────────┴──────┬───────┘          ┌─────────────────┘
                             │                  │
                             ▼                  │  All services verify
                    ┌─────────────────┐         │  tokens via OIDC
                    │   RainyModel    │◄────────┘
                    │   (LLM Proxy)   │
                    │  rm.orcest.ai   │
                    │                 │
                    │  FastAPI +      │
                    │  LiteLLM        │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
     ┌──────────────┐ ┌───────────┐ ┌──────────────┐
     │  FREE Tier   │ │ INTERNAL  │ │ PREMIUM Tier │
     │              │ │   Tier    │ │              │
     │ HuggingFace  │ │ Ollama    │ │ OpenRouter   │
     │ Router       │ │ (DO CPU)  │ │              │
     │              │ │           │ │              │
     │ OllamaFree   │ │ Primary   │ │ Claude       │
     │ API          │ │ Secondary │ │ Qwen-72B     │
     └──────────────┘ └───────────┘ └──────────────┘
```

---

## 2. Service Inventory

| Service | Domain | Stack | Port | Hosting | Repo |
|---------|--------|-------|------|---------|------|
| Landing Page | `orcest.ai` | FastAPI | - | Render | `orcest-ai/orcest.ai` |
| Lamino | `llm.orcest.ai` | Node.js (AnythingLLM fork) | - | Render | `orcest-ai/Lamino` |
| Orcide | `ide.orcest.ai` | VS Code fork (Electron) | - | Render | `orcest-ai/Orcide` |
| Maestrist | `agent.orcest.ai` | Python (OpenHands fork) | 3000 | Render | `orcest-ai/Maestrist` |
| RainyModel | `rm.orcest.ai` | FastAPI + LiteLLM | 8080 | Render | `orcest-ai/rainymodel` |
| Login SSO | `login.orcest.ai` | FastAPI + SQLAlchemy | 10000 | Render + PostgreSQL | `orcest-ai/login` |
| OllamaFreeAPI | `ollamafreeapi.orcest.ai` | Flask/FastAPI | - | Render | `danialsamiei/ollamafreeapi.orcest.ai` |
| Ollama Primary | `164.92.147.36:11434` | Ollama | 11434 | DigitalOcean 16GB | - |
| Ollama Secondary | `178.128.196.3:11434` | Ollama | 11434 | DigitalOcean 8GB | - |
| Status Page | `status.orcest.ai` | TBD | - | - | `orcest-ai/status` |

---

## 3. RainyModel API Endpoints

RainyModel is the central LLM gateway — all services talk to it via an OpenAI-compatible interface.

### 3.1 Exposed Routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/` | No | Service info + available endpoints |
| `GET` | `/health` | No | Health check |
| `GET` | `/v1/models` | Bearer | List model aliases |
| `POST` | `/v1/chat/completions` | Bearer | Chat completions (streaming + non-streaming) |

**Auth**: `Authorization: Bearer <RAINYMODEL_MASTER_KEY>`

**Swagger/OpenAPI**: Disabled in production (`docs_url=None`, `redoc_url=None`, `openapi_url=None`)

### 3.2 Model Aliases

| Alias | Use Case | Primary Model (Free) | Internal Model | Premium Model |
|-------|----------|---------------------|----------------|---------------|
| `rainymodel/auto` | General purpose | Qwen2.5-72B (HF) | qwen2.5:14b (Ollama) | Qwen2.5-72B (OpenRouter) |
| `rainymodel/chat` | Conversation / Persian | Qwen2.5-72B (HF) | qwen2.5:14b (Ollama) | Qwen2.5-72B (OpenRouter) |
| `rainymodel/code` | Code generation | Qwen2.5-Coder-32B (HF) | qwen2.5-coder:7b (Ollama) | Qwen2.5-Coder-32B (OpenRouter) |
| `rainymodel/agent` | Complex agent tasks | Qwen2.5-72B (HF) | qwen2.5:14b (Ollama) | **Claude Sonnet 4** (OpenRouter) |

### 3.3 Routing Policy (`X-RainyModel-Policy` header)

```
┌──────────────┬─────────────────────────────────────────┐
│ Policy       │ Tier Order (fallthrough on failure)      │
├──────────────┼─────────────────────────────────────────┤
│ auto         │ FREE ──▶ INTERNAL ──▶ PREMIUM           │
│ uncensored   │ INTERNAL ──▶ FREE ──▶ PREMIUM           │
│ premium      │ PREMIUM ──▶ INTERNAL ──▶ FREE           │
│ free         │ FREE only (no fallthrough)               │
└──────────────┴─────────────────────────────────────────┘
```

### 3.4 Response Observability Headers

```
x-rainymodel-route:           free | internal | premium
x-rainymodel-upstream:        hf | ollama | openrouter | ollamafreeapi
x-rainymodel-model:           actual-model-name
x-rainymodel-latency-ms:      1234
x-rainymodel-fallback-reason:  (present only if fallback occurred)
```

---

## 4. Upstream Connections (RainyModel → LLM Providers)

```
                    ┌─────────────────────────────┐
                    │        RainyModel            │
                    │       rm.orcest.ai           │
                    │                             │
                    │  LiteLLM Router             │
                    │  ┌───────────────────────┐  │
                    │  │ Circuit Breaker:       │  │
                    │  │  retries: 3            │  │
                    │  │  allowed_fails: 2      │  │
                    │  │  cooldown: 60s         │  │
                    │  └───────────────────────┘  │
                    └──┬──────┬──────┬──────┬─────┘
                       │      │      │      │
          ┌────────────┘      │      │      └────────────┐
          │                   │      │                   │
          ▼                   ▼      ▼                   ▼
 ┌──────────────┐  ┌──────────┐ ┌──────────┐  ┌──────────────────┐
 │ HuggingFace  │  │ Ollama   │ │ Ollama   │  │   OpenRouter     │
 │ Router       │  │ Primary  │ │Secondary │  │                  │
 │              │  │          │ │          │  │                  │
 │ router.hf.  │  │164.92.   │ │178.128.  │  │ openrouter.ai    │
 │ co/v1       │  │147.36    │ │196.3     │  │ /api/v1          │
 │              │  │:11434/v1 │ │:11434/v1 │  │                  │
 │ Qwen2.5-72B │  │          │ │          │  │ Claude Sonnet 4  │
 │ Qwen-Coder  │  │qwen2.5   │ │qwen2.5   │  │ Qwen2.5-72B     │
 │ -32B        │  │:14b      │ │:7b       │  │ Qwen-Coder-32B  │
 │              │  │qwen2.5-  │ │qwen2.5-  │  │                  │
 │              │  │coder:7b  │ │coder:7b  │  │                  │
 │ timeout: 60s│  │          │ │          │  │ timeout: 90-120s │
 │ FREE tier   │  │timeout:  │ │timeout:  │  │ PREMIUM tier     │
 │              │  │120s      │ │120s      │  │                  │
 │ Auth:       │  │INTERNAL  │ │INTERNAL  │  │ Auth:            │
 │ HF_TOKEN    │  │tier      │ │tier      │  │ OPENROUTER_      │
 │              │  │          │ │          │  │ API_KEY          │
 │              │  │Auth:     │ │Auth:     │  │                  │
 │              │  │OLLAMA_   │ │OLLAMA_   │  │                  │
 │              │  │API_KEY   │ │API_KEY   │  │                  │
 └──────────────┘  └──────────┘ └──────────┘  └──────────────────┘
       ▲
       │  Also FREE tier
       │
 ┌─────┴──────────┐
 │ OllamaFreeAPI  │
 │ ollamafreeapi  │
 │ .orcest.ai     │
 │                │
 │ Auth:          │
 │ OLLAMAFREE_    │
 │ API_KEY        │
 └────────────────┘
```

### Timeout Configuration

| Upstream | Timeout | Tier |
|----------|---------|------|
| HuggingFace Router | 60s | FREE |
| OllamaFreeAPI | 60s | FREE |
| Ollama Primary (16GB) | 120s | INTERNAL |
| Ollama Secondary (8GB) | 120s | INTERNAL |
| OpenRouter | 90-120s | PREMIUM |

---

## 5. Authentication & SSO Architecture

```
 ┌───────────┐      ┌───────────┐     ┌───────────┐     ┌───────────┐
 │  Lamino   │      │  Orcide   │     │ Maestrist │     │ RainyModel│
 │ llm.      │      │ ide.      │     │ agent.    │     │ rm.       │
 │ orcest.ai │      │ orcest.ai │     │ orcest.ai │     │ orcest.ai │
 └─────┬─────┘      └─────┬─────┘     └─────┬─────┘     └─────┬─────┘
       │                   │                 │                 │
       │ ◄──── OIDC / OAuth2 Authorization Code Flow ────►    │
       │                   │                 │                 │
       └───────────────────┴────────┬────────┘                 │
                                    │                          │
                                    ▼                          │
                           ┌──────────────────┐                │
                           │   Login SSO      │                │
                           │  login.orcest.ai │                │
                           │                  │                │
                           │  OIDC Provider   │                │
                           │  RS256 JWT       │                │
                           │  PostgreSQL      │                │
                           └──────────────────┘                │
                                                               │
                           RainyModel uses its own Bearer      │
                           token auth (RAINYMODEL_MASTER_KEY) ─┘
```

### 5.1 Login SSO — OIDC Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/.well-known/openid-configuration` | OIDC Discovery |
| `GET` | `/oauth2/authorize` | Authorization endpoint |
| `POST` | `/oauth2/token` | Token exchange (auth_code, refresh_token) |
| `GET` | `/oauth2/userinfo` | User info |
| `GET` | `/oauth2/jwks` | JSON Web Key Set |
| `POST` | `/oauth2/revoke` | Token revocation |
| `POST` | `/api/token/verify` | Verify JWT |
| `GET` | `/api/user/{id}/access` | Check user access to service |

### 5.2 Registered OIDC Clients

| Client ID | Service | Redirect URI |
|-----------|---------|-------------|
| `rainymodel` | RainyModel | `https://rm.orcest.ai/auth/callback` |
| `lamino` | Lamino | `https://llm.orcest.ai/auth/callback` |
| `maestrist` | Maestrist | `https://agent.orcest.ai/auth/callback` |
| `orcide` | Orcide | `https://ide.orcest.ai/auth/callback` |
| `orcest` | Orcest AI | `https://orcest.ai/auth/callback` |

### 5.3 RBAC Roles

| Role | Accessible Services | Description |
|------|-------------------|-------------|
| `admin` | `*` (all) | Full access + admin panel |
| `developer` | rm, llm, agent, ide | Development tools |
| `researcher` | rm, llm, orcest | LLM & research |
| `viewer` | llm | Read-only chat |

---

## 6. Per-Service Connection Details

### 6.1 Lamino → RainyModel

```
Lamino (Node.js)
  │
  │  POST /v1/chat/completions
  │  Authorization: Bearer <RAINYMODEL_MASTER_KEY>
  │  Model: rainymodel/auto | rainymodel/code | rainymodel/agent
  │
  └──▶ rm.orcest.ai
```

Lamino connects to RainyModel as an **OpenAI-compatible** provider. Workspaces are pre-configured:
- General/Persian workspace → `rainymodel/auto`
- Coding workspace → `rainymodel/code`
- Agent workspace → `rainymodel/agent`

### 6.2 Orcide → RainyModel

```
Orcide (VS Code fork)
  │
  │  POST /v1/chat/completions
  │  Authorization: Bearer <RAINYMODEL_MASTER_KEY>
  │  Model: rainymodel/chat | rainymodel/code
  │
  └──▶ rm.orcest.ai
```

Orcide treats RainyModel as an **OpenAI-Compatible** provider in its settings:
- Chat model: `rainymodel/chat`
- Quick Edit / Autocomplete: `rainymodel/code`
- Also supports direct connections to 15+ other providers (Anthropic, OpenAI, Ollama local, etc.)

### 6.3 Maestrist → RainyModel

```
Maestrist (OpenHands fork)
  │
  │  POST /v1/chat/completions
  │  Authorization: Bearer <RAINYMODEL_MASTER_KEY>
  │  Model: rainymodel/agent
  │  X-RainyModel-Policy: premium  (for agent tasks)
  │
  └──▶ rm.orcest.ai
```

Maestrist config (`config.toml`):
```toml
[llm]
base_url = "https://rm.orcest.ai/v1"
model = "rainymodel/agent"
api_key = "<RAINYMODEL_MASTER_KEY>"
```

### 6.4 OllamaFreeAPI → External Providers

```
OllamaFreeAPI
  │
  │  Proxies free Ollama-compatible requests
  │  to community/free endpoints
  │
  └──▶ Various free LLM providers
```

OllamaFreeAPI acts as an aggregator of free LLM inference endpoints and exposes them via an Ollama-compatible API.

---

## 7. Complete Request Flow

```
┌──────────┐
│  User    │  1. User sends message in Lamino/Orcide/Maestrist
└────┬─────┘
     │
     ▼
┌────────────┐
│ Client App │  2. Client app formats OpenAI-compatible request
│ (Lamino/   │     POST /v1/chat/completions
│  Orcide/   │     Authorization: Bearer <key>
│  Maestrist)│     {"model": "rainymodel/auto", "messages": [...]}
└────┬───────┘
     │ HTTPS
     ▼
┌────────────┐
│ RainyModel │  3. Authenticates Bearer token
│ rm.orcest  │  4. Resolves model alias → deployment list
│ .ai        │  5. Reads X-RainyModel-Policy header (default: auto)
│            │  6. Orders deployments by tier policy
└────┬───────┘
     │
     │  7. Sequential fallthrough
     │
     ├──────▶ HuggingFace Router (FREE)
     │         ├─ Success? → Return response + headers
     │         └─ Failure? → Try next ▼
     │
     ├──────▶ OllamaFreeAPI (FREE)
     │         ├─ Success? → Return response + headers
     │         └─ Failure? → Try next ▼
     │
     ├──────▶ Ollama Primary 16GB (INTERNAL)
     │         ├─ Success? → Return response + headers
     │         └─ Failure? → Try next ▼
     │
     ├──────▶ Ollama Secondary 8GB (INTERNAL)
     │         ├─ Success? → Return response + headers
     │         └─ Failure? → Try next ▼
     │
     └──────▶ OpenRouter (PREMIUM)
               ├─ Success? → Return response + headers
               └─ Failure? → Return 502 Bad Gateway

     8. Response includes observability headers:
        x-rainymodel-route: free|internal|premium
        x-rainymodel-upstream: hf|ollamafreeapi|ollama|openrouter
        x-rainymodel-model: actual-model-used
        x-rainymodel-latency-ms: 1234
```

---

## 8. Network & DNS

### 8.1 DNS Records

| Subdomain | Type | Target |
|-----------|------|--------|
| `orcest.ai` | A | 216.24.57.1 (Render) |
| `www` | CNAME | orcest-ai.onrender.com |
| `rm` | CNAME | rainymodel.onrender.com |
| `llm` | CNAME | llm-orcest-ai.onrender.com |
| `lamino` | CNAME | llm-orcest-ai.onrender.com |
| `ide` | CNAME | ide-orcest-ai.onrender.com |
| `orcide` | CNAME | ide-orcest-ai.onrender.com |
| `agent` | CNAME | agent-orcest-ai.onrender.com |
| `maestrist` | CNAME | agent-orcest-ai.onrender.com |
| `ollamafreeapi` | CNAME | ollamafreeapi.onrender.com |
| `login` | CNAME | login-orcest-ai.onrender.com |

### 8.2 Network Security

- All inter-service communication over **HTTPS**
- DigitalOcean Ollama: firewall restricts to SSH (22) + authorized IPs on port 11434
- Secrets stored in Render environment variables (never in git)
- CORS on RainyModel: allows all origins (services on different subdomains)
- CORS on Login: restricted to `*.orcest.ai`

---

## 9. Environment Variables Summary

### RainyModel (`rm.orcest.ai`)

| Variable | Purpose |
|----------|---------|
| `RAINYMODEL_MASTER_KEY` | Bearer token for API auth |
| `HF_TOKEN` | HuggingFace API token |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `OLLAMA_PRIMARY_URL` | Primary Ollama server (default: `http://164.92.147.36:11434`) |
| `OLLAMA_SECONDARY_URL` | Secondary Ollama server (default: `http://178.128.196.3:11434`) |
| `OLLAMA_API_KEY` | Ollama auth key (default: `ollama`) |
| `OLLAMAFREE_API_BASE` | OllamaFreeAPI base URL |
| `OLLAMAFREE_API_KEY` | OllamaFreeAPI key |
| `LITELLM_CONFIG_PATH` | Config YAML path |
| `RAINYMODEL_DEBUG` | Verbose logging |

### Login SSO (`login.orcest.ai`)

| Variable | Purpose |
|----------|---------|
| `SSO_SECRET_KEY` | Session/CSRF secret |
| `SSO_BASE_URL` | Base URL for JWT issuer |
| `SSO_ADMIN_EMAIL` | Initial admin email |
| `SSO_ADMIN_PASSWORD` | Initial admin password |
| `RSA_PRIVATE_KEY` | JWT signing key |
| `RSA_PUBLIC_KEY` | JWT verification key |
| `DATABASE_URL` | PostgreSQL connection string |
| `OIDC_*_SECRET` | Per-client OIDC secrets |

---

## 10. Architecture Diagram — All Connections

```
                         ┌─────────────────────┐
                         │     INTERNET         │
                         │   (End Users)        │
                         └──────────┬───────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │          Render.com            │
                    │          (HTTPS/TLS)           │
 ┌──────────────────┼───────────────────────────────┼──────────────────┐
 │                  │                               │                  │
 │   ┌──────────────▼──────────────┐                │                  │
 │   │        orcest.ai            │                │                  │
 │   │       (Landing Page)        │                │                  │
 │   └─────────────────────────────┘                │                  │
 │                                                  │                  │
 │   ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌─────▼─────┐           │
 │   │ Lamino  │  │ Orcide  │  │Maestrist │  │  Login    │           │
 │   │ llm.    │  │ ide.    │  │ agent.   │  │  SSO      │           │
 │   │         │  │         │  │          │  │ login.    │           │
 │   └────┬────┘  └────┬────┘  └────┬─────┘  └───────────┘           │
 │        │            │            │              ▲                   │
 │        │            │            │    OIDC ─────┘                   │
 │        │            │            │                                  │
 │        └────────────┴─────┬──────┘                                  │
 │                           │ OpenAI-compat API                       │
 │                           ▼                                         │
 │                  ┌─────────────────┐   ┌──────────────────┐        │
 │                  │   RainyModel    │   │  OllamaFreeAPI   │        │
 │                  │   rm.orcest.ai  ├──▶│  ollamafreeapi.  │        │
 │                  │                 │   │  orcest.ai       │        │
 │                  └───┬────────┬────┘   └──────────────────┘        │
 │                      │        │                                     │
 └──────────────────────┼────────┼─────────────────────────────────────┘
                        │        │
           ┌────────────┘        └────────────┐
           │                                  │
           ▼                                  ▼
  ┌──────────────────┐              ┌──────────────────┐
  │  HuggingFace     │              │   OpenRouter     │
  │  router.hf.co/v1 │              │ openrouter.ai    │
  │  (FREE)          │              │ /api/v1          │
  └──────────────────┘              │ (PREMIUM)        │
                                    └──────────────────┘
           │
           │   Private network
           ▼
  ┌──────────────────────────────────────────┐
  │        DigitalOcean                      │
  │                                          │
  │  ┌──────────────┐  ┌──────────────┐     │
  │  │ Ollama       │  │ Ollama       │     │
  │  │ Primary      │  │ Secondary    │     │
  │  │ 164.92.      │  │ 178.128.     │     │
  │  │ 147.36       │  │ 196.3        │     │
  │  │ 16GB CPU     │  │ 8GB CPU      │     │
  │  │              │  │              │     │
  │  │ qwen2.5:14b  │  │ qwen2.5:7b  │     │
  │  │ qwen2.5-     │  │ qwen2.5-    │     │
  │  │ coder:7b     │  │ coder:7b    │     │
  │  └──────────────┘  └──────────────┘     │
  │        (INTERNAL tier)                   │
  └──────────────────────────────────────────┘
```
