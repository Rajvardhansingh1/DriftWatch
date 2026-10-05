#!/usr/bin/env bash
# Usage: deploy/push_space.sh <backend|frontend> <hf-user>/<space-name>
# Needs an HF write token: git will prompt (user = HF username, password = token).
set -euo pipefail
kind=$1; space=$2
root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
git clone "https://huggingface.co/spaces/$space" "$tmp/space"
cd "$tmp/space"
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
src=$root/deploy/huggingface_space
if [ "$kind" = backend ]; then
  cp "$src/backend/Dockerfile" "$src/backend/README.md" .
  cp -r "$root"/{monitor,demo_bot,data,schemas,requirements.txt} .
else
  cp "$src/Dockerfile" "$src/README.md" .
  cp -r "$root/frontend" .
fi
rm -f data/*.sqlite3* ; rm -rf data/baseline_embeddings
find . -name __pycache__ -prune -exec rm -rf {} + ; rm -rf frontend/node_modules frontend/.next
git add -A && git commit -m "Deploy $kind" && git push
