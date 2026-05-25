# Deployment

## Local Docker Demo

```bash
cp .env.example .env
docker compose up -d
curl -f http://localhost:8000/health
curl http://localhost:9090/api/v1/query?query=agent_invocation_total
curl -f http://localhost:3000/api/dashboards/home
```

Services:

- runtime: `http://localhost:8000`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

This uses `.env.example`, which defaults to `RUNTIME_MODE=demo`, deterministic providers, mock tools, and an in-container PostgreSQL database. It is useful for local validation, not for live users.

## Production Docker Runtime

Create an environment file from real secrets:

```bash
RUNTIME_MODE=production
ENVIRONMENT=production
RUNTIME_IMAGE=ghcr.io/skandvj/agentic-cicd-pipeline/runtime:<validated-sha>
DATABASE_URL=postgresql+psycopg2://agent_user:...@db.example.com:5432/agentic_cicd
REDIS_URL=redis://redis.example.com:6379/0
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
TOOL_BACKEND=http
TOOL_HTTP_BASE_URL=https://tools.example.com
EVAL_JUDGE_PROVIDER=openai
EVAL_JUDGE_MODEL=gpt-4o-mini
```

Then verify and start:

```bash
python scripts/check_production_config.py
python scripts/init_db.py
docker compose up -d --no-build runtime
curl -f http://localhost:8000/health
```

Use `TOOL_BACKEND=mcp` and `TOOL_MCP_ENDPOINT` instead of HTTP when your enterprise integrations are exposed through MCP.

## GitHub Environments

Create `staging` and `production` environments in GitHub. Store these secrets:

- `STAGING_DATABASE_URL`, `STAGING_REDIS_URL`
- `PROD_DATABASE_URL`, `PROD_REDIS_URL`
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- `TOOL_BACKEND`
- `TOOL_HTTP_BASE_URL` or `TOOL_MCP_ENDPOINT`
- `EVAL_JUDGE_PROVIDER`, `EVAL_JUDGE_MODEL`
- optional: `SLACK_WEBHOOK_URL`

Useful environment variables:

- `AUTO_PROMOTE_PROD=true` dispatches `deploy-prod.yml` after staging evals pass.
- `TOOL_TIMEOUT_SECONDS` and `TOOL_RETRIES` tune live tool calls.

## AWS Terraform

```bash
cd infra/terraform
terraform init
terraform plan \
  -var environment=staging \
  -var region=us-east-1 \
  -var db_username=agent_user \
  -var db_password='replace-me'
terraform apply
```

Use AWS Secrets Manager or your CI secret store for database credentials in real environments. The variables are marked sensitive, but the sample command is only for local experimentation.

## GCP and Azure

The runtime is containerized and stateless except for PostgreSQL, Redis, and object/log storage. Equivalent managed services are:

- GCP: Cloud Run or GKE, Artifact Registry, Cloud SQL PostgreSQL, Memorystore Redis, Cloud Load Balancing.
- Azure: Container Apps or AKS, Azure Container Registry, Azure Database for PostgreSQL, Azure Cache for Redis, Application Gateway.

Keep the same health path (`/health`), Prometheus path (`/metrics`), and environment variables from `.env.example`.
