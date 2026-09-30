---
title: DriftWatch
emoji: 📉
colorFrom: gray
colorTo: yellow
sdk: docker
app_port: 3000
pinned: false
---

# DriftWatch dashboard (Hugging Face Space)

This Space hosts the Next.js dashboard (`frontend/`), built via
`deploy/huggingface_space/Dockerfile`. The FastAPI monitor service is
hosted separately on Render/Railway (see `deploy/render.yaml`) — this
Space is frontend-only.

## Setup

1. Push this repo's contents to a new HF Space with SDK "Docker".
2. Set the Space secret/variable `NEXT_PUBLIC_MONITOR_API_URL` to the
   deployed monitor's public URL (e.g. `https://driftwatch-monitor.onrender.com`).
   Next.js bakes `NEXT_PUBLIC_*` vars in at build time, so the Space must
   rebuild after changing this value.
3. The Space builds and runs on port 3000 (`app_port` above).

Streamlit was the spec's original fastest-path frontend choice; this
project uses Next.js/React instead per D-009, so the Space uses the
Docker SDK rather than the native Streamlit SDK.
