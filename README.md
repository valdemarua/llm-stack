# LLM Stack

A self-hosted LLM stack with a unified OpenAI-compatible API, local model inference, and cloud provider integration. Powered by Docker Compose.

## Architecture

Applications → LiteLLM → Ollama or cloud providers

PostgreSQL stores gateway state, virtual keys, users and model configuration. All three services run in one Compose project.

## Quick start

Requires Docker Engine and Docker Compose v2. CPU inference is the default.

```sh
cp .env.example .env
```

Generate three independent secrets using `openssl rand -hex 32`. Set POSTGRES_PASSWORD, LITELLM_MASTER_KEY (prefix with sk-), and LITELLM_SALT_KEY. Keep the database password hexadecimal to avoid URL escaping issues.

```sh
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose exec ollama ollama pull qwen3:4b
```

Open http://localhost:4000/ui. Use the default admin login and master key (see [LiteLLM UI documentation](https://docs.litellm.ai/docs/proxy/ui)).

Register an Ollama chat model with alias content-fast, provider model ollama_chat/qwen3:4b and API base http://ollama:11434. Create a virtual API key restricted to the alias. Set LLM_API_KEY in your shell to that key.

```sh
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LLM_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"content-fast","messages":[{"role":"user","content":"Write a short movie review title."}]}'
```

Cloud models can be added separately through the UI. Model weights are not downloaded automatically.

## Dokploy

Create a Compose application from this repository with docker-compose.yml. Set the required secrets in the Environment UI. Configure a TLS domain targeting litellm on container port 4000. Keep the default loopback host binding; the reverse proxy should reach the container over its network. Deploy and use Dokploy's container terminal to pull models. Register models and generate keys in LiteLLM UI.

## Backup and restore

Configure scheduled PostgreSQL backups in Dokploy's Compose Backups UI, targeting service postgres and database litellm, or run:

```sh
docker compose exec -T postgres pg_dump -U litellm -d litellm -Fc > litellm.dump
```

Store encrypted dumps off-site. Securely retain the original master and salt keys. Restore into a compatible stack with the same secrets:

```sh
docker compose stop litellm
docker compose exec -T postgres pg_restore -U litellm -d litellm --clean --if-exists --exit-on-error < litellm.dump
docker compose start litellm
```

Warning: --clean replaces existing database objects. Verify keys, model configuration and a test invocation after restoration. Ollama models can be downloaded again; preserve custom artifacts separately.

## Security and operations

Only LiteLLM publishes a host port, bound to loopback by default. Use TLS for remote access and restrict admin access where practical. Use scoped virtual keys rather than the master key in applications. Never commit credentials or database dumps. Review upstream security advisories before deployment. Limit inference resources on shared production hosts. Do not use docker compose down -v unless intentionally deleting persistent data.

## Status

Initial configuration. Image availability, runtime deployment and restore testing are pending.

## License

License selection pending.
