# Team Onboarding: Using Orcest AI Services via RainyModel

## Overview

All Orcest AI services (Lamino, Maestrist, Orcide) route their LLM requests through **RainyModel** (`rm.orcest.ai`), a unified proxy that automatically selects the best backend.

## For Developers

### Using Orcide (AI Code Editor)

1. Download/access Orcide at `ide.orcest.ai`
2. Open Settings > Providers
3. Select **OpenAI-Compatible**
4. Set:
   - **baseURL**: `https://rm.orcest.ai/v1`
   - **API Key**: (get from admin)
5. Add models:
   - Chat: `rainymodel/chat`
   - Quick Edit: `rainymodel/code`
   - Autocomplete: `rainymodel/code`

### Using Lamino (AI Chat)

1. Visit `llm.orcest.ai`
2. Login with your Orcest AI credentials
3. Default workspaces are pre-configured:
   - **General/Persian**: uses `rainymodel/auto`
   - **Coding**: uses `rainymodel/code`
   - **Agent/Complex**: uses `rainymodel/agent`

### Using Maestrist (AI Agent)

1. Visit `agent.orcest.ai`
2. Login with your Orcest AI credentials
3. Default model: `rainymodel/agent` (optimized for agent workflows)
4. For CLI/headless:
   ```toml
   [llm]
   base_url = "https://rm.orcest.ai/v1"
   model = "rainymodel/agent"
   api_key = "YOUR_KEY"
   ```

### Direct API Usage

```bash
curl https://rm.orcest.ai/v1/chat/completions \
  -H "Authorization: Bearer YOUR_RAINYMODEL_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rainymodel/auto",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Available Models

| Model | Best For |
|-------|---------|
| `rainymodel/auto` | General tasks, cost-optimized |
| `rainymodel/chat` | Conversations, Persian |
| `rainymodel/code` | Code generation, completion |
| `rainymodel/agent` | Complex agent tasks, long context |

### Routing Policies

By default, RainyModel routes: FREE -> INTERNAL -> PREMIUM.

Override per-request with a header:
```bash
curl https://rm.orcest.ai/v1/chat/completions \
  -H "X-RainyModel-Policy: uncensored" \
  ...
```

| Policy | Routing Order |
|--------|--------------|
| `auto` | FREE -> INTERNAL -> PREMIUM |
| `uncensored` | INTERNAL -> FREE -> PREMIUM |
| `premium` | PREMIUM -> INTERNAL -> FREE |
| `free` | FREE only |

## For Admins

### Service URLs

| Service | URL | Purpose |
|---------|-----|---------|
| orcest.ai | https://orcest.ai | Landing page + API |
| Lamino | https://llm.orcest.ai | AI Chat |
| Orcide | https://ide.orcest.ai | AI Code Editor |
| Maestrist | https://agent.orcest.ai | AI Agent |
| RainyModel | https://rm.orcest.ai | LLM Proxy |
| Login | https://login.orcest.ai | SSO Portal |
| Free Ollama | https://ollamafreeapi.orcest.ai | Free Ollama API |

### Observability

Check response headers for routing info:
```
x-rainymodel-route: free|internal|premium
x-rainymodel-upstream: ollamafreeapi|hf|ollama|openrouter
x-rainymodel-model: actual-model-name
x-rainymodel-latency-ms: 1234
```

### Adding New Team Members

1. Create account at `login.orcest.ai`
2. Admin assigns appropriate roles
3. Share RainyModel API key (or create per-user virtual key)
4. Direct to this onboarding doc

### Support

Email: admin@danial.ai
