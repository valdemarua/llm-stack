# Agent instructions

## Project
A portable, self-contained Docker Compose stack for local LLM inference and a unified OpenAI-compatible API. Services: Ollama (inference), LiteLLM (gateway and admin UI), PostgreSQL (gateway state).

## Guidelines
- Keep the stack minimal, CPU-first and hosting-agnostic. Dokploy is an optional deployment target.
- Prefer official images with explicit version tags; verify upstream releases and security advisories before updating.
- Keep PostgreSQL and Ollama private. Expose only LiteLLM; require authentication and TLS for remote access.
- Never commit credentials, real infrastructure addresses, or database dumps. Keep .env.example synchronized with Compose.
- Preserve named volumes and encryption secrets across deployments. Document migrations and backup/restore changes.
- Keep business logic, prompts and project-specific model choices outside this repository.
- Use English for documentation. Keep README commands and service names synchronized.

## Validation
Run docker compose config with a populated local .env, then docker compose up -d and docker compose ps. Check /health/liveliness, load an Ollama model, register it in LiteLLM, and test an authenticated chat completion. Do not claim runtime validation unless performed.
