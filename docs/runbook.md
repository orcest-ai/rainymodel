# RainyModel Operations Runbook

## Rotating API Keys

### RainyModel Master Key
1. Generate new key: `openssl rand -hex 32` (prefix with `sk-rm-v1-`)
2. Update in Render Dashboard > rainymodel > Environment > `RAINYMODEL_MASTER_KEY`
3. Update in all consuming services:
   - Lamino: Render env `GENERIC_OPEN_AI_API_KEY`
   - Maestrist: Render env (or config.toml `api_key`)
   - Orcide: User settings (OpenAI-Compatible API Key)
4. Redeploy rainymodel service
5. Verify: `curl -H "Authorization: Bearer NEW_KEY" https://rm.orcest.ai/v1/models`

### HF Token
1. Revoke old token at https://huggingface.co/settings/tokens
2. Create new token with Inference Providers access
3. Update in Render: rainymodel > Environment > `HF_TOKEN`
4. Redeploy rainymodel

### OpenRouter API Key
1. Revoke at https://openrouter.ai/settings/keys
2. Create new key
3. Update in Render: rainymodel > Environment > `OPENROUTER_API_KEY`
4. Redeploy rainymodel

### DigitalOcean API Token
1. Revoke at https://cloud.digitalocean.com/account/api/tokens
2. Create new token
3. Update wherever stored (CI/CD, local env)

## Adding New Models to Ollama

1. SSH into DO droplet: `ssh root@167.99.141.84`
2. Pull model: `ollama pull <model-name>`
3. Verify: `ollama list`
4. Update `config/litellm_config.yaml` in rainymodel repo:
   - Add new model_list entry under appropriate alias
   - Set tier metadata
5. Commit, push, and deploy

## Changing Routing Policy

### Default routing order
Edit `app/routing.py` in the `select_deployment()` method:
- Modify tier order in the routing policy logic
- Commit and deploy

### Per-request policy
Clients can set `X-RainyModel-Policy` header:
- `auto`: FREE -> INTERNAL -> PREMIUM (default)
- `uncensored`: INTERNAL -> FREE -> PREMIUM
- `premium`: PREMIUM -> INTERNAL -> FREE
- `free`: FREE only

## Monitoring

### Health Checks
- RainyModel: `curl https://rm.orcest.ai/health`
- Ollama: `curl http://167.99.141.84:11434/api/tags`
- Landing: `curl https://orcest.ai/health`
- Login: `curl https://login.orcest.ai/-/health/live/`

### Response Headers
Every RainyModel response includes:
- `x-rainymodel-route`: which tier was used
- `x-rainymodel-upstream`: which provider
- `x-rainymodel-model`: actual model name
- `x-rainymodel-latency-ms`: request latency

### Logs
- Render Dashboard > Service > Logs (real-time)
- DO Ollama: `ssh root@167.99.141.84` then `journalctl -u ollama -f`

## Troubleshooting

### RainyModel returns 503
1. Check if upstream is reachable
2. Check Render logs for error details
3. Verify env vars are set correctly
4. Check if circuit breaker has tripped (wait for cooldown)

### Ollama not responding
1. SSH into droplet: `ssh root@167.99.141.84`
2. Check service: `systemctl status ollama`
3. Restart if needed: `systemctl restart ollama`
4. Check disk space: `df -h`
5. Check memory: `free -h`

### HF credits exhausted
- RainyModel auto-detects and falls back to INTERNAL/PREMIUM
- Check HF usage at https://huggingface.co/settings/billing
- Credits reset monthly

## Backup & Recovery

### Database (Authentik)
- Render PostgreSQL has automatic daily backups
- Manual backup: Render Dashboard > Database > Backups

### Ollama Models
- Models can be re-pulled if droplet is recreated
- No persistent data beyond model weights

### Configuration
- All config is in git (orcest-ai org repos)
- Secrets are in Render environment variables
- DNS records managed via Name.com
