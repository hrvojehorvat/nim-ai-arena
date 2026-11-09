# Deploying to Azure (free tiers)

One container on **Azure Container Apps** runs the backend and serves the frontend
(image built from the root `Dockerfile`, pushed to **GitHub Container Registry**). Match history uses a
**free external Postgres** (Neon or Supabase); without one the app runs and only History is disabled.

| Piece | Service | Cost |
|---|---|---|
| Image | ghcr.io (`ghcr.io/hrvojehorvat/nim-arena:<commit>`) | free |
| App | Container Apps, consumption plan, 0.5 vCPU / 1 GiB, **min 0 / max 1 replica**, no Log Analytics | free monthly grant (scales to zero when idle) |
| Database | Neon / Supabase free tier | free |
| LLM agents | Groq free tier (`GROQ_API_KEY`) | free, rate-limited by Groq |

Modal (paid credits) and Ollama (local) are **not** deployed: their variables are simply not passed, so
those agents don't appear. **Max 1 replica** is required: matches live in process memory.

## One-time setup
1. **Tools:** `az login`, `gh auth login` with the `write:packages` scope
   (`gh auth refresh -s write:packages`), Docker running.
2. **Database (optional):** create a free Postgres on neon.tech or supabase.com, copy the connection
   string and add it to `backend/.env` as
   `CLOUD_DATABASE_URL=postgresql://user:pass@host/db?sslmode=require`.
   Remove `&channel_binding=require` if Neon adds it (asyncpg doesn't take that parameter), and use the
   **direct** host (drop `-pooler` from the hostname): the app keeps its own pool, and asyncpg's
   prepared statements don't work through Neon's PgBouncer pooler.
   Current setup: Neon project `weathered-fire-47331056` (AWS Frankfurt, free plan), database `neondb`.
   Migrations run automatically on startup.
3. **Image access:** either make the ghcr package public after the first push (GitHub → your profile →
   Packages → nim-arena → Package settings → Change visibility; the image has no secrets, but it does
   contain the code), **or** create a classic token with only `read:packages` and add it to
   `backend/.env` as `GHCR_PULL_TOKEN=...` *before* the first deploy.

## Deploy (and every redeploy)
```bash
cd /Users/hrvoje/ai/private/nimm_ai_arena
git status                # must be clean: the image tag is the commit
./deploy/azure.sh         # build, push, create or update; prints the https URL
./deploy/azure.sh --no-build   # roll out the already-pushed image of this commit again
```
The first run creates resource group `nim-arena-rg` (westeurope), environment `nim-arena-env` and app
`nim-arena`. Secrets go into Container App secrets (`groq-key`, `db-url`) and are referenced from env
vars; they never enter the image or the script output.

## Check it
```bash
URL=https://$(az containerapp show -n nim-arena -g nim-arena-rg --query properties.configuration.ingress.fqdn -o tsv)
curl -s $URL/health       # {"status":"ok","db":"ok"}  (or "db":"disabled" without CLOUD_DATABASE_URL)
curl -s $URL/agents       # nim_optimal, random, groq_* agents
```
Open `$URL` and play; the first request after idle takes a few seconds (scale from zero).

## Logs, stop, remove
```bash
az containerapp logs show -n nim-arena -g nim-arena-rg --follow     # live console output
az containerapp ingress disable -n nim-arena -g nim-arena-rg        # take it offline (no traffic, scales to 0)
az group delete -n nim-arena-rg                                        # remove everything in Azure
```
