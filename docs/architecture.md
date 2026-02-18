# Orcest AI Architecture

## System Overview

```
                        +------------------+
                        |   orcest.ai      |  Landing page + API
                        |   (FastAPI)      |  orcest.ai
                        +------------------+
                                |
        +----------+------------+------------+-----------+
        |          |            |            |           |
   +----v----+ +---v----+ +----v----+ +-----v-----+ +---v------+
   | Lamino  | | Orcide | |Maestrist| | RainyModel| |  Login   |
   | (Chat)  | | (IDE)  | | (Agent) | | (LLM Proxy| |  (SSO)   |
   | llm.    | | ide.   | | agent.  | | rm.       | | login.   |
   +----+----+ +---+----+ +----+----+ +-----+-----+ +----------+
        |          |            |            |
        +----------+------------+            |
                   |                         |
            All LLM requests                 |
                   |                         |
                   +--------->---------------+
                                             |
                   +-------------------------+
                   |         RainyModel Routing
                   |
        +----------+----------+-----------+
        |                     |           |
   +----v--------+   +-------v---+  +----v--------+
   | FREE Tier   |   | INTERNAL  |  | PREMIUM     |
   |             |   |           |  |             |
   | ollamafree  |   | Ollama    |  | OpenRouter  |
   | api.orcest  |   | (DO CPU)  |  | openrouter  |
   | .ai         |   | 167.99.   |  | .ai/api/v1  |
   |             |   | 141.84    |  |             |
   | HF Router   |   | qwen2.5   |  | Premium     |
   | router.hf   |   | abliterate|  | models      |
   | .co/v1      |   | d:14b     |  |             |
   |             |   | coder:7b  |  |             |
   +-------------+   +-----------+  +-------------+
```

## Services

| Service | Domain | Stack | Hosting |
|---------|--------|-------|---------|
| Landing Page | orcest.ai | FastAPI | Render |
| Lamino | llm.orcest.ai | Node.js (AnythingLLM fork) | Render |
| Orcide | ide.orcest.ai | VS Code fork | Render |
| Maestrist | agent.orcest.ai | Python (OpenHands fork) | Render |
| RainyModel | rm.orcest.ai | FastAPI + LiteLLM | Render |
| Login Portal | login.orcest.ai | Authentik | Render + PostgreSQL |
| Ollama Backend | 167.99.141.84 | Ollama | DigitalOcean |
| Free Ollama API | ollamafreeapi.orcest.ai | Proxy | Render |

## Routing Flow

1. Client sends request to `rm.orcest.ai/v1/chat/completions`
2. RainyModel authenticates via `Authorization: Bearer <RAINYMODEL_MASTER_KEY>`
3. RainyModel resolves model alias (e.g., `rainymodel/auto`)
4. Routing policy determines tier:
   - **auto**: FREE -> INTERNAL -> PREMIUM
   - **uncensored**: INTERNAL -> FREE -> PREMIUM
   - **premium**: PREMIUM -> INTERNAL -> FREE
   - **free**: FREE only
5. Request forwarded to selected upstream
6. Response returned with observability headers

## Model Aliases

| Alias | Primary Use | Free Upstream | Internal Upstream | Premium Upstream |
|-------|------------|---------------|-------------------|-----------------|
| rainymodel/auto | General | ollamafreeapi / HF | Ollama qwen2.5 | OpenRouter |
| rainymodel/chat | Conversation | ollamafreeapi / HF | Ollama qwen2.5-abliterated | OpenRouter |
| rainymodel/code | Coding | ollamafreeapi / HF | Ollama qwen2.5-coder | OpenRouter |
| rainymodel/agent | Agent tasks | ollamafreeapi / HF | Ollama qwen2.5 | OpenRouter |

## Network Security

- DO Ollama: Firewall restricts inbound to SSH (22) and HTTPS (443)
- Ollama API (11434): Accessible only from authorized IPs
- All inter-service communication over HTTPS
- Secrets stored in Render environment variables (never in git)

## DNS Records

| Subdomain | Type | Target |
|-----------|------|--------|
| orcest.ai | A | 216.24.57.1 (Render) |
| www | CNAME | orcest-ai.onrender.com |
| rm | CNAME | rainymodel.onrender.com |
| llm | CNAME | llm-orcest-ai.onrender.com |
| lamino | CNAME | llm-orcest-ai.onrender.com |
| ide | CNAME | ide-orcest-ai.onrender.com |
| orcide | CNAME | ide-orcest-ai.onrender.com |
| agent | CNAME | agent-orcest-ai.onrender.com |
| maestrist | CNAME | agent-orcest-ai.onrender.com |
| ollamafreeapi | CNAME | ollamafreeapi.onrender.com |
| login | CNAME | login-orcest-ai.onrender.com |
