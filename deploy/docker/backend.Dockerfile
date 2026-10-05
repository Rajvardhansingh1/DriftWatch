# Local/self-hosted image for the FastAPI monitor (e.g. an Oracle free VM).
# Not used by the Render+Vercel deploy. Build context = repo root:
#   docker build -f deploy/docker/backend.Dockerfile -t dw-backend .
FROM python:3.11-slim
RUN useradd -m -u 1000 user
WORKDIR /app
ENV HF_HOME=/app/.hf-cache PYTHONUNBUFFERED=1
COPY requirements.txt .
# CPU-only torch first: the default Linux wheel bundles CUDA (~2 GB).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt
# Bake embedding model into the image so cold starts never hit the Hub.
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('all-MiniLM-L6-v2')"
COPY . .
RUN chown -R user:user /app
USER user
ENV DRIFTWATCH_DB_PATH=/app/data/driftwatch.sqlite3
EXPOSE 7860
CMD ["sh", "-c", "uvicorn monitor.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
