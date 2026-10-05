# Deployment

Target: monitor API on **Render** (native Python runtime, no Docker), dashboard on **Vercel** (native Next.js, no Docker). Database: **Supabase** (durable cloud data). Local SQLite stays local.

## 1. Monitor on Render

`render.yaml` (repo root) is the Blueprint. Render → New → Blueprint → pick the repo, then then fill the `sync: false` secrets in the Render dashboard:

| Variable | Value |
|---|---|
| `GROQ_API_KEY`, `GOOGLE_API_KEY` | provider keys (optional; simulated client if unset) |
| `DRIFTWATCH_CORS_ORIGINS` | your Vercel origin, e.g. `https://driftwatch.vercel.app` (no trailing slash) |
| `SUPABASE_URL` | `https://zaodlvgqowhdqobvvhpx.supabase.co` |
| `SUPABASE_ANON_KEY` | Supabase publishable/anon key (Project Settings → API) |
| `SUPABASE_JWT_SECRET` | Supabase JWT secret (Project Settings → API → JWT). Server-only, never in Vercel |
| `PLATFORM_ADMIN_USER_IDS` | comma-separated Supabase auth user ids allowed to use `/api/admin/*` |

Health: `/api/health` (liveness), `/api/ready` (DB reachable; Render's health check uses this).

Memory: the blueprint installs `requirements-lean.txt` and sets `DRIFTWATCH_EMBEDDER=onnx` (fastembed/ONNX, same MiniLM model, no torch) so it fits 512 MB. If it still runs out of memory, use Render Starter (~$7/mo) or the Docker image below.

Free-tier caveats: 512 MB RAM, service sleeps after ~15 min idle (cold start 20–30 s), SQLite is ephemeral, and quotas are in-process per instance.

## 2. Dashboard on Vercel

1. New project → import the repo.
2. **Root Directory:** `frontend`. Framework: Next.js (auto-detected). No Dockerfile needed.
3. Environment variables (Production and Preview):

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_MONITOR_API_URL` | Render service URL, e.g. `https://driftwatch-monitor.onrender.com` |
| `NEXT_PUBLIC_SUPABASE_URL` | same as `SUPABASE_URL` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | same as `SUPABASE_ANON_KEY` (publishable key only) |

Never put `SUPABASE_JWT_SECRET`, `GROQ_API_KEY`, or any service-role key in Vercel. `NEXT_PUBLIC_*` values are visible in the browser by design.

## 3. Order of operations

1. Apply Supabase migrations `0001`–`0004` (see `supabase/`).
2. Deploy Render, set its variables, confirm `/api/ready` returns 200.
3. Deploy Vercel with the Render URL. Copy the Vercel origin back into Render's `DRIFTWATCH_CORS_ORIGINS`, then redeploy Render.
4. Smoke test: open the dashboard, run a scenario, sign in at `/auth/sign-in`, open `/admin`.

## Optional: Docker (local test / self-hosting)

Not part of the Render+Vercel deploy. Run from the repo root:

```powershell
docker build -f deploy/docker/backend.Dockerfile -t dw-backend .
docker run --rm -p 7860:7860 --env-file .env dw-backend
docker build -f deploy/docker/frontend.Dockerfile --build-arg NEXT_PUBLIC_MONITOR_API_URL=http://localhost:7860 -t dw-ui .
docker run --rm -p 3000:3000 dw-ui
```

The backend image uses torch and needs ~1 GB RAM. Hugging Face Docker Spaces need a paid plan, so they are not used.
