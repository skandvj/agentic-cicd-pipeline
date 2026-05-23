# Deployment

## Local Docker

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

