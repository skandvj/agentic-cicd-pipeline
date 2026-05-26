# Vercel Deployment

Vercel supports FastAPI deployments by exporting a `FastAPI` instance from an entrypoint such as `app.py`, and serves static assets from `public/**`. This repo includes both:

- `app.py`: imports the production runtime from `src.runtime.server`.
- `public/`: recruiter-friendly control center and guided wizard.
- `vercel.json`: routes `/health`, `/v1/**`, `/api/**`, `/metrics`, and `/docs` to the FastAPI function.

## Required Production Services

Use Vercel Marketplace storage for managed dependencies:

- Postgres: Neon, Supabase, or AWS Aurora Postgres.
- Redis/KV: Upstash Redis or another Redis provider.

Required Vercel environment variables:

```bash
RUNTIME_MODE=production
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg2://...
REDIS_URL=redis://...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
TOOL_BACKEND=http
TOOL_HTTP_BASE_URL=https://your-tools.example.com
EVAL_JUDGE_PROVIDER=openai
EVAL_JUDGE_MODEL=gpt-4o-mini
```

For MCP-backed tools, replace `TOOL_BACKEND=http` with:

```bash
TOOL_BACKEND=mcp
TOOL_MCP_ENDPOINT=https://your-mcp.example.com/messages
```

## Deploy

```bash
npm i -g vercel
vercel link
vercel env pull .env.vercel
vercel deploy --prod
```

After deployment:

```bash
curl -f https://your-app.vercel.app/health
curl -X POST https://your-app.vercel.app/v1/agents/customer-support-agent/invoke \
  -H "Content-Type: application/json" \
  -d '{"message":"How do I reset my password?"}'
```

## Notes

FastAPI on Vercel runs as a Vercel Function, so long-running eval batches should remain in CI or a container worker. The public wizard is intended for live product walkthroughs, agent invocation, and observability queries.
