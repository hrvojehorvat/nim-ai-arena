#!/usr/bin/env bash
# Build the image, push it to ghcr.io, and create or update the Azure Container App.
# Safe to re-run: the first run creates everything, later runs only roll out a new image.
#
#   ./deploy/azure.sh            # build + push + deploy
#   ./deploy/azure.sh --no-build # redeploy the image of the current commit (already pushed)
#
# Reads secrets from backend/.env without printing them:
#   GROQ_API_KEY         -> Groq agents (free tier)
#   CLOUD_DATABASE_URL   -> optional: free external Postgres (Neon/Supabase); empty = no history
#   GHCR_PULL_TOKEN      -> optional: a GitHub token with ONLY read:packages, so Azure can pull a
#                           private image; empty = the ghcr package must be public
# Modal and Ollama variables are deliberately not passed: those agents stay local-only.
# Costs: Container Apps consumption plan, min 0 / max 1 replica, no Log Analytics workspace;
# stays inside the monthly free grant for a hobby project.
set -euo pipefail

GH_USER="${GH_USER:-hrvojehorvat}"
RG="${RG:-nim-arena-rg}"
LOCATION="${LOCATION:-westeurope}"
ENV_NAME="${ENV_NAME:-nim-arena-env}"
APP="${APP:-nim-arena}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
IMAGE="ghcr.io/$GH_USER/nim-arena:$TAG"

# One value from backend/.env (python-dotenv parsing, so quotes and '&' in URLs are fine).
envval() {
  (cd "$REPO_ROOT/backend" && unset VIRTUAL_ENV && uv run --quiet python -c \
    "import sys; from dotenv import dotenv_values; print(dotenv_values('.env').get(sys.argv[1]) or '')" "$1")
}

if [[ "${1:-}" != "--no-build" ]]; then
  if [[ -n "$(git -C "$REPO_ROOT" status --porcelain -- . ':!backend/notebooks')" ]]; then
    echo "Uncommitted changes: the image tag is the commit, so commit first." >&2
    exit 1
  fi
  echo "==> build $IMAGE"
  docker build -t "$IMAGE" "$REPO_ROOT"
  echo "==> push (logs in to ghcr.io with your gh CLI token)"
  gh auth token | docker login ghcr.io -u "$GH_USER" --password-stdin >/dev/null
  docker push "$IMAGE"
fi

GROQ_API_KEY="$(envval GROQ_API_KEY)"
DATABASE_URL="$(envval CLOUD_DATABASE_URL)"
PULL_TOKEN="$(envval GHCR_PULL_TOKEN)"

secrets=()
env_vars=("AGENT_MOVE_DELAY=1.5")
if [[ -n "$GROQ_API_KEY" ]]; then
  secrets+=("groq-key=$GROQ_API_KEY")
  env_vars+=("GROQ_API_KEY=secretref:groq-key")
fi
if [[ -n "$DATABASE_URL" ]]; then
  secrets+=("db-url=$DATABASE_URL")
  env_vars+=("DATABASE_URL=secretref:db-url")
fi

if ! az group show -n "$RG" -o none 2>/dev/null; then
  echo "==> create resource group $RG ($LOCATION)"
  az group create -n "$RG" -l "$LOCATION" -o none
fi
if ! az containerapp env show -n "$ENV_NAME" -g "$RG" -o none 2>/dev/null; then
  echo "==> create Container Apps environment $ENV_NAME (no Log Analytics: nothing billed for logs)"
  az containerapp env create -n "$ENV_NAME" -g "$RG" -l "$LOCATION" --logs-destination none -o none
fi

if ! az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  echo "==> create Container App $APP"
  args=(--image "$IMAGE" --ingress external --target-port 8000
    --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1.0Gi --env-vars "${env_vars[@]}")
  if [[ -n "$PULL_TOKEN" ]]; then
    args+=(--registry-server ghcr.io --registry-username "$GH_USER" --registry-password "$PULL_TOKEN")
  fi
  if [[ ${#secrets[@]} -gt 0 ]]; then args+=(--secrets "${secrets[@]}"); fi
  az containerapp create -n "$APP" -g "$RG" --environment "$ENV_NAME" "${args[@]}" -o none
else
  echo "==> update Container App $APP -> $IMAGE"
  if [[ ${#secrets[@]} -gt 0 ]]; then
    az containerapp secret set -n "$APP" -g "$RG" --secrets "${secrets[@]}" -o none
  fi
  # One replica only: matches live in memory (see docs/architecture.md, Phase 7.1).
  az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" \
    --min-replicas 0 --max-replicas 1 --set-env-vars "${env_vars[@]}" -o none
fi

FQDN="$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
echo "==> live at https://$FQDN  (first request after idle takes a few seconds: scale from zero)"
