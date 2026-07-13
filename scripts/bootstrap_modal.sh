#!/usr/bin/env bash
# One-shot setup of the Modal side for a (new) Langfuse project:
#   1. writes the `internal-ax-project` Modal secret from .env (Langfuse keys
#      + WEBHOOK_SECRET, generated and persisted to .env if missing)
#   2. deploys the app
#   3. prints the exact webhook URL to paste into Langfuse
#
# The base `internal-ax` secret (ANTHROPIC_API_KEY, OPENAI_API_KEY) is left
# untouched; the project secret is layered on top of it at runtime.
#
#   bash scripts/bootstrap_modal.sh
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo ".env missing — copy .env.example and fill in LANGFUSE_*"; exit 1; }
set -a; source .env; set +a

: "${LANGFUSE_PUBLIC_KEY:?set in .env}"
: "${LANGFUSE_SECRET_KEY:?set in .env}"
: "${LANGFUSE_BASE_URL:=https://cloud.langfuse.com}"

if [ -z "${WEBHOOK_SECRET:-}" ]; then
  WEBHOOK_SECRET="$(openssl rand -hex 24)"
  printf '\nWEBHOOK_SECRET="%s"\n' "$WEBHOOK_SECRET" >> .env
  echo "Generated WEBHOOK_SECRET and appended it to .env"
fi

MODAL="${MODAL_BIN:-.venv/bin/modal}"

SECRET_ARGS=(
  LANGFUSE_PUBLIC_KEY="$LANGFUSE_PUBLIC_KEY"
  LANGFUSE_SECRET_KEY="$LANGFUSE_SECRET_KEY"
  LANGFUSE_BASE_URL="$LANGFUSE_BASE_URL"
  WEBHOOK_SECRET="$WEBHOOK_SECRET"
)
# Optional separate scratch project the agents get as their LANGFUSE_* env.
if [ -n "${SANDBOX_LANGFUSE_PUBLIC_KEY:-}" ]; then
  SECRET_ARGS+=(
    SANDBOX_LANGFUSE_PUBLIC_KEY="$SANDBOX_LANGFUSE_PUBLIC_KEY"
    SANDBOX_LANGFUSE_SECRET_KEY="${SANDBOX_LANGFUSE_SECRET_KEY:?set in .env}"
    SANDBOX_LANGFUSE_BASE_URL="${SANDBOX_LANGFUSE_BASE_URL:-$LANGFUSE_BASE_URL}"
  )
  echo "Including sandbox Langfuse project keys (agents get these as LANGFUSE_*)"
fi

"$MODAL" secret create internal-ax-project "${SECRET_ARGS[@]}" --force

"$MODAL" deploy -m internal_ax.app

URL="$("${MODAL%modal}python" - <<'EOF'
import modal
print(modal.Function.from_name("internal-ax", "webhook").get_web_url())
EOF
)"

echo
echo "Webhook URL for the Langfuse remote experiment trigger:"
echo "  ${URL}?token=${WEBHOOK_SECRET}"
